"""Layer configuration and evidence-backed cards assembled by the current Codex session."""
import hashlib
import json
import math
from .safety import DomainError, contained, digest
from . import pdf


def layers(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 12:
        raise DomainError('invalid_layers')
    result=[]
    for index, entry in enumerate(value):
        if not isinstance(entry, dict): raise DomainError('invalid_layers')
        name, focus = entry.get('name'), entry.get('focus')
        if not isinstance(name,str) or not name.strip() or len(name)>100 or not isinstance(focus,str) or not focus.strip() or len(focus)>2000:
            raise DomainError('invalid_layers')
        result.append({'id':'layer_'+str(index+1),'name':name.strip(),'focus':focus.strip()})
    return result


def get(store, key, default=None):
    row=store.one('SELECT value FROM settings WHERE key=?',(key,))
    return json.loads(row['value']) if row else default


def put(store,key,value):
    store.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps(value,ensure_ascii=False)))


def state(store,kb):
    config=get(store,'kb_structure:'+kb['id'],[])
    saved=get(store,'kb_cards:'+kb['id'],{})
    current=kb['index_state']=='ready' and saved.get('build_id')==kb['build_id'] and saved.get('member_revision')==kb['member_revision']
    if current:
        versions={r['id']:r['version_id'] for r in store.rows("SELECT id,version_id FROM resources WHERE state<>'deleted'")}
        for card in saved.get('cards',[]):
            if any(versions.get(e['resource_id'])!=e['version_id'] for e in card['evidence']):
                current=False;break
    latest=store.one("SELECT id,status,error FROM jobs WHERE json_extract(context,'$.scope.kb_id')=? AND task IN ('build_knowledge','update_knowledge') ORDER BY created_at DESC LIMIT 1",(kb['id'],))
    status='organized' if current else 'building_knowledge' if latest and latest['status'] in {'queued','running'} else 'knowledge_failed' if latest and latest['status'] in {'failed','interrupted','partial'} else 'awaiting_codex' if config else 'source_index'
    return {'layers':config,'knowledge_state':status,'knowledge_job':latest,
            'retrieval':saved.get('retrieval') if current else None,'card_count':len(saved.get('cards',[])) if current else 0}


def cards(store,kb):
    return get(store,'kb_cards:'+kb['id'],{}).get('cards',[]) if state(store,kb)['knowledge_state']=='organized' else []


