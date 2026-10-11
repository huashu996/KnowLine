"""Acquire the selected graph papers before publication, with verified PDF reuse."""
import asyncio,time
from urllib.parse import urlsplit
from . import paper_bibliography as bibliography
from .institutional_access import validate_pdf
from .safety import DomainError,digest
from .store import uid


def source_failure(exc,fallback):
    code=getattr(exc,'code',None)
    # urllib HTTPError.code is numeric; DomainError.code is textual. Preserve
    # a bounded source failure instead of breaking the entire batch's report.
    if isinstance(code,int):return 'public_source_http_'+str(code)
    return code if isinstance(code,str) and code else fallback


def verified_resources(store,node,record):
    keys={'doi:'+str(node.get('doi') or '').lower(),'arxiv:'+str(node.get('arxiv_id') or '')}-{'doi:','arxiv:'}
    if record:keys.update({record['identity_key'],*record.get('related_identifiers',[])})
    found=[]
    for resource in store.resources():
        metadata=resource['metadata']
        linked=record and (resource['id'] in record.get('resource_ids',[]) or metadata.get('publication_record_id')==record['id'])
        if resource['type']!='paper' or resource['state']!='ready' or (not linked and 'doi:'+str(metadata.get('doi') or '').lower() not in keys and 'arxiv:'+str(metadata.get('arxiv_id') or '') not in keys):continue
        try:
            snapshot=store.snapshot(resource)
            if digest(snapshot)!=resource['sha256']:continue
            identity=metadata.get('pdf_identity') or {'title':node['title'],'authors':node['authors'],'doi':metadata.get('doi') or node.get('doi'),'arxiv_id':metadata.get('arxiv_id') or node.get('arxiv_id')}
            validate_pdf(snapshot,{**(record or node),'citation_record':record or {},'pdf_identity':identity,'pdf_version':metadata.get('pdf_version','unknown')})
            found.append(resource)
        except (DomainError,OSError,ValueError,TypeError,KeyError):continue
    return found


