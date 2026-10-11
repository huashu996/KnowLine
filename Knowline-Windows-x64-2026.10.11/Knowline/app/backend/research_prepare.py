"""Reuse hash-checked results from an identical frozen research scope."""
import json,shutil,time,re
from pathlib import Path
from .safety import contained,digest,atomic_json,DomainError


def key(context):
    scope=context.get('literature_search',{})
    return (context.get('task'),scope.get('query'),scope.get('from_year'),scope.get('to_year'),scope.get('target_count'),scope.get('domain_id'),scope.get('network_policy'),json.dumps(scope.get('source_policy',{}),sort_keys=True),json.dumps(scope.get('search_plan',{}),sort_keys=True),scope.get('connected_papers_url'))


def retry_graph(store,job):
    """Resume this job's intact draft by its manifest path, including local names.

    This only avoids another discovery request; the executor and final ingest
    must still review evidence, current metadata and all artifact hashes.
    """
    if job['task']!='paper_relationships':return None
    output=contained(store.project,job['context']['output_dir'])
    for name in ('result.previous.json','result.json'):
        try:
            manifest_path=output/name
            if not manifest_path.is_file() or manifest_path.stat().st_size>32*1024*1024:continue
            manifest=json.loads(manifest_path.read_text('utf-8-sig'))
            if manifest.get('job_id')!=job['id']:continue
            path=manifest.get('paper_graph_artifact')
            artifact=next((a for a in manifest.get('artifacts',[]) if a.get('path')==path),None)
            if not artifact:continue
            file=contained(store.project,path)
            if not file.is_relative_to(output) or file.stat().st_size>2*1024*1024 or digest(file)!=artifact.get('sha256'):continue
            graph=json.loads(file.read_text('utf-8-sig'))
            from .paper_graph import validate
            validate(graph,job['context']['literature_search'])
            return {'path':path,'sha256':artifact['sha256'],'node_count':len(graph['nodes']),
                    'manifest_path':manifest_path.relative_to(store.project).as_posix(),
                    'requires_agent_review':True,'new_search_completed':False}
        except (OSError,ValueError,KeyError,TypeError,DomainError):continue
    return None


def related_memory(store,job,output):
    """Freeze bounded, accepted evidence for a different query; never auto-publish it."""
    query=job['context']['literature_search']['query'].casefold()
    tokens=set(re.findall(r'[a-z0-9]{3,}|[\u4e00-\u9fff]{2,}',query))
    tokens-={'the','for','and','with','from','paper','based','using'}
    papers={};sources=[];reroot=None
    for item in store.rows("SELECT id FROM jobs WHERE task='paper_relationships' AND status IN ('completed','partial') ORDER BY updated_at DESC LIMIT 24"):
        if item['id']==job['id']:continue
        try:
            previous=store.job(item['id']);result=previous.get('result') or {}
            path=result.get('paper_graph_artifact')
            artifact=next((a for a in result.get('artifacts',[]) if a['path']==path),None)
            if not artifact:continue
            file=contained(store.project,path)
            if file.stat().st_size>2*1024*1024 or digest(file)!=artifact['sha256']:continue
            graph=json.loads(file.read_text('utf-8-sig'))
            terms=previous['context'].get('literature_search',{}).get('query','').casefold()
            origin=next((n for n in graph['nodes'] if n['id']==graph['origin_id']),{})
            score=len(tokens.intersection(re.findall(r'[a-z0-9]{3,}|[\u4e00-\u9fff]{2,}',terms+' '+origin.get('title','').casefold())))
            if not score and not any(query==n.get('title','').casefold() or query==n.get('doi','').casefold() for n in graph['nodes']):continue
            sources.append({'job_id':previous['id'],'artifact':path,'sha256':artifact['sha256'],'topic_overlap':score})
            audit_artifact=next((a for a in result.get('artifacts',[]) if Path(a['path']).name=='citation-audit.json'),None)
            if not reroot and graph.get('network_policy')=='topical-multihop-real-citations-v2':
                exact=next((n for n in graph['nodes'] if query in {n.get('title','').casefold(),n.get('doi','').casefold(),'https://doi.org/'+n.get('doi','').casefold()}),None)
                if exact:
                    # Only accepted, source-backed citation neighbours are reused.
                    adjacent={n['id']:set() for n in graph['nodes']}
                    for e in graph['edges']:
                        if e.get('kind')=='citation':adjacent[e['source']].add(e['target']);adjacent[e['target']].add(e['source'])
                    distance={exact['id']:0};queue=[exact['id']]
                    for current in queue:
                        if distance[current]>=2:continue
                        for target in sorted(adjacent[current]):
                            if target not in distance:distance[target]=distance[current]+1;queue.append(target)
                    scope=job['context']['literature_search']
                    eligible=[n for n in graph['nodes'] if n['id']!=exact['id'] and n['id'] in distance and scope['from_year']<=n['year']<=scope['to_year']]
                    eligible.sort(key=lambda n:(distance[n['id']],-(n.get('citation_count') or 0),-n['year']))
                    if len(eligible)>=min(5,scope['target_count']):
                        selected=[exact,*eligible[:scope['target_count']]];ids={n['id'] for n in selected}
                        reroot={**graph,'origin_id':exact['id'],'nodes':selected,'edges':[e for e in graph['edges'] if e['source'] in ids and e['target'] in ids],
                            'reuse_basis':{'original_job_id':previous['id'],'original_artifact':path,'original_sha256':artifact['sha256'],'scope_unchanged':False,'relevance_basis':'Accepted same-field papers within two verified citation hops; current publication records must be refreshed.'}}
                        atomic_json(output/'paper-graph.json',reroot)
            for node in graph['nodes']:
                identity=('doi:'+node['doi'].lower()) if node.get('doi') else node['title'].casefold()+'|'+str(node['authors'])
                candidate={**node,'previous_job_id':previous['id'],'previous_node_id':node['id'],'original_graph_path':path,'original_graph_sha256':artifact['sha256'],
                    'reference_edges':[e for e in graph['edges'] if e['source']==node['id'] or e['target']==node['id']][:100],
                    'requires_current_publication_check':True,'requires_topic_review':True}
                if audit_artifact:candidate['citation_audit_artifact']={k:audit_artifact[k] for k in ('path','sha256')}
                if identity not in papers:papers[identity]=candidate
                if len(papers)>=100:break
            if len(papers)>=100:break
        except (OSError,ValueError,KeyError,DomainError):continue
    report={'schema_version':1,'query':job['context']['literature_search']['query'],'papers':list(papers.values()),'sources':sources,
        'scope':'this installation accepted graph evidence only','new_search_completed':False,
        'rule':'Review relevance and current formal metadata; old counts and source dates remain old.'}
    atomic_json(output/'field-research-memory.json',report)
    return {'related_paper_count':len(papers),'related_graph_count':len(sources),'memory_path':(output/'field-research-memory.json').relative_to(store.project).as_posix(),**({'cache':'field_warm','scope_unchanged':False,'source_job_id':reroot['reuse_basis']['original_job_id']} if reroot else {})}


