"""Shared current bibliography, abstracts and reusable full-text acquisition plans."""
import asyncio,copy,time,json
from . import paper_bibliography as bibliography
from .research_import import choices
from .safety import DomainError,digest,contained
from .store import uid


def matching(node,records,store=None,max_age=300):
    keys={('doi:'+str(node.get('doi','')).lower()),('arxiv:'+str(node.get('arxiv_id','')))}-{'doi:','arxiv:'}
    if str(node.get('doi','')).lower().startswith('10.48550/arxiv.'):keys.add('arxiv:'+str(node['doi'])[15:])
    for record in records:
        if record.get('alias_of') or not keys.intersection({record['identity_key'],*record.get('related_identifiers',[])}) or not record.get('latest_verified') or (max_age is not None and not bibliography.fresh(record.get('latest_checked_at'),max_age)):continue
        if store:
            try:
                evidence=contained(store.project,record['evidence_path'])
                if evidence.stat().st_size>2*1024*1024 or digest(evidence)!=record['evidence_sha256']:continue
            except (DomainError,OSError,KeyError):continue
        return record
    return None


def apply(node,record,formal=False):
    node=copy.deepcopy(node)
    if not record:return node
    node['citation_record_id']=record['id']
    node['publication_status']=record['publication_status']
    if formal:
        old_doi=node.get('doi')
        for key in ('title','authors','year','venue','doi'):node[key]=record.get(key)
        if old_doi and old_doi!=node.get('doi'):node['previous_doi']=old_doi
        node['metadata_source']={'url':record['source_url'],'retrieved_at':record['latest_checked_at'],'provider':'Verified publication record'}
    abstract=record.get('abstract')
    evidence=record
    if not abstract:
        evidence=next((v for v in record.get('evidence',[]) if v.get('abstract')),record)
        abstract=evidence.get('abstract')
    if abstract:
        node['abstract']=abstract
        node['abstract_source']={'url':evidence.get('source_url') or evidence.get('url'),'retrieved_at':evidence['latest_checked_at'],'provider':'Publication/repository abstract'}
    node['download_sources']=choices(node,record)
    if node.get('full_text_status')!='acquired':node['full_text_status']='sources_located' if node['download_sources'] else 'source_unavailable'
    if not node.get('cached_resources'):node['cached_resources']=[{'resource_id':r} for r in record.get('resource_ids',[])]
    return node


def display(store,graph):
    # Loading an immutable graph adds independently verified detail only; the
    # frozen node IDs, graph years and actual citation edges remain unchanged.
    records=bibliography.rows(store)
    resources=store.resources()
    from .paper_abstract import add_local_abstract
    from .graph_fulltext import verified_resources,describe,summary,source_coverage
    nodes=[]
    for node in graph['nodes']:
        record=matching(node,records,store,max_age=None)
        current=apply(node,matching(node,records,store))
        latest=(record or {}).get('pdf_status',{})
        if 'full_text_attempts' in latest:
            current.update({k:latest[k] for k in ('full_text_policy','full_text_attempts','full_text_sources','full_text_checked','full_text_coverage_complete','full_text_candidates','full_text_disposition','publisher_attempt') if k in latest})
            current['full_text_reason']=latest.get('unavailable_reason')
            if 'full_text_sources' not in latest:
                current['full_text_sources']=source_coverage(latest['full_text_attempts'])
                current['full_text_checked']=any(row['status'] not in {'not_checked','not_configured'}
                    for row in current['full_text_sources'] if row['provider'] not in {'出版商账户','Sci-Hub'})
        ready=verified_resources(store,node,record)
        current['cached_resources']=[{'resource_id':r['id'],'version_id':r['version_id'],'sha256':r['sha256']} for r in ready]
        if ready:current['full_text_status']='acquired';current.pop('full_text_reason',None)
        elif current.get('full_text_status')=='acquired':current['full_text_status']='unavailable';current['full_text_reason']='saved_pdf_missing_or_changed'
        if ready:current['full_text_candidates']=[]
        current.update(describe(current))
        from urllib.parse import urlencode
        query='"'+str(current['title']).replace('"',' ')+'"'
        current['google_scholar_verification']={'url':'https://scholar.google.com/scholar?'+urlencode({'q':query,'hl':'en'}),
            'provider':'Google Scholar','status':'not_checked','role':'supplementary_bibliography_check',
            'fields':['title','authors','year','doi'],'counts_separate':True}
        from .sci_hub import access as sci_hub_access
        current['sci_hub_access']=sci_hub_access(current.get('doi'))
        current['full_text_sources']=[
            {**row,'status':'not_checked','reason':'previous_run_not_checked','request_sent':False}
            if row.get('provider')=='Sci-Hub' and row.get('reason')=='source_not_integrated' else row
            for row in current.get('full_text_sources',source_coverage([]))]
        nodes.append(add_local_abstract(store,current,resources,record))
    return {**graph,'nodes':nodes,'full_text_summary':summary(nodes)}


