"""Acquire the selected graph papers before publication, with verified PDF reuse."""
import asyncio,time,re
from urllib.parse import urlsplit
from . import paper_bibliography as bibliography
from .institutional_access import validate_pdf
from .safety import DomainError,digest
from .store import uid


# These are per-paper limits, starting after a concurrency slot is acquired.
# There is deliberately no deadline for the complete graph.
PAPER_ACQUISITION_TIMEOUT_SECONDS = 180
ABSTRACT_TIMEOUT_SECONDS = 15


FULLTEXT_LABELS={
    'acquired':('PDF 已保存','PDF saved'),
    'candidate_needs_review':('全文身份或版本关联待核验','Full-text identity or version link needs review'),
    'search_incomplete':('来源查询未完成，可稍后重试','Source lookup incomplete; retry later'),
    'access_restricted':('出版商访问待处理，可继续查找公开副本','Publisher access needs attention; public copies may be available'),
    'not_found':('已检查来源暂未找到全文','No full text found in checked sources'),
    'not_checked':('尚未检查全文','Full text not checked'),
}


def acquisition_state(value):
    if value.get('resource_id') or value.get('cached_resources'):return 'acquired'
    if value.get('full_text_candidates'):return 'candidate_needs_review'
    reason=str(value.get('unavailable_reason') or value.get('full_text_reason') or value.get('reason') or '')
    if re.search(r'candidate_needs_review|identity_mismatch|identity_conflict|verification_required|unverified|ambiguous',reason):return 'candidate_needs_review'
    if re.search(r'index_unavailable|locator_unavailable|source_unavailable|search_unavailable|page_unavailable|timeout|budget|http_5|http_429|rate_limit|refresh|saved_pdf_missing|download_busy',reason):return 'search_incomplete'
    if re.search(r'requires_user|login|subscription|confirmation|redirect|http_40|not_connected',reason):return 'access_restricted'
    return 'not_found' if reason else 'not_checked'


def describe(value):
    state=acquisition_state(value);zh,en=FULLTEXT_LABELS[state]
    return {'full_text_status':state,'full_text_label':zh,'full_text_label_en':en}


def summary(nodes):
    states=[acquisition_state(n) for n in nodes]
    return {'pdf_saved':states.count('acquired'),'pdf_missing':len(nodes)-states.count('acquired'),
            'abstracts':sum(bool(n.get('abstract')) for n in nodes),'total':len(nodes),
            **{s:states.count(s) for s in FULLTEXT_LABELS if s!='acquired'}}


def source_failure(exc,fallback):
    code=getattr(exc,'code',None)
    # urllib HTTPError.code is numeric; DomainError.code is textual. Preserve
    # a bounded source failure instead of breaking the entire batch's report.
    if isinstance(code,int):return 'public_source_http_'+str(code)
    return code if isinstance(code,str) and code else fallback


