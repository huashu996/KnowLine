"""Frozen graph selection to library/domain, without creating an import job."""
import asyncio
from .safety import DomainError,contained,digest
from .store import uid


async def run(store,job,body,write):
    from .paper_graph import load
    from .research_enrich import enrich
    from .graph_fulltext import acquire_node,verified_resources
    from . import paper_bibliography as bibliography
    store.check(job,body);graph=load(store,job)
    ids=body.get('candidate_ids')
    if not isinstance(ids,list) or not ids or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids) or not set(ids)<=set(n['id'] for n in graph['nodes']):raise DomainError('scope_violation',409)
    destination=body.get('destination','library')
    if destination not in {'library','domain'}:raise DomainError('invalid_request')
    domain=body.get('domain') if destination=='domain' else None
    if destination=='domain' and not any(g['id']==domain for g in store.groups()):raise DomainError('group_not_found',404)
    path=job['result']['paper_graph_artifact'];sha=next(a['sha256'] for a in job['result']['artifacts'] if a['path']==path)
    def active():
        current=store.job(job['id'])
        if current['revision']!=job['revision'] or current['status'] not in {'completed','partial'} or digest(contained(store.project,path))!=sha:raise DomainError('revision_conflict',409)
    async def guarded_write(kind,clean,action):
        def guarded():active();return action()
        return await write(kind,clean,guarded)
    nodes=[n for n in graph['nodes'] if n['id'] in ids]
    if 'fetch_missing' in body and not isinstance(body['fetch_missing'],bool):raise DomainError('invalid_request')
    fetch_missing=body.get('fetch_missing',True)
    hints=body.get('source_hints',{})
    if not isinstance(hints,dict) or not set(hints)<=set(ids) or (hints and not fetch_missing) or any(not isinstance(v,dict) or set(v)-{'page_url','pdf_url'} or not isinstance(v.get('pdf_url'),str) or len(v['pdf_url'])>2000 or v.get('page_url') is not None and (not isinstance(v['page_url'],str) or len(v['page_url'])>2000) for v in hints.values()):raise DomainError('scope_violation',409)
    if fetch_missing:
        if not str(job['context'].get('external_network','')).startswith('user_requested'):raise DomainError('scope_violation',409)
        missing=[n for n in nodes if not verified_resources(store,n,bibliography_record(store,n))]
        prepared,_=await enrich(store,missing,guarded_write,budget=None)
        replacements={n['id']:n for n in prepared};nodes=[replacements.get(n['id'],n) for n in nodes]
    nodes=[{**n,'official_source_hint':hints[n['id']]} if n['id'] in hints else n for n in nodes]
    rows=[];gate=asyncio.Semaphore(4)
    broker=None
    manager=getattr(store,'institutional',None)
    if fetch_missing and manager:
        from .institutional_broker import InstitutionalBroker
        broker=InstitutionalBroker(manager,guarded_write,graph_operation={'job_id':job['id'],'nodes':nodes,'active':active,'domain':domain})
    async def one(node):
        async with gate:
            active()
            if not fetch_missing and not verified_resources(store,node,bibliography_record(store,node)):
                result={'unavailable_reason':node.get('full_text_reason') or 'pdf_not_saved','full_text_checked':False}
            else:
                from .graph_fulltext import PAPER_ACQUISITION_TIMEOUT_SECONDS,describe
                try:
                    async with asyncio.timeout(PAPER_ACQUISITION_TIMEOUT_SECONDS):
                        result=await acquire_node(store,job,node,guarded_write,broker,domain,active_check=active)
                except TimeoutError:result={'unavailable_reason':'paper_acquisition_timeout'}
                result.update(describe(result))
            rows.append({'candidate_id':node['id'],'title':node['title'],**result})
    await asyncio.gather(*(one(node) for node in nodes))
    active()
    order={n['id']:i for i,n in enumerate(nodes)}
    rows.sort(key=lambda r:order[r['candidate_id']])
    return {'status':'partial' if any(not r.get('resource_id') for r in rows) else 'completed','imported':sum(bool(r.get('resource_id')) for r in rows),'missing':sum(not r.get('resource_id') for r in rows),'rows':rows,'fetched_missing':fetch_missing,'destination':destination,'domain_id':domain,'new_task_created':False}


def bibliography_record(store,node):
    from .research_enrich import matching
    from . import paper_bibliography as bibliography
    return matching(node,bibliography.rows(store),store,max_age=None)
