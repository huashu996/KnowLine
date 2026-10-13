"""Evidence-preserving knowledge-unit BM25 + learned vectors + explicit link fusion."""
import atexit,hashlib,json,math,os,re,sqlite3,subprocess,threading,unicodedata,uuid,sys,time
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .safety import DomainError,atomic_json,digest,contained
from .layout import app_dir


class Encoder:
    def __init__(self,app):self.app=app;self.process=None;self.lock=threading.Lock();self.reader=ThreadPoolExecutor(max_workers=1)
    def encode(self,texts,kind='document'):
        return self.request({'texts':texts,'kind':kind})
    def rerank(self,question,texts):
        return self.request({'op':'rerank','query':question,'texts':texts})
    def request(self,payload):
        with self.lock:
            if not self.process or self.process.poll() is not None:
                command=None
                if getattr(sys,'frozen',False):command=[sys.executable,'--semantic-worker','--project',str(self.app.parent)]
                python=self.app/'.semantic-runtime/python.exe'
                if not python.is_file():python=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
                if command is None:
                    if not python.is_file():raise DomainError('semantic_runtime_missing')
                    command=[str(python),'-X','utf8',str(self.app/'scripts/semantic_worker.py')]
                self.process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.process.stdin.write(json.dumps(payload,ensure_ascii=True)+'\n');self.process.stdin.flush()
            try:answer=json.loads(self.reader.submit(self.process.stdout.readline).result(timeout=120))
            except Exception as exc:self.close();raise DomainError('semantic_runtime_failed') from exc
            if 'error' in answer:raise DomainError('semantic_runtime_failed')
            if payload.get('op')!='rerank' and (not answer.get('learned_model') or len(answer.get('vectors',[]))!=len(payload['texts'])):raise DomainError('semantic_runtime_failed')
            return answer
    def close(self):
        if self.process and self.process.poll() is None:self.process.terminate();self.process.wait(timeout=10)


encoders={};encoder_lock=threading.Lock()
def encoder(store):
    path=app_dir(store.project)
    if not (path/'scripts/semantic_worker.py').is_file():path=Path(__file__).resolve().parents[1]
    with encoder_lock:
        if path not in encoders:encoders[path]=Encoder(path)
        return encoders[path]
@atexit.register
def close_encoders():
    for value in encoders.values():value.close()


def normalized(text):return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',text)).strip()
def cosine(a,b):return sum(x*y for x,y in zip(a,b))/(math.sqrt(sum(x*x for x in a))*math.sqrt(sum(y*y for y in b)) or 1)

def semantic_sections(content):
    """Keep every character, but bound Chinese tokens before the 512-token model."""
    parts=[]
    for section in re.split(r'(?m)(?=^## )',content):
        text=section.strip()
        if not text:continue
        for offset in range(0,len(text),320):parts.append(text[offset:offset+360])
    return parts