def source_coverage(attempts):
    """Expose checked, failed and untouched sources without claiming exhaustion."""
    names=['出版商账户','正式 OA','作者／高校仓库','arXiv','GitHub','OpenAlex','Semantic Scholar','Sci-Hub']
    rows={name:{'provider':name,'status':'not_checked'} for name in names}
    rows['Sci-Hub'].update(request_sent=False)
    aliases={'Publisher session':'出版商账户','locate_publisher':'正式 OA','discover':'作者／高校仓库',
             'locate_author':'作者／高校仓库','locate_proceedings':'正式 OA','locate_public':'arXiv',
             'locate_github':'GitHub','locate_openalex':'OpenAlex','locate_index':'Semantic Scholar',
             'arXiv':'arXiv','GitHub':'GitHub','OpenAlex':'OpenAlex','Semantic Scholar':'Semantic Scholar',
             'Sci-Hub':'Sci-Hub','locate_sci_hub':'Sci-Hub'}
    for attempt in attempts:
        name=aliases.get(attempt.get('provider'))
        if not name and str(attempt.get('provider','')).startswith('arXiv'):name='arXiv'
        if not name and attempt.get('provider')=='PDF download':
            host=urlsplit(str(attempt.get('url') or '')).hostname or ''
            name='arXiv' if host in {'arxiv.org','export.arxiv.org'} else 'GitHub' if host in {'github.com','raw.githubusercontent.com'} else None
        if not name:continue
        reason=str(attempt.get('reason') or '')
        status=attempt.get('status')
        if status=='skipped' or reason in {'official_source_not_located','institution_site_required','publisher_not_authenticated_public_direct'}:status='not_configured'
        elif reason in {'public_repository_no_identity_match','github_no_verified_pdf','public_index_no_open_pdf','public_index_no_record','sci_hub_no_pdf','sci_hub_no_embedded_pdf'}:status='no_match'
        elif status in {'not_checked','cooldown'}:pass
        elif reason=='sci_hub_identifier_required':status='not_checked'
        elif attempt.get('http_status')==429 and attempt.get('request_sent') is False:status='cooldown'
        elif reason:status='unavailable'
        elif status not in {'requested','located','acquired'}:status='requested'
        # A later locator error cannot erase a successfully validated download.
        if rows[name]['status']=='acquired':continue
        rows[name].update({k:v for k,v in attempt.items() if k in {'reason','url','http_status','request_sent','retry_after_seconds'}})
        rows[name]['status']=status
    return list(rows.values())


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
    # When a preprint and the published PDF coexist, reuse the formal file.
    return sorted(found,key=lambda r:r['metadata'].get('pdf_version')!='published')


