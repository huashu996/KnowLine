"""Official automatic citation discovery and a separate normal Scholar web link."""
import json,time,hashlib,urllib.request,urllib.parse,urllib.error,re
from html.parser import HTMLParser
from .safety import atomic_json,contained
from .paper_bibliography import stamp


class ScholarResults(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.stack=[];self.row=None;self.rows=[];self.challenge=False
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs);classes=set(attrs.get('class','').split())
        if tag=='div' and 'gs_r' in classes and self.row is None:self.row={'title':'','byline':'','snippet':'','paper_url':'','pdf_url':''};self.root=len(self.stack)
        self.stack.append((tag,classes))
        if self.row and tag=='a':
            url=attrs.get('href','')
            if any('gs_rt' in c for _,c in self.stack):self.row['paper_url']=url
            elif any('gs_or_ggsm' in c for _,c in self.stack):self.row['pdf_url']=url
        if attrs.get('id') in {'gs_captcha_ccl','captcha-form'} or attrs.get('name') in {'g-recaptcha-response'}:self.challenge=True
        if tag in {'meta','link','input','img','br','hr','wbr'}:self.stack.pop()
    def handle_endtag(self,tag):
        found=next((i for i in range(len(self.stack)-1,-1,-1) if self.stack[i][0]==tag),None)
        if found is None:return
        if self.row is not None and found==self.root:
            self.rows.append({k:' '.join(v.split()) for k,v in self.row.items()});self.row=None
        self.stack=self.stack[:found]
    def handle_data(self,data):
        if not self.row:return
        classes=set().union(*(c for _,c in self.stack))
        field='title' if 'gs_rt' in classes else 'byline' if 'gs_a' in classes else 'snippet' if 'gs_rs' in classes else None
        if field:self.row[field]+=data


def discover(store,job,page=0):
    start=time.monotonic();scope=job['context']['literature_search'];output=contained(store.project,job['context']['output_dir'],False);output.mkdir(parents=True,exist_ok=True)
    from .research_query import names
    files=names(scope);search_plan=scope.get('search_plan',{})
    if page:
        files={'scholar':'scholar-candidates-page-'+str(page)+'.json','discovery':'discovery-page-'+str(page)+'.json'}
    connected=None
    if job['task']=='paper_relationships' and scope.get('connected_papers_url'):
        from .connected_papers import collect
        connected=collect(store,job)
        evidence='connected-papers-'+connected.get('response_sha256',hashlib.sha256(json.dumps(connected,sort_keys=True).encode()).hexdigest())[:16]+'.json'
        atomic_json(output/evidence,connected)
        if connected['status'] in {'candidates_found','access_challenge','redirect_scope_blocked'}:
            atomic_json(output/files['scholar'],{'provider':'Google Scholar','status':'not_requested','papers':[],'reason':'Using user-supplied Connected Papers graph' if connected['status']=='candidates_found' else 'Human access required for supplied graph'})
            atomic_json(output/files['discovery'],connected)
            return {k:v for k,v in connected.items() if k!='papers'}|{'candidate_count':len(connected['papers']),'evidence_path':(output/evidence).relative_to(store.project).as_posix()}
    page_size=20 if job['task']=='discover_papers' else min(20,scope.get('target_count',10)+1)
    params={'q':search_plan.get('scholar_query',scope['query']),'num':page_size,'hl':'en'}
    if page:params['start']=page*page_size
    if job['task']=='discover_papers':params.update(as_ylo=scope['from_year'],as_yhi=scope['to_year'])
    url='https://scholar.google.com/scholar?'+urllib.parse.urlencode(params)
    # Scholar explicitly disallows automated /scholar queries. A browser link
    # is a human search option, never an API or a way around a 429/challenge.
    report={'provider':'Google Scholar','source_url':url,'retrieved_at':stamp(),'papers':[],
            'status':'browser_only','expanded_search':False,'maximum_requests':0,
            'request_sent':False,'browser_search_url':url,
            'reason':'automated_search_not_supported',
            'policy_url':'https://scholar.google.com/intl/en/scholar/help.html'}
    if connected:
        report['connected_papers_status']=connected['status']
        report['warnings']=['User-supplied Connected Papers graph could not be read ('+connected['status']+'); retained source status and the frozen browser search link.']
    if search_plan:report['search_plan']=search_plan
    report['duration_seconds']=round(time.monotonic()-start,3)
    atomic_json(output/files['scholar'],report)
    summary={k:v for k,v in report.items() if k!='papers'}|{'candidate_count':len(report['papers'])}
    from .research_policy import public_fallback_allowed
    if not page and public_fallback_allowed(job):
        from .research_public import discover as supplement
        combined=supplement(store,job,summary)
        combined['duration_seconds']=round(time.monotonic()-start,3)
        atomic_json(output/files['discovery'],{**json.loads((output/files['discovery']).read_text('utf-8')), 'duration_seconds':combined['duration_seconds']})
        return combined
    atomic_json(output/files['discovery'],report)
    return summary


