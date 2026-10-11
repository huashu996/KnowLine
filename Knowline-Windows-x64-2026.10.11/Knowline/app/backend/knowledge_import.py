"""Read a user-selected knowledge folder. Never execute its files or copy models.

Imported units retain their original provenance and relationship types; they are
not presented as newly authored Codex knowledge or verified PDF evidence.
"""
import json,sqlite3,hashlib
from pathlib import Path
from .safety import DomainError,contained,digest,json_text
from .knowledge import put,get

LAYER_NAMES={'01':'基础知识','02':'论文与创新','03':'代码架构'}
def selected_folder(value):
 if not isinstance(value,str) or not value.strip():raise DomainError('knowledge_folder_required')
 root=Path(value).absolute()
 if not root.is_dir():raise DomainError('knowledge_folder_not_found')
 for part in [root,*root.parents]:
  if part.is_symlink() or getattr(part.stat(follow_symlinks=False),'st_file_attributes',0)&0x400:raise DomainError('unsafe_link')
 return root

def read_folder(value):
 root=selected_folder(value);manifests=sorted(root.glob('*.rag.manifest.json'))
 if len(manifests)!=1:raise DomainError('knowledge_format_unsupported')
 manifest=contained(root,manifests[0])
 if manifest.stat().st_size>65536:raise DomainError('knowledge_import_limit')
 try:spec=json.loads(manifest.read_text('utf-8-sig'))
 except (ValueError,UnicodeError):raise DomainError('knowledge_format_unsupported')
 if not isinstance(spec,dict) or not isinstance(spec.get('database'),str):raise DomainError('knowledge_format_unsupported')
 database=contained(root,spec.get('database',''))
 if database.suffix not in {'.sqlite','.sqlite3','.db'} or database.stat().st_size>1024*1024*1024:raise DomainError('knowledge_format_unsupported')
 before=digest(database)
 try:
  with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as db:
   db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON');db.execute('PRAGMA trusted_schema=OFF')
   count=db.execute('SELECT count(*) FROM chunks').fetchone()[0]
   if not 1<=count<=20000:raise DomainError('knowledge_import_limit')
   docs={r['document_id']:dict(r) for r in db.execute('SELECT document_id,title,source_path,layer FROM documents')}
   rows=[dict(r) for r in db.execute('SELECT chunk_id,document_id,title,layer,content,keywords_json,source_locator_json,metadata_json,verification_status FROM chunks')]
   relations=[dict(r) for r in db.execute('SELECT source_chunk_id,target_chunk_id,relation_type,weight,evidence FROM relations LIMIT 100001')]
   if len(relations)>100000:raise DomainError('knowledge_import_limit')
 except sqlite3.DatabaseError:raise DomainError('knowledge_format_unsupported')
 if digest(database)!=before:raise DomainError('knowledge_source_changed',409)
 ids=set();total=0
 for r in rows:
  if not isinstance(r['chunk_id'],str) or r['chunk_id'] in ids or not isinstance(r['content'],str) or not r['content'].strip():raise DomainError('knowledge_source_invalid')
  ids.add(r['chunk_id']);total+=len(r['content'].encode('utf-8'))
  if total>64*1024*1024 or len(r['content'])>100000 or r['document_id'] not in docs:raise DomainError('knowledge_import_limit')
  if not isinstance(r['layer'],str):raise DomainError('knowledge_source_invalid')
  try:
   meta=json.loads(r['metadata_json'] or '{}');locator=json.loads(r['source_locator_json'] or '{}');terms=json.loads(r['keywords_json'] or '[]')
  except (ValueError,TypeError):raise DomainError('knowledge_source_invalid')
  if not isinstance(meta,dict) or not isinstance(locator,dict) or not isinstance(terms,list) or any(not isinstance(x,str) for x in terms):raise DomainError('knowledge_source_invalid')
  tags=meta.get('tags',[])
  if not isinstance(tags,list) or any(not isinstance(x,str) for x in tags):raise DomainError('knowledge_source_invalid')
  # References are retained as data; never follow a path found in the index.
 for r in relations:
  if r['source_chunk_id'] not in ids or r['target_chunk_id'] not in ids:raise DomainError('knowledge_source_invalid')
 return {'name':str(spec.get('name') or root.name)[:200],'root':str(root),'database_sha256':before,'database':database.relative_to(root).as_posix(),'documents':docs,'rows':rows,'relations':relations,'content_bytes':total}

def preview(value):
 data=read_folder(value);layers=sorted({r['layer'] for r in data['rows']})
 return {'name':data['name'],'source_sha256':data['database_sha256'],'document_count':len(data['documents']),'card_count':len(data['rows']),'relation_count':len(data['relations']),'layers':[{'id':str(l),'name':LAYER_NAMES.get(l,str(l)),'count':sum(r['layer']==l for r in data['rows'])} for l in layers],'content_bytes':data['content_bytes'],'warning':'仅导入已有知识内容和原有关系，不复制原库的模型、数据库、PDF 或运行环境；原文定位信息沿用原库，尚未重新核验。'}

