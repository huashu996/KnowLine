"""Bounded public Crossref audit. Produces evidence only; never edits tasks or resources."""
import json,re,sys,time,urllib.request,urllib.parse,urllib.error,argparse,hashlib,copy
from pathlib import Path
from datetime import datetime,timezone
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor

def norm(s):return re.sub('[^a-z0-9]','',str(s).lower())
def name(a):return a if isinstance(a,str) else ' '.join(str(a.get(k,'')) for k in ('given','family'))
def main(argv=None,quiet=False):
    parser=argparse.ArgumentParser();parser.add_argument('graph');parser.add_argument('--budget-seconds',type=int,default=75);parser.add_argument('--memory')
    args=parser.parse_args(argv);path=Path(args.graph).resolve(strict=True)
    graph=json.loads(path.read_text('utf-8-sig'))
    cached={}
    if args.memory:
        memory=Path(args.memory).resolve(strict=True)
        project=next((p for p in path.parents if (p/'app/AGENTS.md').is_file() or (p/'AGENTS.md').is_file()),None)
        if project and memory.is_relative_to(project) and memory.stat().st_size<=2*1024*1024:
            for paper in json.loads(memory.read_text('utf-8-sig')).get('papers',[]):
                evidence=paper.get('citation_audit_artifact') or {}
                if not evidence.get('path'):continue
                source=(project/evidence['path']).resolve()
                try:
                    if not source.is_relative_to(project) or source.stat().st_size>2*1024*1024:continue
                    raw=source.read_bytes()
                    if hashlib.sha256(raw).hexdigest()!=evidence['sha256']:continue
                    row=next((r for r in json.loads(raw).get('rows',[]) if r['node_id']==paper['previous_node_id']),None)
                    if not row or row.get('match_basis')!='doi' or not paper.get('doi') or row.get('source_doi','').lower()!=paper['doi'].lower():continue
                    age=(datetime.now(timezone.utc)-datetime.fromisoformat(row['citation_source']['retrieved_at'].replace('Z','+00:00'))).total_seconds()
                    if not 0<=age<300 or not row.get('attempts'):continue
                    cached[paper['doi'].lower()]=row
                except (OSError,ValueError,KeyError):continue
    stop=time.monotonic()+max(10,min(150,args.budget_seconds))
    def audit(node):
        previous=cached.get(str(node.get('doi','')).lower())
        if previous and norm(previous['source_title'])==norm(node['title']) and norm(name(node['authors'][0])) in [norm(a) for a in previous['source_authors']]:
            return {**copy.deepcopy(previous),'node_id':node['id'],'title':node['title'],'reused_verified_response':True}
        attempts=[]; stamp=lambda:datetime.now(timezone.utc).isoformat()
        first=name(node['authors'][0]).split()[-1].casefold()
        def fetch(url):
            if time.monotonic()>stop:raise TimeoutError('bounded citation audit deadline reached')
            item={'url':url,'retrieved_at':stamp()};attempts.append(item)
            try:
                with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Knowline public citation identity audit'}),timeout=min(10,max(1,stop-time.monotonic()))) as r:
                    raw=r.read(2*1024*1024);item['status']=r.status;item['response']=json.loads(raw)
                    return item['response']['message']
            except urllib.error.HTTPError as exc:
                item.update(status=exc.code,error='HTTPError: '+str(exc),response_body=exc.read(2000).decode('utf-8','replace'))
                return None
            except Exception as exc:item['error']=type(exc).__name__+': '+str(exc);return None
        doi=(node.get('doi') or '').removeprefix('https://doi.org/')
        found=fetch('https://api.crossref.org/works/'+urllib.parse.quote(doi,safe='/')) if doi else None
        candidates=[found] if found else []
        # An identified DOI failure stays unknown. Do not turn a fixed-record
        # audit into another discovery query or retry a rate-limited source.
        if not doi and not found:
            data=fetch('https://api.crossref.org/works?'+urllib.parse.urlencode({'query.title':node['title'],'rows':5}))
            candidates=(data or {}).get('items',[])
        for c in candidates:
            title=(c.get('title') or [''])[0]
            score=SequenceMatcher(None,norm(title),norm(node['title'])).ratio()
            authors=[name(a) for a in c.get('author',[])]
            date=c.get('published',{}).get('date-parts',[[]])[0]
            year=date[0] if date else None
            same_doi=bool(doi and norm(c.get('DOI'))==norm(doi))
            if score<(.6 if same_doi else .88) or not any(first in a.casefold().split() for a in authors[:5]) or year and abs(year-node['year'])>2:continue
            count=c.get('is-referenced-by-count')
            if isinstance(count,int) and not isinstance(count,bool):
                url='https://api.crossref.org/works/'+urllib.parse.quote(c['DOI'],safe='/')
                return {'node_id':node['id'],'title':node['title'],'citation_count':count,'citation_source':{'url':url,'provider':'Crossref','retrieved_at':stamp()},'source_doi':c['DOI'],'source_title':title,'source_authors':authors,'source_year':year,'match_basis':'doi' if same_doi else 'title_author','attempts':attempts}
        reason='; '.join(a.get('error') or 'HTTP '+str(a.get('status'))+'，未找到标题、首位作者和年份一致的记录' for a in attempts)
        return {'node_id':node['id'],'title':node['title'],'citation_count':None,'reason':reason or '无可查询DOI，标题身份匹配未通过','attempts':attempts}
    rows=list(ThreadPoolExecutor(max_workers=4).map(audit,graph['nodes']))
    output=path.parent/'citation-audit.json'
    output.write_text(json.dumps({'schema_version':1,'provider':'Crossref','retrieved_at':datetime.now(timezone.utc).isoformat(),'rows':rows},ensure_ascii=False,indent=2),encoding='utf-8')
    report={'path':str(output),'known':sum(r['citation_count'] is not None for r in rows),'total':len(rows),'reused':sum(r.get('reused_verified_response') is True for r in rows)}
    if not quiet:print(json.dumps(report,ensure_ascii=True))
    return report

def run(graph,budget_seconds=75,memory=None):
    argv=[str(graph),'--budget-seconds',str(budget_seconds)]
    if memory:argv+=['--memory',str(memory)]
    return main(argv,quiet=True)
if __name__=='__main__':main()
