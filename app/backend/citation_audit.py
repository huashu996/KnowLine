"""Reuse exact citation counts and supplement references from independent public sources."""
import json,re,sys,time,urllib.request,urllib.parse,urllib.error,argparse,hashlib,copy
from pathlib import Path
from datetime import datetime,timezone
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor

def norm(s):return re.sub('[^a-z0-9]','',str(s).lower())
def name(a):return a if isinstance(a,str) else ' '.join(str(a.get(k,'')) for k in ('given','family'))
def main(argv=None,quiet=False):
    parser=argparse.ArgumentParser();parser.add_argument('graph');parser.add_argument('--budget-seconds',type=int,default=75);parser.add_argument('--memory');parser.add_argument('--reuse-responses')
    args=parser.parse_args(argv);path=Path(args.graph).resolve(strict=True)
    graph=json.loads(path.read_text('utf-8-sig'))
    cached={};local_records={};prior_rows=[];responses=[]
    prompt_path=path.parent/'agent-prompt.txt'
    attempt_started=prompt_path.stat().st_mtime if prompt_path.is_file() else None
    def reusable_at(value):
        point=datetime.fromisoformat(value.replace('Z','+00:00'))
        age=(datetime.now(timezone.utc)-point).total_seconds()
        return 0<=age<300 or age>=0 and attempt_started is not None and point.timestamp()>=attempt_started-30
    output=path.parent/'citation-audit.json'
    if output.is_file() and output.stat().st_size<=32*1024*1024:
        prior_rows=json.loads(output.read_text('utf-8-sig')).get('rows',[])
        for row in prior_rows:
            doi=str(row.get('source_doi','')).lower()
            if not doi or row.get('match_basis')!='doi':continue
            try:
                if reusable_at(row['citation_source']['retrieved_at']) and row.get('attempts'):cached[doi]=row
            except (KeyError,ValueError):pass
    response_path=Path(args.reuse_responses).resolve(strict=True) if args.reuse_responses else path.parent/'public-citation-responses.json'
    if response_path.is_file() and response_path.parent==path.parent and response_path.stat().st_size<=32*1024*1024:
        envelope=json.loads(response_path.read_text('utf-8-sig'))
        responses=envelope.get('responses',[]) if isinstance(envelope,dict) else envelope
        for response in responses if isinstance(responses,list) else []:
            if response.get('provider')!='Crossref' or response.get('http_status',response.get('status'))!=200:continue
            url=response.get('url','');retrieved=response.get('retrieved_at')
            if not url.startswith('https://api.crossref.org/works') or not retrieved:continue
            try:reusable=reusable_at(retrieved)
            except ValueError:continue
            if not reusable:continue
            message=(response.get('response') or {}).get('message',{})
            records=message.get('items',[]) if isinstance(message,dict) and 'items' in message else [message]
            for record in records:
                if isinstance(record,dict) and record.get('DOI'):
                    local_records[record['DOI'].lower()]={'record':record,'url':url,'retrieved_at':retrieved,'source_artifact':response_path.name,'source_sha256':hashlib.sha256(response_path.read_bytes()).hexdigest()}
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
        reuse=local_records.get(doi.lower()) if doi else None
        if reuse:
            record=reuse['record'];record_title=(record.get('title') or [''])[0]
            record_authors=[name(a) for a in record.get('author',[])]
            if norm(record_title)!=norm(node['title']) or [norm(a) for a in record_authors]!=[norm(name(a)) for a in node['authors']]:reuse=None
        if reuse:
            found=reuse['record'];attempts.append({'url':reuse['url'],'retrieved_at':reuse['retrieved_at'],'status':200,'response':{'message':found},'reused_verified_response':True,'request_sent':False,'source_artifact':reuse['source_artifact'],'source_sha256':reuse['source_sha256']})
        else:found=fetch('https://api.crossref.org/works/'+urllib.parse.quote(doi,safe='/')) if doi else None
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
                url=attempts[-1]['url'] if reuse else 'https://api.crossref.org/works/'+urllib.parse.quote(c['DOI'],safe='/')
                return {'node_id':node['id'],'title':node['title'],'citation_count':count,'citation_source':{'url':url,'provider':'Crossref','retrieved_at':attempts[-1]['retrieved_at']},'source_doi':c['DOI'],'source_title':title,'source_authors':authors,'source_year':year,'match_basis':'doi' if same_doi else 'title_author','attempts':attempts,'reused_verified_response':bool(reuse)}
        reason='; '.join(a.get('error') or 'HTTP '+str(a.get('status'))+'，未找到标题、首位作者和年份一致的记录' for a in attempts)
        return {'node_id':node['id'],'title':node['title'],'citation_count':None,'reason':reason or '无可查询DOI，标题身份匹配未通过','attempts':attempts}
    rows=list(ThreadPoolExecutor(max_workers=4).map(audit,graph['nodes']))
    # Citation counts do not imply a complete reference list. Fill only the
    # missing lists through a separate exact DOI source, retaining its footprint.
    from .paper_graph import audit_records
    from .research_public import fetch as public_fetch
    def has_references(node,row):return any(record['references'] for record in audit_records(node,row))
    # A single exact DOI batch gives an independent reference list and the
    # IDs of selected targets. It does not repeat keyword discovery or replace
    # the Crossref citation-count source.
    if any(not has_references(node,row) for node,row in zip(graph['nodes'],rows)) and time.monotonic()<stop:
        identifiers=sorted(set('https://doi.org/'+str(node['doi']).lower() for node in graph['nodes'] if node.get('doi')))
        if identifiers and len(identifiers)<=50:
            url='https://api.openalex.org/works?'+urllib.parse.urlencode({'filter':'doi:'+'|'.join(identifiers),'per_page':len(identifiers),'select':'id,doi,display_name,publication_year,referenced_works'})
            previous=next((item for row in rows for item in row.get('attempts',[]) if item.get('provider')=='OpenAlex' and item.get('url')==url),None)
            openalex=copy.deepcopy(previous) if previous else {**public_fetch(url),'provider':'OpenAlex'}
            for node,row in zip(graph['nodes'],rows):
                if not any(item.get('provider')=='OpenAlex' for item in row.get('attempts',[])):
                    row.setdefault('attempts',[]).append(copy.deepcopy(openalex))
    blocked=None
    for item in responses if isinstance(responses,list) else []:
        if 'semanticscholar.org' in str(item.get('url','')) and item.get('http_status',item.get('status'))==429:
            blocked=item;break
    for node,row in zip(graph['nodes'],rows):
        if has_references(node,row) or not node.get('doi'):continue
        url='https://api.semanticscholar.org/graph/v1/paper/DOI:'+urllib.parse.quote(node['doi'],safe='/')+'?'+urllib.parse.urlencode({'fields':'externalIds,title,year,authors,references.externalIds,references.title,references.year,references.authors'})
        if any('semanticscholar.org' in str(item.get('url','')) for item in row.get('attempts',[])):continue
        if blocked:
            item={'url':url,'provider':'Semantic Scholar','retrieved_at':datetime.now(timezone.utc).isoformat(),'http_status':429,'request_sent':False,'error':'provider_rate_limited_this_run','rate_limit_source_url':blocked.get('url')}
        elif time.monotonic()>=stop:
            item={'url':url,'provider':'Semantic Scholar','retrieved_at':datetime.now(timezone.utc).isoformat(),'request_sent':False,'error':'reference_query_not_started_batch_budget'}
        else:
            item={**public_fetch(url),'provider':'Semantic Scholar'}
            if item.get('http_status')==429:blocked=item
        row.setdefault('attempts',[]).append(item)
    selected={row['node_id'] for row in rows}
    combined=[row for row in prior_rows if row.get('node_id') not in selected]+rows
    output.write_text(json.dumps({'schema_version':1,'provider':'Crossref','retrieved_at':datetime.now(timezone.utc).isoformat(),'rows':combined},ensure_ascii=False,indent=2),encoding='utf-8')
    report={'path':str(output),'known':sum(r['citation_count'] is not None for r in rows),'total':len(rows),'reused':sum(r.get('reused_verified_response') is True for r in rows)}
    if not quiet:print(json.dumps(report,ensure_ascii=True))
    return report

def run(graph,budget_seconds=75,memory=None):
    argv=[str(graph),'--budget-seconds',str(budget_seconds)]
    if memory:argv+=['--memory',str(memory)]
    return main(argv,quiet=True)
if __name__=='__main__':main()