async def enrich(store,nodes,write,domain=None,budget=45,formal=False,audit=None):
    start=time.monotonic();records=bibliography.rows(store);gate=asyncio.Semaphore(4)
    async def one(node):
        record=matching(node,records,store)
        # A located repository link needs its explicit publication bridge and
        # current version; it is never inferred from a similar title.
        repository=node.get('arxiv_id')
        if not repository:
            import re
            for plan in node.get('download_sources',[]):
                found=re.match(r'https://(?:export\.)?arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?$',str(plan.get('access_url') or plan.get('publisher_url','')))
                if found:repository=found[1];break
        if record and repository and 'arxiv:'+repository not in record.get('related_identifiers',[]):record=None
        # Counts, abstract and formal bibliography can share the same exact DOI
        # response. A fuzzy title result cannot establish a version bridge.
        if audit and not record and not repository:
            row=next((r for r in audit.get('rows',[]) if r.get('node_id')==node['id'] and r.get('match_basis')=='doi'),None)
            if row:
                for attempt in row.get('attempts',[]):
                    response=(attempt.get('retry') or {}).get('response') or attempt.get('response') or {}
                    work=response.get('message',{})
                    checked=(attempt.get('retry') or {}).get('retrieved_at') or attempt['retrieved_at']
                    if bibliography.fresh(checked,300) and work.get('type') in bibliography.FORMAL and work.get('DOI','').lower()==str(node.get('doi','')).lower():
                        candidate=bibliography.crossref(work,checked)
                        candidate['evidence']=[candidate.copy()]
                        record=await write('research_publication_record',{'operation_id':uid('op')},lambda:bibliography.save(store,candidate,domain))
                        break
        if not record:
            if not node.get('doi') and not repository:return {**node,'metadata_refresh_reason':'identifier_unavailable'}
            try:
                async with gate:
                    remaining=None if budget is None else budget-(time.monotonic()-start)
                    if remaining is not None and remaining<=0:raise asyncio.TimeoutError()
                    record=await asyncio.wait_for(bibliography.resolve(node.get('doi'),repository),25 if remaining is None else min(25,remaining))
                    original=str(node.get('doi','')).lower()
                    if original and not original.startswith('10.48550/arxiv.') and 'doi:'+original not in {record['identity_key'],*record.get('related_identifiers',[])}:raise DomainError('citation_identity_conflict')
                    record=await write('research_publication_record',{'operation_id':uid('op')},lambda:bibliography.save(store,record,domain))
            except asyncio.TimeoutError:return {**node,'metadata_refresh_reason':'bounded_source_timeout'}
            except (DomainError,ValueError,OSError) as exc:return {**node,'metadata_refresh_reason':getattr(exc,'code','source_unavailable')}
        return apply(node,record,formal)
    result=await asyncio.gather(*(one(node) for node in nodes))
    return result,{'duration_seconds':round(time.monotonic()-start,3),'verified':sum(bool(n.get('citation_record_id')) for n in result),'total':len(nodes),'new_model_execution':False}


def enrichment_artifacts(store,job,manifest,graph_path):
    """Check submitted hashes before updating only this service's generated files."""
    from .safety import DomainError,digest
    output=contained(store.project,job['context']['output_dir'])
    managed={graph_path,output/'graph-fulltext-progress.json',output/'publication-prefetch.json'}
    generated=[]
    for item in manifest.get('artifacts',[]):
        file=contained(store.project,item['path'])
        if not file.is_relative_to(output):raise DomainError('path_outside_scope')
        if not file.is_file() or file.stat().st_size>32*1024*1024 or digest(file)!=item.get('sha256'):
            raise DomainError('artifact_hash_mismatch')
        if file in managed:generated.append(item)
    return generated