def legacy_build(store,kb,cards,report):
    from .store import tokenize
    started=time.perf_counter()
    model=encoder(store);identity=model.encode(['知识索引模型身份'])['model_id']
    processing='knowledge-unit-360-context-501-v1'
    fingerprint=hashlib.sha256(json.dumps({'model':identity,'processing':processing,'layers':kb['layers'],'cards':[{k:c.get(k) for k in ['id','layer_id','title','content','evidence','links','aliases','terms','topic']} for c in cards]},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    from .knowledge import get
    previous=(get(store,'kb_cards:'+kb['id'],{}).get('retrieval') or {})
    if previous.get('input_fingerprint')==fingerprint:
        target=contained(store.project,previous['path'])
        if digest(target)!=previous['sha256']:raise DomainError('snapshot_corrupt')
        info={**previous,'vectors_computed':0,'vectors_reused':previous['units'],'index_reused':True}
        info['evaluation']=evaluate(store,info,report)
        info['evaluation_batch_size']=len(report.get('queries',[]))
        info['build_duration_ms']=round((time.perf_counter()-started)*1000,3)
        return info
    folder=store.state/'knowledge-index'/kb['id'];folder.mkdir(parents=True,exist_ok=True)
    target=folder/(kb['build_id']+'-'+uuid.uuid4().hex[:8]+'.sqlite');db=sqlite3.connect(target)
    db.executescript('CREATE TABLE units(id TEXT PRIMARY KEY,card_id TEXT,layer_id TEXT,title TEXT,content TEXT,evidence TEXT,links TEXT,aliases TEXT,vector TEXT,content_sha256 TEXT);CREATE VIRTUAL TABLE lexical USING fts5(unit_id UNINDEXED,tokens);')
    cache=sqlite3.connect(store.state/'knowledge-vector-cache.sqlite');cache.execute('CREATE TABLE IF NOT EXISTS vectors(model TEXT,hash TEXT,vector TEXT,PRIMARY KEY(model,hash))')
    units=[];seen=set();reused=0;computed=0
    for card in cards:
        layer=next(l for l in kb['layers'] if l['id']==card['layer_id'])
        groups=semantic_sections(card['content'])
        for i,content in enumerate(groups):
            aliases=card.get('aliases',[]);terms=card.get('terms',[])
            # Only source-authored aliases enter the prefix; never evaluation questions.
            prefix=' / '.join([layer['name'],card.get('topic',''),card['title'],' '.join(aliases+terms)])
            context=prefix[:140]+'\n'+content
            text=normalized(context);sha=hashlib.sha256(text.encode()).hexdigest()
            if sha in seen:continue
            seen.add(sha);prior=cache.execute('SELECT vector FROM vectors WHERE model=? AND hash=?',(identity,sha)).fetchone()
            units.append({'id':card['id']+':'+str(i),'card_id':card['id'],'layer_id':card['layer_id'],'title':card['title'],'content':content,'evidence':card['evidence'],'links':card.get('links',[]),'aliases':aliases,'terms':terms,'context':context,'hash':sha,'vector':json.loads(prior[0]) if prior else None})
            reused+=bool(prior)
    missing=[u for u in units if u['vector'] is None]
    for offset in range(0,len(missing),64):
        batch=missing[offset:offset+64];answer=model.encode([u['context'] for u in batch])
        for unit,vector in zip(batch,answer['vectors']):
            unit['vector']=vector;cache.execute('INSERT OR REPLACE INTO vectors VALUES(?,?,?)',(identity,unit['hash'],json.dumps(vector)));computed+=1
        from .retention import bound_vectors
        bound_vectors(cache,store)
    for u in units:
        db.execute('INSERT INTO units VALUES(?,?,?,?,?,?,?,?,?,?)',(u['id'],u['card_id'],u['layer_id'],u['title'],u['content'],json.dumps(u['evidence'],ensure_ascii=False),json.dumps(u['links']),json.dumps(u['aliases'],ensure_ascii=False),json.dumps(u['vector']),u['hash']))
        db.execute('INSERT INTO lexical VALUES(?,?)',(u['id'],tokenize(u['context']+' '+' '.join(u['terms']+u['aliases']))))
    db.commit();cache.commit();db.close();cache.close()
    info={'path':target.relative_to(store.project).as_posix(),'sha256':digest(target),'model_id':identity,'learned_model':True,'dimensions':512,'lexical':'sqlite_fts5_bm25','fusion':'RRF','relation_expansion':'one-hop explicit card links','units':len(units),'vectors_computed':computed,'vectors_reused':int(reused),'source_scope':'validated_codex_knowledge_units','query_requires_source_pdf':False}
    info.update(input_fingerprint=fingerprint,processing_version=processing,index_reused=False,build_duration_ms=round((time.perf_counter()-started)*1000,3))
    try:results=evaluate(store,info,report)
    except DomainError as exc:
        atomic_json(target.with_suffix('.manifest.json'),{**info,'evaluation_failed':True,'error':exc.code})
        raise
    info['evaluation']=results
    info['semantic_chunk_char_limit']=360;info['semantic_context_char_limit']=501
    info['evaluation_batch_size']=len(report.get('queries',[]))
    atomic_json(target.with_suffix('.manifest.json'),info)
    return info


def legacy_evaluate(store,info,report):
    results=[]
    cases=report.get('queries',[])
    answers=query_batch(store,info,[case['query'] for case in cases])
    for case,answer in zip(cases,answers):
        hits=answer['hits'];found={h['card_id'] for h in hits[:10]};expected=set(case['expected_card_ids'])
        results.append({'query':case['query'],'expected':sorted(expected),'found':sorted(found),'expected_hit':bool(found&expected) if expected else None,'assessment':'not_observed' if not expected else 'retrieved' if found&expected else 'missed'})
    # Retrieval evidence is checked; this does not prove semantic factual correctness.
    if any(r['expected_hit'] is False for r in results):raise DomainError('knowledge_retrieval_eval_failed')
    return results


def query_index(store,info,question):
    return query_batch(store,info,[question])[0]

def legacy_query_batch(store,info,questions):
    if not questions:return []
    from .store import tokenize
    path=contained(store.project,info['path'])
    if digest(path)!=info['sha256']:raise DomainError('snapshot_corrupt')
    with closing(sqlite3.connect(f'file:{path.as_posix()}?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row;units=[dict(r) for r in db.execute('SELECT * FROM units')]
        lexical_rankings=[]
        for question in questions:
            expansions=[];normalized_question=question.casefold()
            for u in units:
                family=json.loads(u['aliases'])
                # Broad tokens such as IMU cannot expand an entire unrelated alias family.
                if any(len(a.strip())>=5 and a.casefold() in normalized_question for a in family):expansions.extend(family)
            terms=list(dict.fromkeys(tokenize(question+' '+' '.join(dict.fromkeys(expansions))).split()))[:80]
            match=' OR '.join('"'+term.replace('"','""')+'"' for term in terms)
            lexical_rankings.append([r['unit_id'] for r in db.execute('SELECT unit_id FROM lexical WHERE lexical MATCH ? ORDER BY bm25(lexical) LIMIT 40',(match,))] if match else [])
    vectors=[]
    for offset in range(0,len(questions),64):vectors.extend(encoder(store).encode(questions[offset:offset+64])['vectors'])
    decoded={u['id']:json.loads(u['vector']) for u in units}
    cards={}
    for u in units:cards.setdefault(u['card_id'],[]).append(u)
    dense_rankings=None
    try:
        import numpy as np
        matrix=np.asarray([decoded[u['id']] for u in units],dtype=np.float32)
        queries=np.asarray(vectors,dtype=np.float32)
        scores=(queries@matrix.T)/(np.maximum(np.linalg.norm(queries,axis=1),1e-12)[:,None]*np.maximum(np.linalg.norm(matrix,axis=1),1e-12)[None,:])
        dense_rankings=[[(units[int(i)]['id'],float(row[i])) for i in np.argsort(-row)[:40]] for row in scores]
    except ImportError:pass # Identical learned vectors/cosine, slower fallback.
    return [rank_units(info,units,decoded,cards,lexical,vector,dense_rankings[i] if dense_rankings is not None else None) for i,(lexical,vector) in enumerate(zip(lexical_rankings,vectors))]

def rank_units(info,units,decoded,cards,lexical,vector,dense=None):
    if dense is None:dense=sorted([(u['id'],cosine(vector,decoded[u['id']])) for u in units],key=lambda pair:pair[1],reverse=True)[:40]
    scores={};by_id={u['id']:u for u in units}
    for ranking in [lexical,[id for id,_ in dense]]:
        for rank,id in enumerate(ranking):scores[id]=scores.get(id,0)+1/(60+rank+1)
    linked={}
    for id in sorted(scores,key=scores.get,reverse=True)[:5]:
        for card in json.loads(by_id[id]['links']):
            for candidate in cards.get(card,[]):linked[candidate['id']]=max(linked.get(candidate['id'],0),scores[id]*.08)
    for id,boost in linked.items():scores[id]=scores.get(id,0)+boost
    hits=[]
    for id in sorted(scores,key=scores.get,reverse=True):
        u=by_id[id]
        if u.get('claim_type') in {'research_idea','inference'}:continue
        evidence=json.loads(u['evidence']);e=evidence[0]
        hits.append({'id':id,'card_id':u['card_id'],'layer_id':u['layer_id'],'title':u['title'],'text':u['content'],'kind':'knowledge_card','score':scores[id],'resource_id':e['resource_id'],'version_id':e['version_id'],'locator':{k:v for k,v in e.items() if k not in {'resource_id','version_id'}},'evidence':evidence,'dense_similarity':dict(dense).get(id),'verification_status':'codex_needs_review'})
        if len(hits)>=20:break
    return {'provider':'local_bm25_fastembed_rrf','learned_model':True,'model_id':info['model_id'],'hits':hits,'warnings':['检索命中不代表结论已审核；没有依据的问题需由 Codex 明确拒答。']}


PROCESSING='dual-parent-bilingual-card320-source360-v4'
TOKENIZER='knowline-identifiers-cjk-bigrams-v1'

def build(store,kb,cards,report,resources=None,index_dir=None):
    from .store import tokenize
    from .knowledge_evidence import raw_parents,card_parents,units_from_parents
    from .knowledge import get
    start=time.perf_counter();model=encoder(store);warnings=[]
    try:identity=model.encode([])
    except DomainError:
        identity={'model_id':'unavailable','learned_model':False,'dimensions':0};warnings.append('语义模型不可用；本次仅建立真实原文与知识卡关键词索引。')
    resources=resources or []
    originals=raw_parents(store,resources)
    source_keys={p['evidence'][0]['resource_id']:p['source_key'] for p in originals}
    parents=card_parents(cards)+originals
    for p in parents:p['independent_sources']=sorted({source_keys.get(e['resource_id'],'resource:'+e['resource_id']) for e in p['evidence']})
    profile={k:identity.get(k) for k in ('model_id','model_revision','tokenizer_sha256','query_instruction','document_instruction','pooling','dimensions')}
    profile.update(processing=PROCESSING,lexical_tokenizer=TOKENIZER)
    identity_key=hashlib.sha256(json.dumps(profile,sort_keys=True).encode()).hexdigest()
    fingerprint=hashlib.sha256(json.dumps({'profile':profile,'parents':parents,'layers':kb['layers']},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    previous=(get(store,'kb_cards:'+kb['id'],{}).get('retrieval') or {})
    if previous.get('input_fingerprint')==fingerprint:
        if digest(contained(store.project,previous['path']))!=previous['sha256']:raise DomainError('snapshot_corrupt')
        info={**previous,'vectors_computed':0,'vectors_reused':previous['units'],'index_reused':True}
        info['evaluation']=evaluate(store,info,report);return info
    folder=index_dir or store.state/'knowledge-index'/kb['id'];folder.mkdir(parents=True,exist_ok=True)
    path=folder/(kb['build_id']+'-'+uuid.uuid4().hex[:8]+'.sqlite')
    units=units_from_parents(parents);computed=0;reused=0
    with closing(sqlite3.connect(store.state/'knowledge-vector-cache.sqlite')) as cache:
        cache.execute('CREATE TABLE IF NOT EXISTS vectors(model TEXT,hash TEXT,vector TEXT,PRIMARY KEY(model,hash))')
        for u in units:
            prior=cache.execute('SELECT vector FROM vectors WHERE model=? AND hash=?',(identity_key,u['hash'])).fetchone()
            u['vector']=json.loads(prior[0]) if prior and identity['learned_model'] else None;reused+=u['vector'] is not None
        missing=[u for u in units if u['vector'] is None]
        if identity['learned_model']:
            for offset in range(0,len(missing),64):
                batch=missing[offset:offset+64];answer=model.encode([u['context'] for u in batch])
                if answer['model_id']!=identity['model_id'] or answer.get('tokenizer_sha256')!=identity.get('tokenizer_sha256'):raise DomainError('semantic_model_changed')
                for u,v in zip(batch,answer['vectors']):
                    if len(v)!=identity['dimensions'] or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in v):raise DomainError('semantic_runtime_failed')
                    u['vector']=v;cache.execute('INSERT OR REPLACE INTO vectors VALUES(?,?,?)',(identity_key,u['hash'],json.dumps(v)));computed+=1
            from .retention import bound_vectors
            bound_vectors(cache,store)
        cache.commit()
    with closing(sqlite3.connect(path)) as db:
        db.executescript('CREATE TABLE parents(id TEXT PRIMARY KEY,data TEXT);CREATE TABLE units(id TEXT PRIMARY KEY,parent_id TEXT,data TEXT);CREATE VIRTUAL TABLE lexical USING fts5(unit_id UNINDEXED,tokens);')
        for parent in parents:db.execute('INSERT INTO parents VALUES(?,?)',(parent['id'],json.dumps(parent,ensure_ascii=False)))
        for u in units:
            db.execute('INSERT INTO units VALUES(?,?,?)',(u['id'],u['parent_id'],json.dumps(u,ensure_ascii=False)))
            db.execute('INSERT INTO lexical VALUES(?,?)',(u['id'],tokenize(u['context']+' '+' '.join(u['terms']+u['aliases']))))
        db.commit()
    info={'schema_version':4,'path':path.relative_to(store.project).as_posix(),'sha256':digest(path),
          'input_fingerprint':fingerprint,'encoding_profile':profile,'model_id':identity['model_id'],
          'learned_model':identity['learned_model'],'dimensions':identity['dimensions'],'processing_version':PROCESSING,
          'lexical':'sqlite_fts5_bm25','fusion':'RRF','units':len(units),'raw_units':sum(u['kind']=='raw_evidence' for u in units),
          'knowledge_units':sum(u['kind']=='knowledge_card' for u in units),'parents':len(parents),
          'vectors_computed':computed,'vectors_reused':reused,'index_reused':False,'query_requires_source_pdf':False,
          'source_scope':'frozen_originals_and_claim_cited_cards','warnings':warnings,
          'source_versions':[{k:r[k] for k in ('resource_id','version_id','sha256')} for r in resources]}
    try:info['evaluation']=evaluate(store,info,report)
    except DomainError as exc:
        atomic_json(path.with_suffix('.manifest.json'),{**info,'evaluation_failed':True,'error':exc.code,'error_params':exc.params});raise
    info['build_duration_ms']=round((time.perf_counter()-start)*1000,3)
    atomic_json(path.with_suffix('.manifest.json'),info)
    return info

def load_index(store,info):
    path=contained(store.project,info['path'])
    if digest(path)!=info['sha256']:raise DomainError('snapshot_corrupt')
    return path

def query_batch(store,info,questions,purpose='evidence',layer_ids=None,top_k=40):
    if info.get('schema_version')!=4:return legacy_query_batch(store,info,questions)
    if not questions:return []
    if purpose not in {'evidence','inspiration'}:raise DomainError('invalid_request')
    from .store import tokenize
    path=load_index(store,info);started=time.perf_counter();warnings=list(info.get('warnings',[]))
    with closing(sqlite3.connect(f'file:{path.as_posix()}?mode=ro',uri=True)) as db:
        units=[json.loads(row[0]) for row in db.execute('SELECT data FROM units')]
        parents={row[0]:json.loads(row[1]) for row in db.execute('SELECT id,data FROM parents')}
        # Filter before both recall and explicit-link expansion. Ideas cannot
        # become factual evidence by acquiring a high semantic similarity.
        eligible={u['id']:u for u in units if (purpose=='inspiration' or u['claim_type'] not in {'research_idea','inference'}) and
                  (not layer_ids or u['kind']=='raw_evidence' or set(layer_ids)&set(u['layer_ids']))}
        lexical=[]
        for question in questions:
            terms=list(dict.fromkeys(tokenize(question).split()))[:80]
            match=' OR '.join('"'+t.replace('"','""')+'"' for t in terms)
            # Recall each role independently: Chinese summaries must not hide
            # English originals, nor English originals hide method navigation.
            all_lexical=[r[0] for r in db.execute('SELECT unit_id FROM lexical WHERE lexical MATCH ? ORDER BY bm25(lexical)',(match,)) if r[0] in eligible] if match else []
            ranking={kind:[uid for uid in all_lexical if eligible[uid]['kind']==kind][:60] for kind in ('knowledge_card','raw_evidence')}
            lexical.append(ranking)
    vectors=[None]*len(questions);learned=False
    if info['learned_model']:
        try:
            answer=encoder(store).encode(questions,kind='query')
            if answer['model_id']!=info['model_id'] or answer.get('tokenizer_sha256')!=info['encoding_profile'].get('tokenizer_sha256') or answer.get('query_instruction')!=info['encoding_profile'].get('query_instruction'):
                raise DomainError('semantic_model_changed')
            vectors=answer['vectors'];learned=True
        except DomainError:warnings.append('语义模型不可用或模型/分词器/指令已变化；本次降级关键词检索，请重建索引。')
    dense_rankings=None
    if learned:
        try:
            import numpy as np
            scored=[u for u in eligible.values() if u['vector']]
            if scored:
                matrix=np.asarray([u['vector'] for u in scored],dtype=np.float32);queries=np.asarray(vectors,dtype=np.float32)
                similarities=(queries@matrix.T)/(np.maximum(np.linalg.norm(queries,axis=1),1e-12)[:,None]*np.maximum(np.linalg.norm(matrix,axis=1),1e-12)[None,:])
                dense_rankings=[[(scored[int(i)]['id'],float(row[i])) for i in np.argsort(-row,kind='stable')] for row in similarities]
        except ImportError:pass # Same learned vectors and cosine, slower fallback.
    answers=[];shared_ms=(time.perf_counter()-started)*1000/len(questions)
    for query_index,(question,lexical_ids,vector) in enumerate(zip(questions,lexical,vectors)):
        query_started=time.perf_counter()
        dense=dense_rankings[query_index] if dense_rankings is not None else sorted([(u['id'],cosine(vector,u['vector'])) for u in eligible.values() if vector is not None and u['vector']],key=lambda p:p[1],reverse=True)
        scores={}
        for kind in ('knowledge_card','raw_evidence'):
            for ranking in (lexical_ids[kind],[uid for uid,_ in dense if eligible[uid]['kind']==kind][:60]):
                for rank,uid in enumerate(ranking):scores[uid]=scores.get(uid,0)+1/(61+rank)
        by_card={}
        for u in eligible.values():by_card.setdefault(u.get('card_id'),[]).append(u['id'])
        for uid in sorted(scores,key=scores.get,reverse=True)[:5]:
            for card_id in eligible[uid]['links']:
                for related in by_card.get(card_id,[]):scores[related]=scores.get(related,0)+scores[uid]*.04
        ordered=sorted(scores,key=scores.get,reverse=True)
        candidates={uid for kind in ('knowledge_card','raw_evidence') for uid in [i for i in ordered if eligible[i]['kind']==kind][:60]}
        ids=[uid for uid in ordered if uid in candidates];rerank_status={'status':'not_available','learned_model':False}
        rerank_scores={}
        if ids:
            try:
                result=encoder(store).rerank(question,[eligible[i]['context'] for i in ids[:60]])
                if result.get('available'):
                    values=list(result['scores']);calls=1
                    for offset in range(60,len(ids),60):
                        more=encoder(store).rerank(question,[eligible[i]['context'] for i in ids[offset:offset+60]])
                        if not more.get('available') or more.get('model_id')!=result['model_id']:raise DomainError('semantic_runtime_failed')
                        values.extend(more['scores']);calls+=1
                    if len(values)!=len(ids) or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in values):raise DomainError('semantic_runtime_failed')
                    rerank_scores=dict(zip(ids,values));ids.sort(key=lambda i:(rerank_scores[i],scores[i]),reverse=True)
                    rerank_status={'status':'applied','learned_model':True,'model_id':result['model_id'],'inferences':calls}
                else:rerank_status['reason']=result.get('reason','local_model_not_installed')
            except DomainError:rerank_status['reason']='reranker_failed_using_rrf'
        hits=[];seen=set();role_counts={'knowledge_card':0,'raw_evidence':0};card_counts={};parent_counts={}
        role_limit=max(1,(top_k+1)//2)
        for uid in ids:
            u=eligible[uid];parent=parents[u['parent_id']]
            # Keep distinct method/limitation windows from the same card. Only
            # exact duplicate source spans are coalesced, after reranking.
            marker=(parent['id'],tuple(u['offset']))
            if marker in seen:continue
            if role_counts[u['kind']]>=role_limit:continue
            # Diversify only after full-window recall and reranking. Retain
            # two different claims/sections per card; originals already return
            # the complete page/function, so duplicate parents add no context.
            if u['kind']=='knowledge_card' and card_counts.get(u['card_id'],0)>=2:continue
            if u['kind']=='raw_evidence' and parent_counts.get(parent['id'],0):continue
            seen.add(marker);e=u['evidence'][0]
            role_counts[u['kind']]+=1
            card_counts[u['card_id']]=card_counts.get(u['card_id'],0)+1;parent_counts[parent['id']]=1
            evidence_sources=set(parent['independent_sources'])
            hits.append({'id':uid,'parent_id':parent['id'],'card_id':u['card_id'],'layer_id':u['layer_id'],'layer_ids':u['layer_ids'],
                         'title':u['title'],'text':u['content'],'context':parent['content'],'kind':u['kind'],'claim_type':u['claim_type'],
                         'claim_id':parent.get('claim_id'),'score':scores[uid],'rerank_score':rerank_scores.get(uid),
                         'resource_id':e['resource_id'],'version_id':e['version_id'],'locator':{k:v for k,v in e.items() if k not in {'resource_id','version_id'}},
                         'evidence':u['evidence'],'source_keys':sorted(evidence_sources),
                         'proof_eligible':u['kind']=='raw_evidence' and e.get('source_kind')!='link_descriptor_only',
                         'retrieval_role':'original_evidence' if u['kind']=='raw_evidence' else 'knowledge_navigation',
                         'verification_status':parent['verification_status'],'requires_primary_source_check':u['kind']=='knowledge_card'})
            if len(hits)>=top_k:break
        # Existing explicit relationships supply a small navigation supplement.
        # Include backlinks (experiment -> method is also useful when the
        # method is found first), never traverse an unbounded graph.
        seed_cards=list(dict.fromkeys(h['card_id'] for h in hits if h['card_id']))[:5]
        present_cards={h['card_id'] for h in hits if h['card_id']};related_cards=set()
        for uid,u in eligible.items():
            if u['card_id'] in seed_cards:related_cards.update(u['links'])
            if set(u['links'])&set(seed_cards):related_cards.add(u['card_id'])
        related_ids=sorted((uid for uid,u in eligible.items() if u['card_id'] in related_cards-present_cards),key=lambda uid:scores.get(uid,0),reverse=True)
        related_count=0
        for uid in related_ids:
            u=eligible[uid]
            if u['card_id'] in present_cards:continue
            present_cards.add(u['card_id']);parent=parents[u['parent_id']];e=u['evidence'][0]
            hits.append({'id':uid,'parent_id':parent['id'],'card_id':u['card_id'],'layer_id':u['layer_id'],'layer_ids':u['layer_ids'],
                         'title':u['title'],'text':u['content'],'context':parent['content'],'kind':u['kind'],'claim_type':u['claim_type'],
                         'claim_id':parent.get('claim_id'),'score':None,'rerank_score':None,
                         'resource_id':e['resource_id'],'version_id':e['version_id'],'locator':{k:v for k,v in e.items() if k not in {'resource_id','version_id'}},
                         'evidence':u['evidence'],'source_keys':parent['independent_sources'],'proof_eligible':False,
                         'retrieval_role':'knowledge_navigation','verification_status':parent['verification_status'],
                         'requires_primary_source_check':True,'retrieval_via':'explicit_relation','relation_seed_cards':seed_cards})
            related_count+=1
            if related_count>=8:break
        # Expand cited original parents after recall. This is deterministic
        # source navigation, not another model call or benchmark-conditioned
        # search. Return it separately from similarity scores, with a bound.
        original_lookup={}
        card_sources={}
        for parent in parents.values():
            if parent['kind']=='raw_evidence':
                e=parent['evidence'][0]
                original_lookup.setdefault((e['resource_id'],e['version_id'],e.get('page_index'),e.get('file')),[]).append(parent)
            elif parent['claim_type'] not in {'research_idea','inference'} or purpose=='inspiration':
                card_sources.setdefault(parent['card_id'],[]).extend(parent['evidence'])
        expanded=[];seen_parents={h['parent_id'] for h in hits if h['kind']=='raw_evidence'}
        for hit in hits:
            if hit['kind']!='knowledge_card':continue
            for e in card_sources.get(hit['card_id'],hit['evidence']):
                for parent in original_lookup.get((e['resource_id'],e['version_id'],e.get('page_index'),e.get('file')),[]):
                    if parent['id'] in seen_parents:continue
                    pe=parent['evidence'][0]
                    if 'file' in e and not (pe['line_start']<=e['line_end'] and e['line_start']<=pe['line_end']):continue
                    seen_parents.add(parent['id'])
                    expanded.append({'id':parent['id']+':context','parent_id':parent['id'],'card_id':None,'layer_id':None,'layer_ids':[],
                                     'title':parent['title'],'text':parent['content'],'context':parent['content'],'kind':'raw_evidence',
                                     'claim_type':'original_source','claim_id':None,'score':None,'rerank_score':None,
                                     'resource_id':pe['resource_id'],'version_id':pe['version_id'],'locator':{k:v for k,v in pe.items() if k not in {'resource_id','version_id'}},
                                     'evidence':[{**pe,'quote':parent['content']}],'source_keys':parent['independent_sources'],
                                     'proof_eligible':pe.get('source_kind')!='link_descriptor_only','retrieval_role':'original_evidence',
                                     'verification_status':parent['verification_status'],'requires_primary_source_check':False,
                                     'retrieval_via':'cited_parent_context','cited_by':hit['id']})
                    if len(expanded)>=24:break
                if len(expanded)>=24:break
            if len(expanded)>=24:break
        hits.extend(expanded)
        answers.append({'provider':'local_dual_bm25_vector_rrf','learned_model':learned,'model_id':info['model_id'],'hits':hits,
                        'ranked_hit_count':len(hits)-len(expanded)-related_count,'related_knowledge_count':related_count,
                        'source_context_count':len(expanded),'candidate_limit_per_role':60,
                        'purpose':purpose,'reranker':rerank_status,'independent_source_count':len({s for h in hits for s in h['source_keys']}),
                        'answerability':'requires_evidence_judgment' if hits else 'no_matching_evidence',
                        'warnings':warnings+['相关性不是事实证明；推断/设想仅供灵感，未知内容不可补造。'],
                        'elapsed_ms':round(shared_ms+(time.perf_counter()-query_started)*1000,3),'timing_scope':'query_plus_amortized_shared_batch_recall'})
    return answers

def expand(store,info,unit_id):
    if info.get('schema_version')!=4:raise DomainError('knowledge_index_upgrade_required')
    path=load_index(store,info)
    with closing(sqlite3.connect(f'file:{path.as_posix()}?mode=ro',uri=True)) as db:
        row=db.execute('SELECT parent_id FROM units WHERE id=?',(unit_id,)).fetchone()
        if not row and unit_id.endswith(':context'):
            row=db.execute('SELECT id FROM parents WHERE id=?',(unit_id[:-len(':context')],)).fetchone()
        if not row:raise DomainError('evidence_not_found',404)
        parent=json.loads(db.execute('SELECT data FROM parents WHERE id=?',(row[0],)).fetchone()[0])
        related=[]
        if parent['kind']=='raw_evidence' and 'page_index' in parent['evidence'][0]:
            e=parent['evidence'][0]
            for record in db.execute('SELECT data FROM parents'):
                p=json.loads(record[0]);pe=p['evidence'][0]
                if p['kind']=='raw_evidence' and pe['resource_id']==e['resource_id'] and abs(pe.get('page_index',-100)-e['page_index'])==1:related.append(p)
    return {'parent':parent,'adjacent_pages':related,'original_context_preserved':True}

def evaluate(store,info,report):
    if info.get('schema_version')!=4:return legacy_evaluate(store,info,report)
    cases=report.get('queries',[]);answers=[None]*len(cases);batches=0
    for purpose in ('evidence','inspiration'):
        selected=[(i,c) for i,c in enumerate(cases) if c.get('purpose','inspiration' if c.get('category')=='research_design' else 'evidence')==purpose]
        if selected:
            batches+=1
            for (i,_),answer in zip(selected,query_batch(store,info,[c['query'] for _,c in selected],purpose=purpose)):answers[i]=answer
    if any(a is None for a in answers):raise DomainError('invalid_request')
    results=[]
    for case,answer in zip(cases,answers):
        hits=answer['hits'];found={h['card_id'] for h in hits if h['card_id']};expected=set(case.get('expected_card_ids',[]))
        matches=[]
        for e in case.get('expected_evidence',[]):
            matches.append(any(h['kind']=='raw_evidence' and h['resource_id']==e['resource_id'] and h['version_id']==e['version_id'] and
                               ('page_index' not in e or h['locator'].get('page_index')==e['page_index']) and
                               ('file' not in e or h['locator'].get('file')==e['file']) and
                               normalized(e['quote']) in normalized(h['context']) for h in hits))
        passed=(not expected or expected<=found) and all(matches)
        results.append({'query':case['query'],'category':case.get('category'),'purpose':answer['purpose'],'expected_card_ids':sorted(expected),'found_card_ids':sorted(found),
                        'all_required_evidence_retrieved':all(matches) if matches else None,'evidence_recall':sum(matches)/len(matches) if matches else None,
                        'retrieval_passed':passed,'answer_correctness':'not_evaluated','answer_checks':case.get('answer_checks',[]),
                        'negative_case_status':'requires_answer_refusal_review' if case.get('category')=='unanswerable' else None,
                        'query_ms':answer['elapsed_ms'],'reranker':answer['reranker']})
    if any(not r['retrieval_passed'] for r in results):raise DomainError('knowledge_retrieval_eval_failed',failed_queries=[r['query'] for r in results if not r['retrieval_passed']],cases=results)
    return {'cases':results,'case_count':len(results),'critical_evidence_gate':'all_expected_sources_not_one_card',
            'semantic_and_experiment_readiness':'requires_answer_and_researcher_evaluation','embedding_batches':batches if info['learned_model'] else 0,
            'reranker_inferences':sum(a['reranker'].get('inferences',0) for a in answers),'remote_api_cost':0}