async def acquire_node(store,job,node,write,broker,domain=None,active_check=None):
    from .research_enrich import matching
    from .research_import import choices,publisher_source
    from .research_download import acquire,locate_proceedings,locate_openalex,locate_public,locate_index
    from .research_policy import fulltext_policy,authenticated_account,known_open_access,public_source
    start=time.monotonic();failures=[];attempted=set();attempts=[];candidates=[];publisher_attempt=None
    def failed(exc,provider,fallback='public_source_unavailable',url=None):
        code=source_failure(exc,fallback);failures.append(code)
        params=getattr(exc,'params',{})
        for entry in params.get('source_attempts',[])[:5]:
            if isinstance(entry,dict):attempts.append(entry)
        attempts.append({'provider':provider,'reason':code,**({'url':url} if url else {}),
                         **{k:params[k] for k in ('provider','http_status','source_status','request_sent','retry_after_seconds') if params.get(k) is not None}})
        for candidate in params.get('candidates',[])[:3]:
            if candidate not in candidates:candidates.append(candidate)
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
    async def reuse_saved(**details):
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
        return {'resource_id':resource['id'],'version_id':resource['version_id'],'sha256':resource['sha256'],'duplicate':True,'new_download':False,'new_registration':False,'full_text_checked':True,'pdf_version':resource['metadata'].get('pdf_version','unknown'),'metadata_status':record.get('metadata_status') if record else 'needs_review','duration_seconds':round(time.monotonic()-start,3),**details}
    if resources and (not broker or any(r['metadata'].get('pdf_version')=='published' for r in resources)
                      or not historical or historical.get('publication_status')!='published'):
        return await reuse_saved()
    if not record:
        # Queueing and acquisition can outlast the five-minute freshness window.
        # Refresh the exact identity here; expiry is not evidence of no full text.
        try:
            record=await asyncio.wait_for(bibliography.resolve(node.get('doi'),node.get('arxiv_id')),25)
            original=str(node.get('doi') or '').lower()
            if original and not original.startswith('10.48550/arxiv.') and 'doi:'+original not in {record['identity_key'],*record.get('related_identifiers',[])}:
                raise DomainError('citation_identity_conflict')
            active()
            record=await guarded_write('graph_pdf_publication_refresh',{'operation_id':uid('op')},lambda:bibliography.save(store,record,domain))
        except (DomainError,OSError,ValueError,asyncio.TimeoutError) as exc:
            if resources:
                return await reuse_saved(publisher_upgrade_pending=True,publisher_attempt={
                    'status':'unavailable','reason':source_failure(exc,'current_publication_refresh_timeout'),'request_sent':False})
            return {'unavailable_reason':source_failure(exc,'current_publication_refresh_timeout'),'full_text_disposition':'skipped_this_run','full_text_checked':False,'full_text_sources':source_coverage([]),'metadata_status':'needs_review','duration_seconds':round(time.monotonic()-start,3)}
    async def try_sources(sources):
        for source in sources:
            active()
            url=source.get('access_url') or source.get('publisher_url')
            if not public_source(source,record) or url in attempted:continue
            attempted.add(url)
            try:
                result=await acquire(store,node,record,source,guarded_write,domain,seconds=25)
                if result.get('resource_id'):
                    attempts.append({'provider':source.get('source_provider') or 'PDF download','status':'acquired','url':url,'request_sent':True})
                    return result
            except (DomainError,OSError,ValueError,asyncio.TimeoutError) as exc:failed(exc,source.get('source_provider') or 'PDF download',url=url)
    result=None
    # Resolve an unknown publisher route only when an authenticated account is
    # actually available. With no account, do not visit subscription publishers.
    has_account=False
    if broker and hasattr(broker.manager,'status'):
        account_status=broker.manager.status()
        has_account=any(authenticated_account(s) for s in [account_status,*account_status.get('sites',[])])
    if has_account and urlsplit(record.get('publisher_url','')).hostname=='doi.org':
        from .official_copy import resolve_publisher_url
        try:
            updated=await resolve_publisher_url(record)
            active()
            if updated['publisher_url']!=record['publisher_url']:
                record=await guarded_write('graph_pdf_publisher_route',{'operation_id':uid('op')},lambda:bibliography.save(store,updated,domain))
                attempts.append({'provider':'DOI publisher route','status':'located','url':record['publisher_url']})
        except (DomainError,OSError,ValueError,asyncio.TimeoutError) as exc:failed(exc,'DOI publisher route','publisher_route_unavailable')
    ready=False
    def skip_publisher(reason,site_id=None):
        nonlocal publisher_attempt
        publisher_attempt={'status':'skipped','reason':reason,'url':record['publisher_url'],
                           'request_sent':False,**({'site_id':site_id} if site_id else {})}
        attempts.append({'provider':'Publisher session',**publisher_attempt})
    if broker:
        try:
            site_id,session=broker.manager.route_session(record.get('publisher_url'))
            state=session.status()
            # A previously verified PDF can justify restoring this one saved
            # profile. A manual "I logged in" report cannot justify a transfer.
            if not authenticated_account(state) and state.get('state') not in {'expired','awaiting_login','unconfigured'} and state.get('verified_pdf') and hasattr(broker,'resume_account'):
                state=await broker.resume_account(session,job['id'])
            # A subscription refusal belongs to one article, not the whole
            # logged-in account. The broker checks the denied DOI/URL itself.
            ready=authenticated_account(state) and bool(state.get('task_ready') or state.get('reason')=='subscription_denied')
            if not ready:
                reason=state.get('reason') or 'publisher_not_authenticated_public_direct'
                skip_publisher(reason,site_id)
        except DomainError as exc:
            ready=False
            skip_publisher(exc.code)
        if ready:
            paper={**{k:node.get(k) for k in ('doi','title','authors','year','venue')},'candidate_id':node['id'],'citation_record_id':record['id'],'sources':[publisher_source(record)]}
            try:
                response=await broker.acquire({'job_id':job['id'],'paper':paper,'timeout_seconds':30,'publisher_only':True})
                publisher_attempt={k:response[k] for k in ('status','reason','site_id','blocked_sources') if k in response}
                publisher_attempt['url']=record['publisher_url']
                if response.get('resource_id'):publisher_attempt['request_sent']=True
                elif 'request_sent' in response:publisher_attempt['request_sent']=response['request_sent']
                if response.get('resource_id'):result=response
                else:failed(DomainError(response.get('reason') or 'publisher_full_text_unavailable'),'Publisher session',url=record['publisher_url'])
            except DomainError as exc:
                publisher_attempt={'status':'unavailable','reason':exc.code,'url':record['publisher_url']}
                failed(exc,'Publisher session')
    else:skip_publisher('publisher_not_authenticated_public_direct')
    # A saved repository copy remains available if the original publisher
    # cannot be acquired. Do not download that same fallback a second time.
    if not result and resources:
        result=await reuse_saved(publisher_upgrade_pending=ready)
    # The publisher account remains first even when a graph has an explicitly
    # located author copy. Hints supply URLs, never caller-authored identities.
    if not result and node.get('official_source_hint'):
        from .official_copy import verify,save
        try:
            source,proof=await verify(record,node['official_source_hint'])
            active()
            record=await guarded_write('official_copy_source',{'operation_id':uid('op')},lambda:save(store,record,source,proof,domain))
        except (DomainError,OSError,ValueError) as exc:failed(exc,'Official source hint','official_source_unavailable')
    if not result:result=await try_sources(choices(node,record))
    # The PDF specialist can locate a concrete repository ID independently of
    # title search/index health. It still needs the same original identity gate.
    if not result:
        from .research_download import repository_arxiv_id
        ids=list(dict.fromkeys(filter(None,(repository_arxiv_id(url) for url in node.get('repository_source_hints',[])[:3]))))
        for identifier in ids:
            try:
                updated,source=await locate_public(record,identifier=identifier)
                attempts.extend(entry for entry in updated.get('public_location_attempts',[])[-5:] if entry not in attempts)
                attempts.append({'provider':'locate_public','status':'located','url':source['version_source_url']})
                from .official_copy import persist_sources
                record=await guarded_write('graph_pdf_source',{'operation_id':uid('op')},lambda:persist_sources(store,updated,domain))
                result=await try_sources([source])
                if result:break
            except (DomainError,OSError,ValueError,asyncio.TimeoutError) as exc:failed(exc,'locate_public','public_locator_unavailable')
    # This is exact-paper source resolution, even with no institution session.
    # A blocked publisher or index does not suppress other legal repositories.
    if not result:
        from .institutional_access import rss_pdf_url
        from .official_copy import discover as locate_author,locate_github,locate_publisher,persist_sources
        from .sci_hub import locate as locate_sci_hub
        locators=([locate_proceedings] if rss_pdf_url(record.get('doi')) else [])+([locate_publisher] if known_open_access(record) else [])+[locate_author,locate_public,locate_github,locate_openalex,locate_index,locate_sci_hub]
        for locator in locators:
            active()
            try:
                updated,source=await locator(record)
                attempts.extend(entry for entry in updated.get('public_location_attempts',[])[-5:]
                                if isinstance(entry,dict) and entry not in attempts)
                attempts.append({'provider':source.get('source_provider') or locator.__name__,'status':'located',
                                 'url':source.get('version_source_url') or source.get('publisher_url')})
                active()
                record=await guarded_write('graph_pdf_source',{'operation_id':uid('op')},lambda:persist_sources(store,updated,domain))
                result=await try_sources([source,*choices(node,record)])
                if result:break
            except (DomainError,OSError,ValueError,asyncio.TimeoutError) as exc:failed(exc,locator.__name__,'public_locator_unavailable')
    active()
    details={**(result or {'unavailable_reason':'; '.join(dict.fromkeys(failures)) or 'no_authorized_or_public_pdf'}),
             'full_text_policy':fulltext_policy(),
             'full_text_attempts':attempts[-12:],'full_text_candidates':candidates[:5],
             'publisher_attempt':publisher_attempt,'metadata_status':record.get('metadata_status'),
             'duration_seconds':round(time.monotonic()-start,3)}
    details.update(describe(details))
    details['full_text_disposition']='saved' if details.get('resource_id') else 'skipped_this_run'
    details['full_text_sources']=source_coverage(attempts)
    public=[r for r in details['full_text_sources'] if r['provider'] in {'arXiv','GitHub','OpenAlex','Semantic Scholar','正式 OA','作者／高校仓库','Sci-Hub'}]
    details['full_text_checked']=bool(details.get('resource_id') or any(r['status'] not in {'not_checked','not_configured'} for r in public))
    # A failed or untouched independent source still leaves coverage partial;
    # checking only arXiv/GitHub does not exhaust public full-text discovery.
    details['full_text_coverage_complete']=bool(details.get('resource_id') or all(r['status'] in {'no_match','located','acquired'} for r in public))
    await guarded_write('graph_pdf_outcome',{'operation_id':uid('op')},lambda:bibliography.outcome(store,record['id'],details['full_text_status'],
        **{k:v for k,v in details.items() if k in {'unavailable_reason','full_text_policy','full_text_attempts','full_text_sources','full_text_checked','full_text_coverage_complete','full_text_candidates','full_text_disposition','publisher_attempt','resource_id'}}))
    return details


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
            paper_started=time.monotonic()
            timed_out=False
            try:
                async with asyncio.timeout(PAPER_ACQUISITION_TIMEOUT_SECONDS):
                    result=await acquire_node(store,job,node,write,broker)
            except TimeoutError:
                # A slow/unavailable paper must not cancel its peers or discard
                # their verified files. User cancellation still propagates.
                timed_out=True
                result={'unavailable_reason':'paper_acquisition_timeout','full_text_disposition':'skipped_this_run'}
            cached=[{k:result[k] for k in ('resource_id','version_id','sha256')} ] if result.get('resource_id') else []
            enriched={**node,'cached_resources':cached,**describe(result),'full_text_reason':result.get('unavailable_reason'),
                      **{k:result[k] for k in ('full_text_attempts','full_text_sources','full_text_checked','full_text_coverage_complete','full_text_candidates','full_text_disposition','publisher_attempt') if k in result}}
            if not timed_out:
                try:
                    async with asyncio.timeout(ABSTRACT_TIMEOUT_SECONDS):
                        record=matching(enriched,bibliography.rows(store),store,max_age=None)
                        # PDF parsing is read-only and must not block the event
                        # loop, heartbeats, or other papers' timeout checks.
                        enriched=await asyncio.to_thread(add_local_abstract,store,enriched,store.resources(),record)
                except TimeoutError:
                    result['abstract_unavailable_reason']='paper_abstract_timeout'
            elif not enriched.get('abstract'):
                result['abstract_unavailable_reason']='paper_acquisition_timeout'
            enriched['abstract_status']='available' if enriched.get('abstract') else 'unavailable'
            if enriched['abstract_status']=='unavailable':
                enriched['abstract_unavailable_reason']=result.get('abstract_unavailable_reason','abstract_not_found')
            else:
                enriched.pop('abstract_unavailable_reason',None)
            row={'candidate_id':node['id'],'title':node['title'],**result,'duration_seconds':round(time.monotonic()-paper_started,3),'abstract_status':enriched['abstract_status']};rows.append(row)
            atomic_json(contained(store.project,job['context']['output_dir'])/'graph-fulltext-progress.json',{'rows':rows,'total':len(graph['nodes'])})
            return enriched
    tasks=[asyncio.create_task(one(node)) for node in graph['nodes']]
    try:nodes=await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        if broker:broker.graph_candidates.pop(job['id'],None)
    return nodes,{'duration_seconds':round(time.monotonic()-start,3),**summary(nodes),'rows':rows}