async def artifact(store,job,write,budget=45,path=None,broker=None):
    """Enrich only this task's graph and recalculate its manifest hash."""
    from .safety import atomic_json
    from .research_policy import total_budget
    if total_budget(job) is None:budget=None
    output=contained(store.project,job['context']['output_dir']);path=path or output/'paper-graph.json'
    graph=json.loads(path.read_text('utf-8-sig'))
    from .paper_graph import validate
    validate(graph,job['context']['literature_search'])
    audit_path=output/'citation-audit.json'
    audit=json.loads(audit_path.read_text('utf-8-sig')) if audit_path.is_file() else None
    graph['nodes'],report=await enrich(store,graph['nodes'],write,job['context']['scope'].get('domain_id'),budget,formal=True,audit=audit)
    plan_path=output/'pdf-source-plan.json'
    if plan_path.is_file():
        try:
            if plan_path.stat().st_size>256000:raise DomainError('pdf_source_plan_invalid')
            plan=json.loads(plan_path.read_text('utf-8-sig'))
            if not isinstance(plan,dict) or plan.get('schema_version')!=1 or plan.get('job_id')!=job['id'] or not isinstance(plan.get('papers'),list):raise DomainError('pdf_source_plan_invalid')
            by_id={n['id']:n for n in graph['nodes']};seen=set();prepared_changes={}
            from .institutional_access import safe_url
            from .research_download import repository_arxiv_id
            for row in plan['papers']:
                if not isinstance(row,dict):raise DomainError('pdf_source_plan_invalid')
                key=row.get('node_id') or row.get('candidate_id')
                if key not in by_id or key in seen:raise DomainError('pdf_source_plan_invalid')
                seen.add(key);node=by_id[key]
                if str(row.get('doi') or '').casefold()!=str(node.get('doi') or '').casefold():raise DomainError('pdf_source_plan_identity_conflict')
                sources=row.get('sources',[])
                if not isinstance(sources,list) or len(sources)>3:raise DomainError('pdf_source_plan_invalid')
                hints=[];direct=[]
                for source in sources:
                    if not isinstance(source,dict):raise DomainError('pdf_source_plan_invalid')
                    url=safe_url(source.get('access_url') or source.get('url'))
                    if repository_arxiv_id(url):hints.append(url);continue
                    direct.append({k:source[k] for k in ('publisher_url','access_url','pdf_version','version_basis','version_source_url','fallback_reason') if k in source})
                    direct[-1].update(access_url=url,public_oa=True,download_permitted=True)
                prepared_changes[key]={'repository_source_hints':hints,'download_sources':[*direct,*node.get('download_sources',[])][:3]}
            for key,change in prepared_changes.items():by_id[key].update(change)
            report['pdf_source_plan']={'status':'bound_to_frozen_nodes','papers':len(seen),'actual_downloads_claimed':False}
        except (DomainError,ValueError,TypeError,KeyError) as exc:
            # A malformed PDF plan cannot cancel verified relationship work.
            report['pdf_source_plan']={'status':'ignored','reason':getattr(exc,'code','pdf_source_plan_invalid')}
    from .graph_fulltext import prepare
    graph['nodes'],fulltext=await prepare(store,job,graph,write,broker)
    # PDFs and publication bridges arrive after the relationship specialist.
    # Read their verified reference sections once before writing the managed graph.
    from .paper_graph import build_relationship_audit,verified_record_identifiers,verified_resource_identifiers,verified_pdf_references
    records=bibliography.rows(store)
    aliases=verified_record_identifiers(graph,records,store.project)+verified_resource_identifiers(graph,records,store.resources(),store.project)
    graph,relationship_report=build_relationship_audit(graph,audit,aliases,supplemental_records=verified_pdf_references(store,graph,records))
    report['relationship_completion']={'added_real_edges':relationship_report['added_real_edges'],
        'references_checked_nodes':relationship_report['references_checked_nodes'],'references_unchecked_node_ids':relationship_report['references_unchecked_node_ids']}
    report['full_text']=fulltext
    graph['full_text_summary']={k:v for k,v in fulltext.items() if k not in {'rows','duration_seconds'}}
    atomic_json(path,graph);atomic_json(output/'publication-prefetch.json',report)
    return report
