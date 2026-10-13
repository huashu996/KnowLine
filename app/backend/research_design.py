"""Bounded evidence search within a proposal's frozen resources and KB snapshots."""
import copy
import json
import time
from .safety import contained,digest,atomic_json,DomainError
from .research_contracts import proposal_policy,require

def previous_failures(store,job,frozen=None):
    idea=job['context']['proposal'].get('idea_id')
    if not idea:return []
    from .proposal_evidence import FrozenKnowledge
    frozen=frozen or FrozenKnowledge(store,job);found=[];seen=set()
    for row in store.rows("SELECT id FROM jobs WHERE task IN ('proposal_word','proposal_ppt') AND status IN ('completed','partial') AND json_extract(context,'$.proposal.idea_id')=? ORDER BY created_at DESC LIMIT 20",(idea,)):
        if row['id']==job['id']:continue
        prior=store.job(row['id'])
        for failure in (prior.get('result') or {}).get('research_design',{}).get('failure_records',[]):
            if failure['signature'] in seen:continue
            evidence=failure.get('evidence',[])
            if not evidence:continue
            try:
                evidence=[frozen.rebind(e) for e in evidence]
            except DomainError:continue
            found.append({**failure,'evidence':evidence,'source_job_id':row['id'],'role':'previous_observed_failure_requires_review'});seen.add(failure['signature'])
            if len(found)>=20:return found
    return found

def search(store,job_id,body,*,saved_result_audit=False):
    job=store.job(job_id);store.check(job,body)
    require(job['task'] in {'proposal_word','proposal_ppt'} and (job['status']=='running' or saved_result_audit and job['status'] in {'failed','partial','interrupted','completed'}),'proposal_search_task_scope')
    policy=proposal_policy();queries=body.get('queries')
    require(isinstance(queries,list) and 1<=len(queries)<=4,'one_to_four_queries_required')
    key='research_search:'+job_id;row=store.one('SELECT value FROM settings WHERE key=?',(key,))
    trace=json.loads(row['value']) if row else {'job_id':job_id,'queries':[],'rounds':0}
    require(trace['rounds']<policy['max_search_rounds'] and len(trace['queries'])+len(queries)<=policy['max_queries'],'research_search_budget_exhausted')
    seen={(q['lane'],q['query']) for q in trace['queries']}
    for q in queries:
        require(isinstance(q,dict) and q.get('lane') in policy['search_lanes'] and isinstance(q.get('query'),str) and 1<=len(q['query'].strip())<=500,'invalid_research_query')
        require((q['lane'],q['query']) not in seen,'duplicate_research_query');seen.add((q['lane'],q['query']))
        if trace['rounds']:require(isinstance(q.get('gap'),str) and q['gap'].strip(),'followup_requires_evidence_gap')
    start=time.perf_counter();output=contained(store.project,job['context']['output_dir']);manifest=output/'research-index.json'
    from .knowledge_retrieval import build,query_batch
    from .proposal_evidence import FrozenKnowledge,VERSION
    frozen_knowledge=FrozenKnowledge(store,job)
    resources={(r['resource_id'],r['version_id']) for r in job['context']['resources']}
    frozen_bases=[]
    for kb in job['context']['proposal']['knowledge_bases']:
        path=contained(store.project,kb['snapshot_path'])
        if digest(path)!=kb['sha256']:raise DomainError('snapshot_corrupt')
        frozen_bases.append((kb,json.loads(path.read_text('utf-8-sig'))))
    # The durable single-writer record is authoritative; task files are editable.
    if not resources:
        info=None
    elif trace.get('index'):
        info=trace['index'];require(info.get('source_versions')==[{k:r[k] for k in ('resource_id','version_id','sha256')} for r in job['context']['resources']],'research_index_scope')
    else:
        cards=[];layers=[];resources={(r['resource_id'],r['version_id']) for r in job['context']['resources']}
        for kb,frozen in frozen_bases:
            prefix=kb['id']+':'
            for source in frozen.get('cards',[]):
                if not source.get('evidence') or not all((e.get('resource_id'),e.get('version_id')) in resources for e in source['evidence']):continue
                card=copy.deepcopy(source);card['id']=prefix+card['id'];card['links']=[prefix+i for i in card.get('links',[])]
                card['claim_type']=card.get('claim_type','inference');cards.append(card)
            layers+=frozen.get('layers',[])
        info=build(store,{'id':'proposal:'+job_id,'build_id':job_id,'layers':layers},cards,{'queries':[]},job['context']['resources'],output/'research-index')
        atomic_json(manifest,info)
        trace['index']=info
    answers=query_batch(store,info,[q['query'] for q in queries],top_k=policy['top_k_per_query']) if info else [None]*len(queries)
    knowledge_answers,knowledge_index=frozen_knowledge.search([q['query'] for q in queries],output,trace.get('knowledge_index'),policy['top_k_per_query'])
    trace.update(knowledge_index=knowledge_index,evidence_version=VERSION)
    result=[]
    for q,answer,kanswer in zip(queries,answers,knowledge_answers):
        if answer is None:answer=kanswer
        elif kanswer['hits']:
            # Two independently ranked roles, no dependence on raw-resource IDs.
            merged=[];seen_hits=set()
            for pair in zip(answer['hits']+[None]*len(kanswer['hits']),kanswer['hits']+[None]*len(answer['hits'])):
                for hit in pair:
                    if hit and hit['id'] not in seen_hits:merged.append(hit);seen_hits.add(hit['id'])
            answer={**answer,'hits':merged[:policy['top_k_per_query']],'provider':'original_hybrid_and_frozen_knowledge',
                    'elapsed_ms':answer['elapsed_ms']+kanswer['elapsed_ms'],'knowledge_reranker':kanswer['reranker'],
                    'warnings':answer.get('warnings',[])+kanswer['warnings']}
        for h in answer['hits']:
            for e in h.get('evidence',[]):frozen_knowledge.validate_any(e)
        identities={frozen_knowledge.validate_any(e) for h in answer['hits'] for e in h.get('evidence',[])}
        answer.update(independent_source_count=len(identities),ranked_hit_count=len(answer['hits']))
        if answer['hits'] and answer.get('answerability')=='no_matching_evidence':answer['answerability']='knowledge_sources_available'
        result.append({**q,**answer})
        trace['queries'].append({**q,'hit_ids':[h['id'] for h in answer['hits']],'source_ids':sorted(identities),
                                 'elapsed_ms':answer['elapsed_ms'],'reranker':answer['reranker']})
    trace['rounds']+=1;trace['source_scope']='frozen_selected_sources';trace['total_elapsed_ms']=trace.get('total_elapsed_ms',0)+round((time.perf_counter()-start)*1000,3)
    store.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps(trace,ensure_ascii=False)))
    atomic_json(output/'research-search-log.json',trace)
    return {'job_id':job_id,'results':result,'previous_failures':previous_failures(store,job,frozen_knowledge),'remaining_queries':policy['max_queries']-len(trace['queries']),
            'remaining_rounds':policy['max_search_rounds']-trace['rounds'],'novelty_scope':'selected_sources',
            'stop_rule':'Stop when candidate evidence is sufficient; only named gaps permit follow-up search.'}


