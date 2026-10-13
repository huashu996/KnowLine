"""Bounded discovery through official public APIs after an authorized Scholar 429.

No authentication, browser cookies, broad web crawling, pagination or retries.
Candidates and reference lists are evidence for review, never a published graph.
"""
import copy
import hashlib
import json
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from .paper_bibliography import stamp
from .safety import atomic_json, contained

MAX_BYTES = 2 * 1024 * 1024
HOSTS = {'api.crossref.org', 'api.semanticscholar.org', 'api.openalex.org', 'api.github.com'}
_lock = threading.Lock()
_provider_locks={host:threading.Lock() for host in HOSTS}
_next_request = {}
_cooldown = {}
_cache = OrderedDict()  # At most four bounded responses; original dates retained.


class PublicRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        original = urllib.parse.urlsplit(req.full_url)
        if (target.scheme != 'https' or target.hostname != original.hostname
                or target.hostname not in HOSTS or target.username or target.password
                or target.port not in {None, 443}):
            raise ValueError('public_api_redirect_blocked')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def retry_after(value):
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            seconds = 60
    return max(60, seconds) if math.isfinite(seconds) else 60


def fetch(url):
    """One serialized request per provider; 429 stops that source, never retries."""
    target = urllib.parse.urlsplit(url)
    host = target.hostname
    if host not in HOSTS or target.scheme != 'https' or target.username or target.password or target.port not in {None, 443}:
        raise ValueError('public_api_source_not_allowed')
    with _provider_locks[host]:
        current = time.monotonic()
        if _cooldown.get(host, 0) > current:
            return {'url': url, 'retrieved_at': stamp(), 'status': 'rate_limited',
                    'http_status': 429, 'request_sent': False,
                    'retry_after_seconds': round(_cooldown[host] - current)}
        with _lock:
            cached = _cache.get(url)
            if cached and current - cached[0] < 300:
                _cache.move_to_end(url)
                return {**copy.deepcopy(cached[1]), 'reused_verified_response': True,
                        'request_sent': False}
        delay = _next_request.get(host, 0) - current
        if delay > 0:
            time.sleep(min(1, delay))
        record = {'url': url, 'retrieved_at': stamp(), 'request_sent': True}
        started = time.monotonic()
        _next_request[host] = started + 1
        try:
            opener = urllib.request.build_opener(PublicRedirects())
            request = urllib.request.Request(url, headers={
                'User-Agent': 'Knowline/1.0 public citation discovery', 'Accept': 'application/json'})
            with opener.open(request, timeout=10) as response:
                raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ValueError('bounded_response_exceeded')
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError('invalid_public_api_response')
                record.update(status='ok', http_status=response.status, response=redact_links(data),
                              stored_urls_without_query=True,
                              response_sha256=hashlib.sha256(raw).hexdigest())
                with _lock:
                    _cache[url] = (time.monotonic(), copy.deepcopy(record))
                    while len(_cache) > 4:
                        _cache.popitem(last=False)
        except urllib.error.HTTPError as exc:
            record.update(status='rate_limited' if exc.code == 429 else 'source_unavailable',
                          http_status=exc.code)
            if exc.code == 429:
                seconds = retry_after(exc.headers.get('Retry-After'))
                _cooldown[host] = time.monotonic() + seconds
                record['retry_after_seconds'] = seconds
            exc.close()
        except Exception as exc:
            record.update(status='source_unavailable', error=type(exc).__name__)
        record['duration_seconds'] = round(time.monotonic() - started, 3)
        return record


def stable_url(value):
    """Only stable public page identifiers, without transient query strings."""
    try:
        url = urllib.parse.urlsplit(str(value or ''))
        if url.scheme not in {'https', 'http'} or not url.hostname or url.username or url.password:
            return ''
        return urllib.parse.urlunsplit(url._replace(query='', fragment=''))
    except ValueError:
        return ''