async def acquire_node(store,job,node,write,broker,domain=None,active_check=None):
    from .research_enrich import matching
    from .research_import import choices
    from .research_download import acquire,locate_proceedings,locate_openalex,locate_public,locate_index
    start=time.monotonic();failures=[];attempted=set()
    record=matching(node,bibliography.rows(store),store)
    historical=record or matching(node,bibliography.rows(store),store,max_age=None)
    def active():
        if active_check:return active_check()
        if store.job(job['id'])['status'] not in {'running','waiting_user'}:raise asyncio.CancelledError()
    async def guarded_write(kind,clean,action):
        def guarded():
            # Store.mutate rolls back Exception; cancellation is BaseException.
            try:active()
            except asyncio.CancelledError:raise DomainError('originating_task_stopped',409)
            return action()
        return await write(kind,clean,guarded)
    active()
    # Domain membership applies to the citation record as well as the file,
    # including the early return when a verified local PDF already exists.
    if record and domain and domain not in record['domain_ids']:
        record=await guarded_write('graph_pdf_domain',{'operation_id':uid('op')},lambda:bibliography.save(store,record,domain))
        historical=record
    resources=verified_resources(store,node,historical)
    if resources:
        resource=resources[0]
        def reuse():
            current=resource
            # Old identity evidence permits local reuse, never claims a new
            # publication check or replaces formal metadata with stale data.
            if record:current=bibliography.attach(store,record,resource['id'],resource['metadata'].get('pdf_identity'))
            if domain:
                group=next(g for g in store.groups() if g['id']==domain)
                if current['id'] not in group['resource_ids']:store.group_members(domain,{'base_revision':group['revision'],'resource_ids':[*group['resource_ids'],current['id']]})
            return current
        resource=await guarded_write('graph_pdf_reuse',{'operation_id':uid('op')},reuse)
        return {'resource_id':resource['id'],'version_id':resource['version_id'],'sha256':resource['sha256'],'duplicate':True,'new_download':False,'metadata_status':record.get('metadata_status') if record else 'needs_review','duration_seconds':round(time.monotonic()-start,3)}
    if not record:return {'unavailable_reason':node.get('metadata_refresh_reason','current_publication_not_verified'),'metadata_status':'needs_review'}
    async def try_sources(sources):
        for source in sources:
            active()
            url=source.get('access_url') or source.get('publisher_url')
            if source.get('public_oa') is not True or url in attempted:continue
            attempted.add(url)
            try:
                result=await acquire(store,node,record,source,guarded_write,domain,seconds=25)
                if result.get('resource_id'):return result
            except (DomainError,OSError,ValueError) as exc:failures.append(source_failure(exc,'public_source_unavailable'))
    result=None
    if broker:
        try:
            _,session=broker.manager.route_session(record.get('publisher_url'))
            state=session.status()
            saved=state.get('login_reported_at') or state.get('verified_pdf') or state.get('authentication_confirmed')
            # A subscription refusal belongs to one article, not the whole
            # logged-in account. The broker checks the denied DOI/URL itself.
            usable=state.get('task_ready') or state.get('reason')=='subscription_denied' and saved
            ready=usable and (state.get('online') or saved)
        except DomainError:ready=False
        if ready:
            paper={**{k:node.get(k) for k in ('doi','title','authors','year','venue')},'candidate_id':node['id'],'citation_record_id':record['id'],'sources':choices(node,record)}
            try:
                response=await broker.acquire({'job_id':job['id'],'paper':paper,'timeout_seconds':30,'publisher_only':True})
                if response.get('resource_id'):result=response
                else:failures.append(response.get('reason') or 'publisher_full_text_unavailable')
            except DomainError as exc:failures.append(exc.code)
    # The publisher account remains first even when a graph has an explicitly
    # located author copy. Hints supply URLs, never caller-authored identities.
    if not result and node.get('official_source_hint'):
        from .official_copy import verify,save
        try:
            source,proof=await verify(record,node['official_source_hint'])
            active()
            record=await guarded_write('official_copy_source',{'operation_id':uid('op')},lambda:save(store,record,source,proof,domain))
        except (DomainError,OSError,ValueError) as exc:failures.append(source_failure(exc,'official_source_unavailable'))
    if not result:result=await try_sources(choices(node,record))
    # This is exact-paper source resolution, even with no institution session.
    # A blocked publisher or index does not suppress other legal repositories.
    if not result:
        from .institutional_access import rss_pdf_url
        locators=([locate_proceedings] if rss_pdf_url(record.get('doi')) else [])+[locate_openalex,locate_public,locate_index]
        for locator in locators:
            active()
            try:
                updated,source=await locator(record)
                active()
                record=await guarded_write('graph_pdf_source',{'operation_id':uid('op')},lambda:bibliography.save(store,updated,domain))
                result=await try_sources([source,*choices(node,record)])
                if result:break
            except (DomainError,OSError,ValueError) as exc:failures.append(source_failure(exc,'public_locator_unavailable'))
    active()
    return {**(result or {'unavailable_reason':'; '.join(dict.fromkeys(failures)) or 'no_authorized_or_public_pdf'}),'metadata_status':record.get('metadata_status'),'duration_seconds':round(time.monotonic()-start,3)}


async def prepare(store,job,graph,write,broker=None):
    """Bounded concurrent reads/downloads; catalog writes use the single writer."""
    from .paper_graph import validate
    from .paper_abstract import add_local_abstract
    from .research_enrich import matching
    from .safety import atomic_json,contained
    if not str(job['context'].get('external_network','')).startswith('user_requested'):raise DomainError('scope_violation',409)
    validate(graph,job['context']['literature_search'])
    start=time.monotonic();gate=asyncio.Semaphore(4);rows=[]
    if broker:broker.graph_candidates[job['id']]=graph['nodes']
    async def one(node):
        async with gate:
            result=await acquire_node(store,job,node,write,broker)
            row={'candidate_id':node['id'],'title':node['title'],**result};rows.append(row)
            atomic_json(contained(store.project,job['context']['output_dir'])/'graph-fulltext-progress.json',{'rows':rows,'total':len(graph['nodes'])})
            cached=[{k:result[k] for k in ('resource_id','version_id','sha256')} ] if result.get('resource_id') else []
            enriched={**node,'cached_resources':cached,'full_text_status':'acquired' if cached else 'unavailable','full_text_reason':result.get('unavailable_reason')}
            record=matching(enriched,bibliography.rows(store),store,max_age=None)
            enriched=add_local_abstract(store,enriched,store.resources(),record)
            enriched['abstract_status']='available' if enriched.get('abstract') else 'unavailable'
            return enriched
    try:nodes=await asyncio.gather(*(one(node) for node in graph['nodes']))
    finally:
        if broker:broker.graph_candidates.pop(job['id'],None)
    return nodes,{'duration_seconds':round(time.monotonic()-start,3),'pdf_saved':sum(bool(r.get('resource_id')) for r in rows),'pdf_missing':sum(not r.get('resource_id') for r in rows),'abstracts':sum(bool(n.get('abstract')) for n in nodes),'total':len(nodes),'rows':rows}