def audit_saved(store,id,body):
    """Revalidate a completed generation after a validator fix; no LLM rerun."""
    job=store.job(id);store.check(job,body)
    require(job['task'] in {'proposal_word','proposal_ppt'} and job['status'] in {'failed','partial','interrupted','completed'},'proposal_audit_task_scope')
    output=contained(store.project,job['context']['output_dir']);path=contained(output,'result.json')
    require(path.stat().st_size<=2*1024*1024,'proposal_manifest_too_large')
    result=json.loads(path.read_text('utf-8-sig'))
    require(result.get('job_id')==id and result.get('schema_version')==2,'proposal_manifest_identity')
    for artifact in result.get('artifacts',[]):
        target=contained(store.project,artifact['path']);contained(output,target)
        require(digest(target)==artifact['sha256'],'proposal_artifact_changed')
    from .proposal_evidence import VERSION
    key='research_search:'+id;row=store.one('SELECT value FROM settings WHERE key=?',(key,))
    trace=json.loads(row['value']) if row else {}
    if trace.get('evidence_version')!=VERSION:
        queries=[{k:q[k] for k in ('lane','query','gap') if k in q} for q in trace.get('queries',[])]
        require(bool(queries),'proposal_saved_search_required')
        store.db.execute('DELETE FROM settings WHERE key=?',(key,))
        for start in range(0,len(queries),4):search(store,id,{'base_revision':job['revision'],'queries':queries[start:start+4]},saved_result_audit=True)
    current=store.one('SELECT value FROM settings WHERE key=?',(key,))
    refreshed=json.loads(current['value']) if current else {}
    counts=[len(q.get('hit_ids',[])) for q in refreshed.get('queries',[])]
    result['completion_audit']={'basis':'saved_artifacts_and_frozen_knowledge','previous_status':job['status'],'generation_reused':True,
                              'search_hit_counts':counts,'original_artifacts_unchanged':True}
    note='已在知识库独立引用修复后重新检索并核验来源；原文档保留生成时的检索说明和待验证事项。'
    if note not in result.setdefault('warnings',[]):result['warnings'].append(note)
    return store.ingest_job(id,{**body,'manifest':result})
