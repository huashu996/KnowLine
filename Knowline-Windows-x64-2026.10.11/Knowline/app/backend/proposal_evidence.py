"""Task-frozen knowledge is a source in its own right, without inventing PDFs.

Citations certify snapshot/card/excerpt identity, never verification of a paper
or an experiment mentioned by that card. Original-resource citations retain
their existing stricter validator.
"""
import hashlib,json,re,sqlite3,time,unicodedata
from contextlib import closing
from .safety import DomainError,contained,digest

VERSION='frozen-knowledge-v1'
def norm(value):return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',value)).strip()
def sha(value):return hashlib.sha256(value.encode('utf-8')).hexdigest()
def tokens(value):
    # Keep identifiers and each CJK run; never create bigrams across words.
    words=re.findall(r'[a-z0-9_]+|[\u3400-\u9fff]+',unicodedata.normalize('NFKC',value).lower())
    return ' '.join(t for w in words for t in ([w]+[w[i:i+2] for i in range(len(w)-1)] if re.search(r'[\u3400-\u9fff]',w) else [w]))

def snapshot(store,kb):
    """Freeze accepted knowledge content, independently of source-file availability."""
    from .knowledge import get
    saved=get(store,'kb_cards:'+kb['id'],{})
    cards=saved.get('cards',[])
    if not cards:raise DomainError('knowledge_base_not_ready')
    return {**kb,'schema_version':1,'cards':cards,'card_count':len(cards),'resource_ids':[],
            'source_mode':'standalone_knowledge','knowledge_content_build_id':saved.get('build_id'),
            'primary_sources_required':False,'source_review_required':bool(kb.get('needs_revalidation')) or kb.get('knowledge_state')!='organized'}