def assemble(store,id,body):
    kb=store.kb(id);store.check(kb,body)
    if kb['index_state']!='ready':raise DomainError('kb_not_ready')
    job=store.job(body.get('job_id',''))
    if job['status']!='completed' or job['context']['scope'].get('kb_id')!=id or job['context']['scope'].get('kb_revision')!=kb['revision']:
        raise DomainError('scope_violation')
    values=job['result'].get('knowledge_cards')
    if not isinstance(values,list) or not 1<=len(values)<=5000:raise DomainError('invalid_knowledge_cards')
    layer_ids={layer['id'] for layer in kb['layers']}
    accepted=[];seen=set();render=[]
    for card in values:
        if not isinstance(card,dict) or not isinstance(card.get('id'),str) or not card['id'] or len(card['id'])>100 or card['id'] in seen:
            raise DomainError('invalid_knowledge_cards')
        if card.get('layer_id') not in layer_ids:raise DomainError('invalid_layers')
        if any(not isinstance(card.get(key),str) or not card[key].strip() or len(card[key])>limit for key,limit in [('title',200),('content',20000)]):
            raise DomainError('invalid_knowledge_cards')
        evidence=card.get('evidence')
        if not isinstance(evidence,list) or not evidence:raise DomainError('evidence_required')
        for e in evidence:
            if not isinstance(e,dict):raise DomainError('invalid_evidence')
            store.validate_evidence(e,job['context']['resources'])
            if e['resource_id'] not in kb['resource_ids'] or store.resource(e['resource_id'])['version_id']!=e['version_id']:
                raise DomainError('revision_conflict',409)
        result={key:card[key] for key in ['id','layer_id','title','content','evidence']}
        result['origin']='codex';result['status']='needs_review';seen.add(card['id'])
        for key in ['topic','claim_type','terms','aliases']:
            if key in card:result[key]=card[key]
        if 'figure' in card:
            figure=card['figure']
            if not isinstance(figure,dict) or not any(all(e.get(key)==figure.get(key) for key in ['resource_id','version_id','page_index']) for e in evidence):
                raise DomainError('scope_violation')
            r=store.resource(figure['resource_id'])
            if r['type']!='paper':raise DomainError('paper_required')
            rect=figure.get('rect')
            if not isinstance(rect,list) or len(rect)!=4 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in rect):
                raise DomainError('invalid_figure')
            with pdf.open_pdf(store.snapshot(r,figure['version_id'])) as doc:
                page=doc[figure['page_index']];bounds=page.rect
                if not (bounds.x0<=rect[0]<rect[2]<=bounds.x1 and bounds.y0<=rect[1]<rect[3]<=bounds.y1):raise DomainError('invalid_figure')
                # Clip is in displayed page coordinates (PyMuPDF page.rect), including rotation.
                pix=page.get_pixmap(matrix=__import__('pymupdf').Matrix(1.5,1.5),clip=__import__('pymupdf').Rect(rect),alpha=False)
                data=pix.tobytes('png')
            sha=hashlib.sha256(data).hexdigest();path=store.state/'figures'/id/(sha+'.png')
            result['figure']={**{key:figure[key] for key in ['resource_id','version_id','page_index','rect']},'path':path.relative_to(store.project).as_posix(),'sha256':sha}
            render.append((path,data))
        accepted.append(result)
    for source,card in zip(values,accepted):
        links=source.get('links',[])
        if not isinstance(links,list) or any(not isinstance(link,str) or link not in seen or link==card['id'] for link in links):
            raise DomainError('invalid_knowledge_cards')
        card['links']=list(dict.fromkeys(links))
    for relation in job['result'].get('knowledge_relations',[]):
        source=next((card for card in accepted if card['id']==relation.get('source_card_id')),None)
        target=next((card for card in accepted if card['id']==relation.get('target_card_id')),None)
        if not source or not target:raise DomainError('scope_violation')
        source['links']=list(dict.fromkeys(source['links']+[target['id']]))
        source.setdefault('relations',[]).append(relation)
    # All scope, version, text and geometry checks precede publication.
    for path,data in render:
        path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():path.write_bytes(data)
    retrieval=None
    if job['task'] in {'build_knowledge','update_knowledge'}:
        validate_result(store,job,job['result'])
        from .knowledge_retrieval import build
        retrieval=build(store,kb,accepted,job['result']['knowledge_build_report'])
    # Replace the visible raw directory/page hierarchy with actual user layers and knowledge.
    store.db.execute('DELETE FROM nodes WHERE kb_id=?',(id,))
    root=store.node(id,kb['build_id'],'root',None,'knowledge_base',kb['name'])
    for layer in kb['layers']:
        parent=store.node(id,kb['build_id'],'layer:'+layer['id'],root,'knowledge_layer',layer['name'])
        for card in accepted:
            if card['layer_id']==layer['id']:
                card['node_id']=store.node(id,kb['build_id'],'card:'+card['id'],parent,'figure' if card.get('figure') else 'knowledge_card',card['title'],card['evidence'])
    previous=get(store,'kb_cards:'+id,{})
    for card in previous.get('cards',[]):
        if card.get('node_id') not in {c['node_id'] for c in accepted}:store.db.execute('DELETE FROM nodes WHERE id=?',(card.get('node_id'),))
    previous=get(store,'kb_cards:'+id,{})
    if previous:put(store,'kb_cards_history:'+id+':'+previous.get('build_id','initial'),previous)
    put(store,'kb_cards:'+id,{'build_id':kb['build_id'],'member_revision':kb['member_revision'],'job_id':job['id'],'cards':accepted,'retrieval':retrieval})
    store.db.execute('UPDATE knowledge_bases SET revision=revision+1 WHERE id=?',(id,))
    store.event('knowledge_base',id,kb['revision']+1)
    return store.kb(id)


