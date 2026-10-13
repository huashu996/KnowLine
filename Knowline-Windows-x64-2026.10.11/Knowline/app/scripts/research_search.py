"""Read-only evidence retrieval via the task-scoped public single-writer service."""
import argparse,json,sys,urllib.request,uuid
from pathlib import Path
APP=Path(__file__).resolve().parents[1];sys.path.insert(0,str(APP))
from backend.layout import project_root,data_path
from backend.safety import contained,atomic_json

def search(context_path,queries_path):
    project=project_root(APP);context=json.loads(contained(project,context_path).read_text('utf-8-sig'))
    output=contained(project,context['output_dir']);path=contained(output,queries_path)
    queries=json.loads(path.read_text('utf-8-sig'))
    config=json.loads(data_path(project,'.knowledge/config.json').read_text('utf-8'))
    base='http://127.0.0.1:'+str(config['port'])+'/api/v1'
    def get(path):
        with urllib.request.urlopen(base+path,timeout=20) as r:return json.load(r)
    session=get('/session')
    if Path(session['project_root']).resolve()!=project:raise ValueError('project mismatch')
    job=get('/jobs/'+context['job_id'])
    if job['context']!=context:raise ValueError('frozen context mismatch')
    body={'queries':queries,'base_revision':job['revision'],'operation_id':'op_'+str(uuid.uuid4())}
    req=urllib.request.Request(base+'/jobs/'+context['job_id']+'/research-search',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-KW-Token':session['token']})
    with urllib.request.urlopen(req,timeout=600) as response:result=json.load(response)
    saved=output/'research-search-response.json';atomic_json(saved,result)
    # Return compact locators, keeping every full original parent in the saved
    # response and index. The caller expands only contexts actually needed.
    for lane in result['results']:
        for h in lane['hits']:h.pop('context',None)
    result['full_contexts_path']=str(saved)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('context');p.add_argument('queries');a=p.parse_args();search(a.context,a.queries)
