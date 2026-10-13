"""Run an external question set through the public KB query API, without mutating data."""
import argparse,json,statistics,time,urllib.parse,urllib.request,unicodedata,re
from pathlib import Path

def norm(text):return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',text)).strip()
def audit(base,kb_id,cases):
    def get(route):
        with urllib.request.urlopen(base+route,timeout=120) as response:return json.load(response)
    kb=get('/knowledge-bases/'+kb_id)
    if kb['knowledge_state']!='organized':raise ValueError('Knowledge is not published')
    results=[]
    for case in cases:
        purpose=case.get('purpose','evidence');start=time.perf_counter()
        answer=get('/knowledge-bases/'+kb_id+'/query?'+urllib.parse.urlencode({'q':case['query'],'kb_revision':kb['revision'],'purpose':purpose}))
        matches=[]
        for e in case.get('expected_evidence',[]):
            matches.append(any(h['kind']=='raw_evidence' and h['resource_id']==e['resource_id'] and h['version_id']==e['version_id'] and
                               ('page_index' not in e or h['locator'].get('page_index')==e['page_index']) and norm(e['quote']) in norm(h['context']) for h in answer['hits']))
        results.append({'query':case['query'],'purpose':purpose,'expectation':case.get('expectation'),
                        'required_source_recall':sum(matches)/len(matches) if matches else None,'all_sources_found':all(matches) if matches else None,
                        'http_seconds':round(time.perf_counter()-start,4),'query_ms':answer.get('elapsed_ms'),
                        'hit_kinds':sorted({h['kind'] for h in answer['hits']}),'source_count':answer.get('independent_source_count'),
                        'reranker':answer.get('reranker'),'hits':[{k:h.get(k) for k in ('id','title','kind','resource_id','version_id','locator','proof_eligible')} for h in answer['hits']],
                        'answer_review':'pending','answer_checks':case.get('answer_checks',[])})
    elapsed=[r['http_seconds'] for r in results]
    return {'kb_id':kb_id,'kb_revision':kb['revision'],'source_count':len(kb['resource_ids']),'cards':kb['card_count'],
            'retrieval':kb['retrieval'],'case_count':len(results),'cases':results,'median_http_seconds':statistics.median(elapsed),
            'max_http_seconds':max(elapsed),'source_recall_cases_passed':sum(r['all_sources_found'] is True for r in results),
            'source_recall_cases_total':sum(r['all_sources_found'] is not None for r in results),
            'scope':'Retrieval only; answer support, refusal and experiment readiness require actual answer review. No scientific success claim.'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('kb');p.add_argument('cases',type=Path);p.add_argument('output',type=Path);p.add_argument('--port',type=int,required=True);args=p.parse_args()
    report=audit(f'http://127.0.0.1:{args.port}/api/v1',args.kb,json.loads(args.cases.read_text('utf-8-sig')))
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'cases','retrieval'}},ensure_ascii=False))