def prepare(store,job,job_dir):
    sources=[];cache_hits=0
    for r in job['context']['resources']:
        resource=store.resource(r['resource_id']);path=store.snapshot(resource,r['version_id'])
        if r['type']=='paper':
            cached=store.state/'knowledge-source-cache'/(r['sha256']+'.json')
            marker=cached.with_suffix('.sha256')
            if cached.is_file() and marker.is_file() and digest(cached)==marker.read_text('ascii').strip():
                items=json.loads(cached.read_text('utf-8'));cache_hits+=1
            else:
                with pdf.open_pdf(path) as doc:items=[{'page_index':p.number,'page_label':p.get_label(),'text':p.get_text()} for p in doc]
                from .safety import atomic_json
                atomic_json(cached,items);marker.write_text(digest(cached),encoding='ascii')
        elif r['type']=='code':
            items=[store.code_file(resource,name,r['version_id']) for name in r['allowed_files']]
        else:items=[{'description':path.read_text('utf-8-sig'),'source_kind':'link_descriptor_only'}]
        target=job_dir/(r['resource_id']+'-source.json')
        from .safety import atomic_json
        atomic_json(target,{'resource_id':r['resource_id'],'version_id':r['version_id'],'source_sha256':r['sha256'],'items':items})
        sources.append({'resource_id':r['resource_id'],'version_id':r['version_id'],'path':target.relative_to(store.project).as_posix(),'sha256':digest(target),'page_count':len(items) if r['type']=='paper' else None})
    return {'pipeline':'codex_layered_knowledge_v3','prepared_sources':sources,'source_cache_hits':cache_hits,'preprocessing_is_completion':False,'time_limit_seconds':None,'retrieval_contract':'knowledge_units_bm25_fastembed_rrf','artifact_contract':'single-authored-analysis-v3','reference_read_only':None}


def validate_result(store,job,result):
    values=result.get('knowledge_cards');report=result.get('knowledge_build_report')
    if not isinstance(values,list) or not values or not isinstance(report,dict):raise DomainError('invalid_knowledge_cards')
    ids={card.get('id') for card in values if isinstance(card,dict)}
    layers={layer['id'] for layer in job['context']['knowledge_layers']}
    coverage=report.get('layers',[])
    if len(coverage)!=len(layers) or {item.get('layer_id') for item in coverage}!=layers:raise DomainError('invalid_layers')
    for item in coverage:
        subset=[c for c in values if c['layer_id']==item['layer_id']]
        if item.get('status')=='covered':
            if not subset or set(item.get('card_ids',[]))!={c['id'] for c in subset}:raise DomainError('invalid_knowledge_cards')
        elif item.get('status')!='insufficient_source' or not str(item.get('reason','')).strip():raise DomainError('invalid_layers')
    for card in values:
        if card.get('layer_id') not in layers or card.get('claim_type') not in {'source_fact','synthesis','inference','research_idea'} or not isinstance(card.get('content'),str) or len(card['content'].strip())<160:raise DomainError('invalid_knowledge_cards')
        for key in ['terms','aliases']:
            if not isinstance(card.get(key,[]),list) or any(not isinstance(v,str) or len(v)>200 for v in card.get(key,[])):raise DomainError('invalid_knowledge_cards')
        if not card.get('evidence'):raise DomainError('evidence_required')
        for e in card['evidence']:store.validate_evidence(e,job['context']['resources'])
    covered=report.get('resources',[]);frozen={r['resource_id']:r for r in job['context']['resources']}
    if len(covered)!=len(frozen) or {r.get('resource_id') for r in covered}!=set(frozen):raise DomainError('scope_violation')
    prepared={r['resource_id']:r for r in job['context']['knowledge_build']['prepared_sources']}
    for r in covered:
        if r.get('version_id')!=frozen[r['resource_id']]['version_id']:raise DomainError('scope_violation')
        if frozen[r['resource_id']]['type']=='paper' and (not isinstance(r.get('analyzed_pages'),list) or any(isinstance(p,bool) or not isinstance(p,int) or not 0<=p<prepared[r['resource_id']]['page_count'] for p in r['analyzed_pages'])):raise DomainError('invalid_citation')
    cases=report.get('queries',[])
    if not isinstance(cases,list) or len(cases)<3:raise DomainError('knowledge_retrieval_eval_required')
    for case in cases:
        if not isinstance(case.get('query'),str) or not case['query'].strip() or not isinstance(case.get('expected_card_ids'),list) or not set(case['expected_card_ids'])<=ids:raise DomainError('knowledge_retrieval_eval_required')


def figure_path(store,kb_id,card_id):
    kb=store.kb(kb_id);card=next((c for c in cards(store,kb) if c['id']==card_id),None)
    if not card or not card.get('figure'):raise DomainError('figure_not_found',404)
    path=contained(store.project,card['figure']['path'])
    if not path.is_file() or digest(path)!=card['figure']['sha256']:raise DomainError('artifact_hash_mismatch')
    return path