def more(store,job):
    """Finite additional pages for a successful-fulltext quota; never retry a page."""
    from .research_policy import acquisition_limits
    from .safety import DomainError
    if job['task']!='discover_papers' or job['status'] not in {'running','waiting_user'} or not str(job['context'].get('external_network','')).startswith('user_requested'):raise DomainError('scope_violation',409)
    from .research_query import supplemental_name
    scope=job['context']['literature_search']
    output=contained(store.project,job['context']['output_dir']);state_file=output/supplemental_name(scope,'discovery-refill-state')
    state=json.loads(state_file.read_text('utf-8')) if state_file.is_file() else {'pages':[],'stopped':False}
    def repository_more(reason):
        from .research_policy import public_fallback_allowed
        if not public_fallback_allowed(job) or reason=='access_challenge':return {'status':'exhausted','papers':[],'reason':reason}
        from .research_query import public_response_name
        public_file=output/public_response_name(job['context']['literature_search'])
        public_count=len(json.loads(public_file.read_text('utf-8')).get('responses',[])) if public_file.is_file() else 0
        remaining=acquisition_limits(job)['maximum_discovery_requests']-1-len(state['pages'])-public_count
        from .research_public import discover_repository,discover_journals
        repository=discover_repository(store,job,remaining)
        if repository.get('papers'):return repository
        if (output/supplemental_name(scope,'repository-discovery')).is_file():remaining-=1
        return discover_journals(store,job,remaining)
    if state['stopped']:return repository_more(state.get('reason','bounded_sources_exhausted'))
    from .research_query import names
    scope=job['context']['literature_search'];initial=output/names(scope)['scholar']
    first=json.loads(initial.read_text('utf-8')) if initial.is_file() else {}
    if first.get('status') not in {None,'candidates_found'}:
        state.update(stopped=True,reason=first.get('status'));atomic_json(state_file,state)
        return repository_more(state['reason'])
    page=len(state['pages'])+1
    if page>=acquisition_limits(job)['maximum_discovery_requests']:
        state.update(stopped=True,reason='bounded_sources_exhausted');atomic_json(state_file,state)
        return repository_more(state['reason'])
    # Reserve before the network call; interrupted/failed pages are never retried.
    state['pages'].append(page);atomic_json(state_file,state)
    report=discover(store,job,page)
    data=json.loads((output/('scholar-candidates-page-'+str(page)+'.json')).read_text('utf-8'))
    if report['status']!='candidates_found':
        state.update(stopped=True,reason=report['status']);atomic_json(state_file,state)
        return repository_more(state['reason'])
    prior=[*first.get('papers',[])]
    for n in state['pages'][:-1]:
        path=output/('scholar-candidates-page-'+str(n)+'.json')
        if path.is_file():prior.extend(json.loads(path.read_text('utf-8')).get('papers',[]))
    seen={p['id'] for p in prior};papers=[p for p in data.get('papers',[]) if p['id'] not in seen]
    return {**report,'papers':papers,'page':page,'remaining_requests':max(0,acquisition_limits(job)['maximum_discovery_requests']-page-1)}