def import_folder(store,body):
 from .store import uid,now,tokenize
 data=read_folder(body.get('folder'))
 if body.get('source_sha256')!=data['database_sha256']:raise DomainError('knowledge_source_changed',409)
 previous=get(store,'knowledge_import_hash:'+data['database_sha256'])
 if previous:
  try:return {'knowledge_base':store.kb(previous),'duplicate':True}
  except DomainError:pass
 id=uid('kb');build=uid('b');name=str(body.get('name') or data['name']).strip()[:200]
 if not name:raise DomainError('name_required')
 layers=[{'id':'import_'+str(l),'name':LAYER_NAMES.get(l,str(l)),'focus':'沿用所选知识库的已有内容与分类'} for l in sorted({r['layer'] for r in data['rows']})]
 store.db.execute("INSERT INTO knowledge_bases(id,name,index_state,build_id,created_at) VALUES(?,?,'ready',?,?)",(id,name,build,now()))
 put(store,'kb_structure:'+id,layers)
 root=store.node(id,build,'root',None,'knowledge_base',name)
 parents={l['id']:store.node(id,build,'layer:'+l['id'],root,'knowledge_layer',l['name']) for l in layers}
 cards=[];by_id={}
 for r in data['rows']:
  meta=json.loads(r['metadata_json'] or '{}');locator=json.loads(r['source_locator_json'] or '{}');doc=data['documents'][r['document_id']]
  card={'id':r['chunk_id'],'title':str(r['title'] or doc['title'])[:300],'content':r['content'],'layer_id':'import_'+str(r['layer']),'evidence':[],'links':[],'relations':[],'origin':'imported','status':'needs_review','tags':meta.get('tags',[]),'terms':json.loads(r['keywords_json'] or '[]'),'imported_sources':[{'kb_id':id,'document_id':r['document_id'],'title':doc['title'],'original_path':doc['source_path'],'locator':locator,'source_sha256':data['database_sha256'],'verification_status':r['verification_status']}],'source_document_id':r['document_id']}
  card['node_id']=store.node(id,build,'card:'+card['id'],parents[card['layer_id']],'knowledge_card',card['title'],[])
  cards.append(card);by_id[card['id']]=card
 for r in data['relations']:
  card=by_id[r['source_chunk_id']];card['links'].append(r['target_chunk_id']);card['relations'].append({'target':r['target_chunk_id'],'relation':r['relation_type'],'weight':r['weight'],'evidence':r['evidence']})
 for card in cards:card['links']=list(dict.fromkeys(card['links']))
 put(store,'kb_cards:'+id,{'build_id':build,'member_revision':1,'cards':cards,'retrieval':None,'origin':'imported'})
 put(store,'kb_import:'+id,{'folder_name':Path(data['root']).name,'database':data['database'],'database_sha256':data['database_sha256'],'document_count':len(data['documents']),'card_count':len(cards),'relation_count':len(data['relations']),'source_files_copied':0,'model_files_copied':0,'provenance_reverified':False})
 put(store,'knowledge_import_hash:'+data['database_sha256'],id)
 store.event('knowledge_base',id,1)
 return {'knowledge_base':store.kb(id),'duplicate':False,'import_summary':get(store,'kb_import:'+id)}

def query(store,kb,question):
 from .knowledge import cards
 words=question.casefold().split();hits=[]
 for card in cards(store,kb):
  text=(card['title']+' '+card['content']+' '+' '.join(card.get('tags',[]))).casefold()
  if words and all(w in text for w in words):hits.append({'id':card['id'],'card_id':card['id'],'title':card['title'],'text':card['content'],'kind':'imported_knowledge','score':sum(text.count(w) for w in words),'imported_source':card['imported_sources'][0],'locator':{}})
 return {'kb_id':kb['id'],'kb_revision':kb['revision'],'provider':'imported_knowledge_text_search','hits':sorted(hits,key=lambda h:-h['score'])[:20],'warnings':['按已有知识文字匹配，尚未接入原库语义向量。']}

def source_document(store,id,document_id):
 kb=store.kb(id)
 from .knowledge import cards
 values=[c for c in cards(store,kb) if c.get('source_document_id')==document_id]
 if not values:raise DomainError('knowledge_source_not_found',404)
 first=values[0]['imported_sources'][0]
 return '已导入的知识内容（沿用原库定位，未经重新核验）\n来源：'+first['title']+'\n原库路径：'+first['original_path']+'\n\n'+'\n\n'.join(c['title']+'\n'+c['content'] for c in values)