def prepare(store,job):
    started=time.monotonic();context=job['context'];output=contained(store.project,context['output_dir'])
    info={'cache':'cold','reused_artifacts':[],'source_job_id':None,'scope_unchanged':True}
    if job['task'] not in {'discover_papers','paper_relationships'}:return info
    draft=retry_graph(store,job)
    if draft:
        info.update(cache='retry_draft',source_job_id=job['id'],retry_graph=draft,
                    reused_artifacts=[draft],duration_seconds=round(time.monotonic()-started,3))
        atomic_json(output/'research-preparation.json',info)
        return info
    candidates=[]
    for file in (store.state/'jobs').glob('*/context.json'):
        if file.parent.name==job['id']:continue
        try:
            previous=json.loads(file.read_text('utf-8-sig'))
            if key(previous)!=key(context):continue
            manifest_path=contained(store.project,previous['output_dir'])/'result.json'
            manifest=json.loads(manifest_path.read_text('utf-8-sig'))
            artifacts={Path(a['path']).name:a for a in manifest.get('artifacts',[]) if a.get('sha256')}
            name='papers.json' if job['task']=='discover_papers' else 'paper-graph.json'
            artifact=artifacts.get(name)
            if not artifact:continue
            source=contained(store.project,artifact['path'])
            if digest(source)!=artifact['sha256']:continue
            candidates.append((manifest_path.stat().st_mtime,previous,manifest,artifacts))
        except (OSError,ValueError,KeyError,DomainError):continue
    if candidates:
        _,previous,manifest,artifacts=max(candidates,key=lambda item:item[0])
        for name in ('papers.json','paper-graph.json','sources.json','source-responses.json','relationship-evidence-review.json'):
            artifact=artifacts.get(name)
            if not artifact:continue
            try:
                source=contained(store.project,artifact['path'])
                if digest(source)!=artifact['sha256']:continue
                value=json.loads(source.read_text('utf-8-sig'))
                # Change only task ownership; source retrieval timestamps stay intact.
                if isinstance(value,dict) and 'job_id' in value:value['job_id']=job['id']
                target=output/name;atomic_json(target,value)
                info['reused_artifacts'].append({'name':name,'original_path':artifact['path'],'original_sha256':artifact['sha256'],'prepared_sha256':digest(target)})
            except (OSError,ValueError,KeyError,DomainError):continue
        info.update(cache='warm',source_job_id=previous['job_id'],previous_import_results=manifest.get('imported_papers',[]))
        checked=[]
        for row in info['previous_import_results']:
            if not row.get('resource_id'):continue
            try:
                resource=store.resource(row['resource_id'])
                snapshot=store.snapshot(resource)
                checked.append({'candidate_id':row['candidate_id'],'resource_id':resource['id'],'version_id':resource['version_id'],'sha256':resource['sha256'],'ready':resource['state']=='ready' and digest(snapshot)==resource['sha256'],'title':resource['title']})
            except Exception:checked.append({'candidate_id':row.get('candidate_id'),'ready':False})
        info['current_full_texts']=checked
    if job['task']=='paper_relationships':info.update(related_memory(store,job,output))
    info['duration_seconds']=round(time.monotonic()-started,3)
    atomic_json(output/'research-preparation.json',info)
    return info
