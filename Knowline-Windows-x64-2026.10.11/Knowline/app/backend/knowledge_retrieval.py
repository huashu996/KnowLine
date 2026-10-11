"""Evidence-preserving knowledge-unit BM25 + learned vectors + explicit link fusion."""
import atexit,hashlib,json,math,os,re,sqlite3,subprocess,threading,unicodedata,uuid,sys,time
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .safety import DomainError,atomic_json,digest,contained
from .layout import app_dir


class Encoder:
    def __init__(self,app):self.app=app;self.process=None;self.lock=threading.Lock();self.reader=ThreadPoolExecutor(max_workers=1)
    def encode(self,texts):
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
            self.process.stdin.write(json.dumps({'texts':texts},ensure_ascii=True)+'\n');self.process.stdin.flush()
            try:answer=json.loads(self.reader.submit(self.process.stdout.readline).result(timeout=120))
            except Exception as exc:self.close();raise DomainError('semantic_runtime_failed') from exc
            if 'error' in answer or not answer.get('learned_model') or len(answer.get('vectors',[]))!=len(texts):raise DomainError('semantic_runtime_failed')
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


def build(store,kb,cards,report):
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


def evaluate(store,info,report):
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

def query_batch(store,info,questions):
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
    seen_cards=set()
    for id in sorted(scores,key=scores.get,reverse=True):
        u=by_id[id];evidence=json.loads(u['evidence']);e=evidence[0]
        if u['card_id'] in seen_cards:continue
        seen_cards.add(u['card_id'])
        hits.append({'id':id,'card_id':u['card_id'],'layer_id':u['layer_id'],'title':u['title'],'text':u['content'],'kind':'knowledge_card','score':scores[id],'resource_id':e['resource_id'],'version_id':e['version_id'],'locator':{k:v for k,v in e.items() if k not in {'resource_id','version_id'}},'evidence':evidence,'dense_similarity':dict(dense).get(id),'verification_status':'codex_needs_review'})
        if len(hits)>=20:break
    return {'provider':'local_bm25_fastembed_rrf','learned_model':True,'model_id':info['model_id'],'hits':hits,'warnings':['检索命中不代表结论已审核；没有依据的问题需由 Codex 明确拒答。']}
