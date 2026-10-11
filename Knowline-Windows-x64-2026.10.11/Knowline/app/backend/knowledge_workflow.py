"""Hash-validated reuse of completed knowledge, never a raw-source shortcut."""
import copy,hashlib,json,shutil,time
from pathlib import Path
from .safety import atomic_json,contained,digest,DomainError

CONTRACT='layered-knowledge-efficient-v3'
def signature(context):
 resources=sorted((r['type'],r['sha256'],tuple(r.get('allowed_files',[]))) for r in context['resources'])
 layers=[(l['name'].strip(),l['focus'].strip()) for l in context['knowledge_layers']]
 return hashlib.sha256(json.dumps({'resources':resources,'layers':layers},ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def reuse(store,job):
 if job['task'] not in {'build_knowledge','update_knowledge'}:return None
 if job['context'].get('knowledge_build',{}).get('reuse_enabled') is False:return None
 started=time.monotonic();scope=signature(job['context']);output=contained(store.project,job['context']['output_dir'])
 from .knowledge import validate_result
 for row in store.rows("SELECT id FROM jobs WHERE task IN ('build_knowledge','update_knowledge') AND status='completed' ORDER BY updated_at DESC LIMIT 100"):
  if row['id']==job['id']:continue
  prior=store.job(row['id'])
  if signature(prior['context'])!=scope:continue
  try:prior_kb=store.kb(prior['context']['scope']['kb_id'])
  except DomainError:continue
  if prior_kb['knowledge_state']!='organized' or not prior_kb.get('retrieval',{}).get('learned_model'):continue
  result=copy.deepcopy(prior.get('result',{}))
  if not result.get('knowledge_cards') or not result.get('knowledge_build_report'):continue
  try:
   for artifact in result.get('artifacts',[]):
    source=contained(store.project,artifact['path'])
    if not source.is_file() or digest(source)!=artifact['sha256']:raise ValueError('changed artifact')
   old={r['resource_id']:r for r in prior['context']['resources']};new={r['sha256']:r for r in job['context']['resources']}
   for card in result['knowledge_cards']:
    for evidence in card['evidence']:
     current=new[old[evidence['resource_id']]['sha256']];evidence.update(resource_id=current['resource_id'],version_id=current['version_id'])
    if card.get('figure'):
     e=card['figure'];current=new[old[e['resource_id']]['sha256']];e.update(resource_id=current['resource_id'],version_id=current['version_id'])
   report=result['knowledge_build_report'];report.pop('timing',None)
   for r in report['resources']:
    current=new[old[r['resource_id']]['sha256']];r.update(resource_id=current['resource_id'],version_id=current['version_id'])
   result['claims']=[] # Cards carry their validated evidence; old claim IDs stay in archived provenance.
   result['job_id']=job['id'];result.pop('knowledge_base_id',None)
   validate_result(store,job,result)
  except (ValueError,KeyError,OSError,DomainError):continue
  artifacts=[]
  for i,a in enumerate(result.get('artifacts',[])):
   source=contained(store.project,a['path']);target=output/'reused-validated'/str(i)/source.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
   artifacts.append({**a,'path':target.relative_to(store.project).as_posix(),'sha256':digest(target)})
  result['artifacts']=artifacts
  result.setdefault('warnings',[]).append('本轮复用相同资料哈希、完全相同选层与侧重点的已发布知识；来源/引文与全部原检索题重新校验，不重新生成相同分析。')
  result['knowledge_reuse']={'contract':CONTRACT,'source_job_id':prior['id'],'scope_sha256':scope,'cards':len(result['knowledge_cards']),'queries':len(report['queries']),'validation_seconds':round(time.monotonic()-started,3),'exact_layers_and_source_hashes':True,'full_retrieval_revalidation_required':True}
  atomic_json(output/'result.json',result)
  return result
 return None

def checkpoint(store,job):
 """Retry the validated analysis checkpoint, with all retrieval checks rerun."""
 if job['task'] not in {'build_knowledge','update_knowledge'}:return None
 result=copy.deepcopy(job.get('result') or {})
 if not result.get('knowledge_cards') or not result.get('knowledge_build_report'):return None
 from .knowledge import validate_result
 try:
  validate_result(store,job,result)
  for a in result['artifacts']:
   p=contained(store.project,a['path'])
   if not p.is_file() or digest(p)!=a['sha256']:return None
 except (DomainError,ValueError,KeyError,OSError):return None
 result['knowledge_resume']={'validated_analysis_reused':True,'full_retrieval_revalidation_required':True}
 atomic_json(contained(store.project,job['context']['output_dir'])/'result.json',result)
 return result