def redact_links(value):
    # Public records can contain temporary PDF URLs too. Keep metadata/reference
    # evidence while stripping transient URL parameters before saving/model use.
    if isinstance(value, dict):
        return {k: redact_links(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_links(v) for v in value]
    if isinstance(value, str) and value.startswith(('https://', 'http://')):
        return stable_url(value)
    return value


def candidates(provider, record, limit):
    data = record.get('response', {})
    message = data.get('message')
    items = message.get('items', []) if provider == 'Crossref' and isinstance(message, dict) else data.get('data', []) if provider != 'Crossref' else []
    if not isinstance(items, list):
        return []
    rows = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        if provider == 'Crossref':
            titles=item.get('title')
            title = titles[0] if isinstance(titles,list) and titles else ''
            doi = item.get('DOI', '')
            authors = [' '.join(str(a.get(k, '')) for k in ('given', 'family')).strip()
                       for a in (item.get('author') or []) if isinstance(a, dict)]
            published=item.get('published') or {}
            date = published.get('date-parts', [[]]) if isinstance(published,dict) else []
            year = date[0][0] if date and isinstance(date[0],list) and date[0] else None
            venues=item.get('container-title')
            venue = venues[0] if isinstance(venues,list) and venues else ''
            identity = doi
        else:
            title = item.get('title', '')
            doi = (item.get('externalIds') or {}).get('DOI', '')
            authors = [a.get('name', '') for a in (item.get('authors') or []) if isinstance(a, dict)]
            year, venue, identity = item.get('year'), item.get('venue') or '', item.get('paperId', '')
        if not isinstance(title, str) or not title.strip() or not identity:
            continue
        source = {'url': record['url'], 'retrieved_at': record['retrieved_at'], 'provider': provider}
        rows.append({'id': provider.lower().replace(' ', '_') + '_' + hashlib.sha256(str(identity).encode()).hexdigest()[:16],
                     'title': title.strip(), 'doi': str(doi).casefold(), 'authors': authors,
                     'year': year, 'venue': venue, 'paper_url': stable_url(item.get('URL') or item.get('url')),
                     'pdf_url': '', 'source': source, 'source_record_id': identity,
                     'metadata_status': 'unverified', 'abstract_status': 'requires_source_review',
                     'requires_identity_and_topic_review': True})
    return rows


def discover(store, job, scholar):
    started = time.monotonic()
    scope = job['context']['literature_search']
    output = contained(store.project, job['context']['output_dir'])
    quota=job['task']=='discover_papers'
    limit = min(80,scope.get('target_count',10)*8) if quota else min(21, max(1, scope.get('target_count', 10) + 1))
    plan=scope.get('search_plan',{})
    query=plan.get('topic_query',scope['query']) if quota else scope['query']
    crossref={'query.bibliographic':query,'rows':limit}
    if quota:
        crossref['filter']='from-pub-date:'+str(scope['from_year'])+'-01-01,until-pub-date:'+str(scope['to_year'])+'-12-31'
        crossref['select']='DOI,title,author,published,container-title,URL'
        if plan.get('preferred_publisher')=='IEEE':crossref['query.publisher-name']='IEEE'
        if plan.get('preferred_venues'):crossref['query.container-title']=' '.join(plan['preferred_venues'])
    sources = [
        ('Crossref', 'https://api.crossref.org/works?' + urllib.parse.urlencode(crossref)),
        ('Semantic Scholar', 'https://api.semanticscholar.org/graph/v1/paper/search?' + urllib.parse.urlencode({
            'query': query, 'limit': limit, 'fields': 'title,authors,year,venue,externalIds,url,citationCount'}))]
    responses, papers, identities = [], [], set()
    # Independent public APIs can run together; per-provider locks preserve
    # throttling/cooldown while the catalog still has only one writer.
    with ThreadPoolExecutor(max_workers=2) as pool:
        records=list(pool.map(fetch,[url for _,url in sources]))
    for (provider, url), record in zip(sources,records):
        record['provider'] = provider
        responses.append(record)
        for paper in candidates(provider, record, limit):
            # Identical DOI only; a similar title is never a version identity proof.
            identity = ('doi:' + paper['doi']) if paper['doi'] else (provider, paper['source_record_id'])
            if identity not in identities:
                papers.append(paper)
                identities.add(identity)
    if quota:papers=papers[:limit]
    elif plan:
        from .research_query import graph_candidate_rank
        papers=sorted(papers,key=lambda paper:graph_candidate_rank(paper,plan))
    browser_only = scholar.get('status') == 'browser_only'
    reason = ('Automatic discovery uses the authorized official citation APIs; Google Scholar is available through its normal website.'
              if browser_only else 'Google Scholar returned HTTP 429; user-authorized official public citation APIs supplement discovery.')
    status = 'candidates_found' if papers else 'no_results' if all(r['status'] == 'ok' for r in responses) else 'sources_unavailable'
    report = {'provider': 'Public citation APIs', 'status': status, 'papers': papers,
              'retrieved_at': stamp(), 'source_url': responses[0]['url'],
              'expanded_search': not browser_only, 'maximum_requests': 2 if browser_only else 3, 'fallback_reason': reason,
              'discovery_mode': 'official_apis' if browser_only else 'rate_limit_fallback',
              'browser_search_url': scholar.get('browser_search_url',scholar.get('source_url')),
              'scholar': scholar, 'public_sources': [{k: v for k, v in r.items() if k != 'response'} for r in responses],
              'candidate_limit': limit if quota else limit * 2, 'requires_identity_and_topic_review': True,
              'warnings': ([] if browser_only else ['Google 学术本轮返回 429；使用经用户允许的 Crossref / Semantic Scholar 公开接口补充，未重试 Google。']) + [
                           '候选需核对身份与主题；公开数据库的覆盖范围不同，不能混合引用次数或凭搜索结果推断引用边。']}
    report['duration_seconds'] = round(time.monotonic() - started, 3)
    if plan:report['search_plan']=plan
    from .research_query import names, public_response_name
    atomic_json(output / public_response_name(scope), {'responses': responses, 'fallback_reason': reason})
    atomic_json(output / names(scope)['discovery'], report)
    return {k: v for k, v in report.items() if k != 'papers'} | {'candidate_count': len(papers)}


class RepositoryRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        target=urllib.parse.urlsplit(newurl)
        if target.scheme!='https' or target.hostname!='export.arxiv.org' or target.username or target.password or target.port not in {None,443}:raise ValueError('repository_api_redirect_blocked')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def discover_repository(store,job,remaining_requests):
    """One independent official topic lookup, retained and never retried."""
    import xml.etree.ElementTree as ET
    import re
    from .research_acquire import kind
    scope=job['context']['literature_search'];output=contained(store.project,job['context']['output_dir']);file=output/'repository-discovery.json'
    if file.is_file() or remaining_requests<1:return {'status':'exhausted','papers':[],'reason':'bounded_sources_exhausted'}
    topic=kind(job)
    if not topic:return {'status':'exhausted','papers':[],'reason':'unsupported_repository_topic'}
    terms='(ti:"visual SLAM" OR ti:"visual odometry" OR abs:"visual SLAM")' if topic=='visual' else '(ti:"LiDAR SLAM" OR ti:"LiDAR odometry" OR abs:"LiDAR SLAM")'
    query=terms+' AND submittedDate:['+str(scope['from_year'])+'01010000 TO '+str(scope['to_year'])+'12312359]'
    url='https://export.arxiv.org/api/query?'+urllib.parse.urlencode({'search_query':query,'max_results':20,'sortBy':'lastUpdatedDate','sortOrder':'descending'})
    report={'provider':'arXiv','source_url':url,'retrieved_at':stamp(),'status':'reserved','maximum_requests':1,'candidate_limit':20,'papers':[]}
    # Reserve before network so interruptions/429 never cause a repeated query.
    atomic_json(file,report)
    try:
        from . import paper_bibliography as bibliography
        delay=3-(time.monotonic()-bibliography._last.get('arxiv',0))
        if delay>0:time.sleep(delay)
        bibliography._last['arxiv']=time.monotonic()
        opener=urllib.request.build_opener(RepositoryRedirects())
        with opener.open(urllib.request.Request(url,headers={'User-Agent':'Knowline public paper discovery/1.0','Accept':'application/atom+xml'}),timeout=10) as response:
            raw=response.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES:raise ValueError('bounded_response_exceeded')
            report['response_sha256']=hashlib.sha256(raw).hexdigest();root=ET.fromstring(raw)
        report['original_response_xml']=raw.decode('utf-8','replace')
        ns='{http://www.w3.org/2005/Atom}';seen=set()
        for entry in root.findall(ns+'entry')[:20]:
            identifier=entry.findtext(ns+'id','').rsplit('/abs/',1)[-1];match=re.fullmatch(r'(\d{4}\.\d{4,5})v(\d+)',identifier)
            if not match or match[1] in seen:continue
            title=' '.join(entry.findtext(ns+'title','').split());authors=[v.findtext(ns+'name','').strip() for v in entry.findall(ns+'author')]
            if not title or not authors:continue
            seen.add(match[1]);page='https://arxiv.org/abs/'+identifier
            report['papers'].append({'id':'arxiv_'+match[1],'arxiv_id':match[1],'preprint_version':int(match[2]),'title':title,'authors':authors,'doi':entry.findtext('{http://arxiv.org/schemas/atom}doi','').strip().lower().removeprefix('https://doi.org/'),'paper_url':page,'pdf_url':'https://arxiv.org/pdf/'+identifier,'abstract':entry.findtext(ns+'summary',''),'source':{'provider':'arXiv','url':url,'retrieved_at':report['retrieved_at']},'metadata_status':'unverified','requires_identity_and_topic_review':True})
        report['status']='candidates_found' if report['papers'] else 'no_results'
    except urllib.error.HTTPError as exc:report.update(status='rate_limited' if exc.code==429 else 'source_unavailable',http_status=exc.code)
    except Exception as exc:report.update(status='source_unavailable',reason=type(exc).__name__)
    atomic_json(file,report)
    return {k:v for k,v in report.items() if k!='original_response_xml'}


def discover_journals(store,job,remaining_requests):
    """One distinct journal query after closed/failed candidate sources exhaust."""
    scope=job['context']['literature_search'];output=contained(store.project,job['context']['output_dir']);file=output/'journal-discovery.json'
    if file.is_file() or remaining_requests<1:return {'status':'exhausted','papers':[],'reason':'bounded_sources_exhausted'}
    plan=scope.get('search_plan',{});query=plan.get('topic_query',scope['query'])
    params={'query.bibliographic':query,'query.container-title':' '.join(plan.get('preferred_venues') or ['IEEE Robotics']),'rows':20,'select':'DOI,title,author,published,container-title,URL','filter':'type:journal-article,from-pub-date:'+str(scope['from_year'])+'-01-01,until-pub-date:'+str(scope['to_year'])+'-12-31'}
    if plan.get('preferred_publisher')=='IEEE':params['query.publisher-name']='IEEE'
    url='https://api.crossref.org/works?'+urllib.parse.urlencode(params)
    report={'provider':'Crossref journal discovery','source_url':url,'retrieved_at':stamp(),'status':'reserved','maximum_requests':1,'candidate_limit':20,'papers':[]}
    atomic_json(file,report)
    record=fetch(url);report['response']=record;report['papers']=candidates('Crossref',record,20)
    report['status']='candidates_found' if report['papers'] else record['status'] if record['status']!='ok' else 'no_results'
    atomic_json(file,report);return report