class FrozenKnowledge:
    def __init__(self,store,job):
        self.store=store;self.job=job;self.cards={};self.bases={};self.identities={}
        from .knowledge_evidence import source_identity
        self.raw={r['resource_id']:source_identity(store.resource(r['resource_id'])) for r in job['context']['resources']}
        for kb in job['context'].get('proposal',{}).get('knowledge_bases',[]):
            path=contained(store.project,kb['snapshot_path'])
            data=path.read_bytes()
            if hashlib.sha256(data).hexdigest()!=kb['sha256']:raise DomainError('snapshot_corrupt')
            frozen=json.loads(data.decode('utf-8-sig'));self.bases[kb['id']]=kb
            if frozen.get('id')!=kb['id'] or frozen.get('revision')!=kb['revision']:raise DomainError('knowledge_snapshot_identity_mismatch')
            for card in frozen.get('cards',[]):
                if not isinstance(card.get('id'),str) or not isinstance(card.get('content'),str):raise DomainError('knowledge_card_invalid')
                key=(kb['id'],card['id'])
                if key in self.cards:raise DomainError('knowledge_card_duplicate')
                imported=(card.get('imported_sources') or [{}])[0]
                locator=imported.get('locator') or {}
                source_id=locator.get('source_id')
                document_id=imported.get('document_id') or card.get('source_document_id')
                original=imported.get('original_path')
                raw_ids={self.raw.get(e['resource_id'],'resource:'+e['resource_id']) for e in card.get('evidence',[]) if isinstance(e.get('resource_id'),str)}
                if imported:
                    namespace=imported.get('source_sha256') or kb['sha256']
                    doi=str(locator.get('doi') or '').strip().lower().removeprefix('https://doi.org/').removeprefix('doi:')
                    # A recorded DOI can collapse duplicate sources conservatively;
                    # it does not upgrade the card's primary-source verification.
                    identity='doi:'+doi if re.fullmatch(r'10\.\d{4,9}/\S+',doi) else 'knowledge-source:'+sha(namespace+'\0'+str(source_id or document_id or original or card['id']))
                elif len(raw_ids)==1:identity=next(iter(raw_ids))
                else:identity='knowledge-source:'+sha(kb['id']+'\0'+str(document_id or card['id']))
                entry={'kb':kb,'card':card,'hash':sha(card['content']),'source_key':identity,
                       'source_id':source_id,'imported_document_id':document_id,'imported_source_path':original,
                       'source_title':imported.get('title') or card.get('title',card['id'])}
                self.cards[key]=entry;self.identities.setdefault(identity,entry)
        self.signature=sha(json.dumps({'version':VERSION,'bases':[(k['id'],k['revision'],k['sha256']) for k in self.bases.values()]},sort_keys=True))

    def citation(self,entry,excerpt):
        kb=entry['kb'];card=entry['card']
        return {'kind':'frozen_knowledge_card','kb_id':kb['id'],'kb_revision':kb['revision'],
                'snapshot_path':kb['snapshot_path'],'snapshot_sha256':kb['sha256'],'card_id':card['id'],
                'card_content_sha256':entry['hash'],'excerpt':excerpt,'resource_id':None,
                'source_key':entry['source_key'],'source_id':entry['source_id'],
                'imported_document_id':entry['imported_document_id'],'imported_source_path':entry['imported_source_path'],
                'verification':'frozen_card_content_verified','primary_source_verified':False}

    def validate(self,e):
        entry=self.cards.get((e.get('kb_id'),e.get('card_id')))
        if not entry:raise DomainError('knowledge_citation_outside_scope')
        kb=entry['kb']
        if (e.get('kb_revision')!=kb['revision'] or e.get('snapshot_sha256')!=kb['sha256'] or
            e.get('snapshot_path')!=kb['snapshot_path'] or e.get('card_content_sha256')!=entry['hash']):
            raise DomainError('knowledge_citation_snapshot_mismatch')
        if e.get('resource_id') is not None or e.get('version_id') is not None or e.get('primary_source_verified') is True:
            raise DomainError('knowledge_citation_not_original_evidence')
        for field in ('source_key','source_id','imported_document_id','imported_source_path'):
            if e.get(field) is not None and e[field]!=entry[field]:raise DomainError('knowledge_citation_source_mismatch')
        excerpt=e.get('excerpt',e.get('quote'))
        if not isinstance(excerpt,str) or not norm(excerpt) or norm(excerpt) not in norm(entry['card']['content']):
            raise DomainError('knowledge_quote_not_found')
        return entry['source_key']

    def validate_any(self,e):
        if e.get('kind')=='frozen_knowledge_card':return self.validate(e)
        self.store.validate_evidence(e,self.job['context']['resources'])
        return self.raw[e['resource_id']]

    def rebind(self,e):
        """History may cite a different task path, but only identical bytes."""
        value=dict(e)
        if value.get('kind')=='frozen_knowledge_card' and value.get('kb_id') in self.bases:
            value['snapshot_path']=self.bases[value['kb_id']]['snapshot_path']
        self.validate_any(value)
        return value

    def search(self,queries,output,previous=None,top_k=12):
        started=time.perf_counter();path=contained(output,'frozen-knowledge.sqlite',False)
        reuse=bool(previous and previous.get('signature')==self.signature and previous.get('sha256') and path.is_file() and digest(path)==previous['sha256'])
        entries=list(self.cards.values())
        if not reuse:
            temporary=contained(output,'frozen-knowledge.build.sqlite',False)
            if temporary.exists():temporary.unlink()
            with closing(sqlite3.connect(temporary)) as db:
                db.execute('CREATE VIRTUAL TABLE cards USING fts5(title,body,tokenize="unicode61")')
                db.executemany('INSERT INTO cards(rowid,title,body) VALUES(?,?,?)',[(i+1,tokens(' '.join([e['source_title'],e['card'].get('title',''),str(e['source_id'] or '')])),tokens(e['card']['content'])) for i,e in enumerate(entries)])
                db.commit()
            temporary.replace(path)
        info={'signature':self.signature,'sha256':digest(path),'path':path.relative_to(self.store.project).as_posix(),'cards':len(entries),'version':VERSION}
        answers=[]
        with closing(sqlite3.connect('file:'+path.as_posix()+'?mode=ro',uri=True)) as db:
            for query in queries:
                terms=list(dict.fromkeys(tokens(query).split()))[:80]
                expression=' OR '.join('"'+t+'"' for t in terms)
                found=db.execute('SELECT rowid,bm25(cards,3.0,1.0) FROM cards WHERE cards MATCH ? ORDER BY bm25(cards,3.0,1.0) LIMIT 60',(expression,)).fetchall() if terms else []
                hits=[]
                for row,score in found:
                    entry=entries[row-1];card=entry['card'];content=card['content']
                    # Full card retained in context; the citation excerpt is verbatim.
                    positions=[content.lower().find(t.lower()) for t in terms if t.lower() in content.lower()]
                    start=max(0,min(positions,default=0)-100);excerpt=content[start:start+700]
                    evidence=self.citation(entry,excerpt)
                    hits.append({'id':entry['kb']['id']+':'+card['id'],'card_id':card['id'],'kb_id':entry['kb']['id'],
                                 'title':entry['source_title']+' · '+card.get('title',''),'text':excerpt,'context':content,
                                 'kind':'frozen_knowledge_card','claim_type':card.get('claim_type','unverified_knowledge'),
                                 'score':-score,'resource_id':None,'version_id':None,'evidence':[evidence],
                                 'independent_sources':[entry['source_key']],'source_key':entry['source_key'],
                                 'proof_eligible':False,'retrieval_role':'knowledge_source','requires_primary_source_check':True,
                                 'verification_status':'frozen_card_content_verified','primary_source_verified':False})
                # Keep lexical recall cheap. Optional learned reranking sees only candidates.
                reranker={'status':'not_available','learned_model':False}
                if hits:
                    from .knowledge_retrieval import encoder
                    try:
                        result=encoder(self.store).rerank(query,[h['title']+'\n'+h['text'] for h in hits])
                        if result.get('available') and len(result.get('scores',[]))==len(hits):
                            for h,score in zip(hits,result['scores']):h['rerank_score']=score
                            hits.sort(key=lambda h:h['rerank_score'],reverse=True)
                            reranker={'status':'applied','learned_model':True,'model_id':result.get('model_id')}
                    except (OSError,ValueError,DomainError):pass
                # Multiple cards from one document remain useful but cannot crowd out all alternatives.
                selected=[];counts={}
                for hit in hits:
                    identity=hit['source_key']
                    if counts.get(identity,0)>=3:continue
                    selected.append(hit);counts[identity]=counts.get(identity,0)+1
                    if len(selected)>=top_k:break
                answers.append({'hits':selected,'provider':'frozen_knowledge_bm25','learned_model':reranker['learned_model'],
                                'reranker':reranker,'independent_source_count':len(counts),'ranked_hit_count':len(selected),
                                'answerability':'knowledge_sources_available' if selected else 'no_matching_evidence',
                                'warnings':['知识卡内容可独立引用；引用只核验所选知识库快照，未重新核验其中提到的原始论文或实验。']})
        elapsed=round((time.perf_counter()-started)*1000/max(1,len(queries)),3)
        for answer in answers:answer['elapsed_ms']=elapsed
        return answers,info
