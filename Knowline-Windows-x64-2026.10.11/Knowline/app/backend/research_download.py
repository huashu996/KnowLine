"""Bounded public PDF acquisition, independent of institution login and citations."""
import asyncio,time,urllib.request,urllib.parse,urllib.error,re,uuid,http.cookiejar,ssl,gzip
from pathlib import Path
from .institutional_access import safe_url,public_destination,validate_pdf,MAX_PDF,stamp
from .safety import DomainError,digest
from .store import uid


PUBLIC_REPOSITORIES={'hal.science','inria.hal.science','pmc.ncbi.nlm.nih.gov','openaccess.thecvf.com','proceedings.neurips.cc','roboticsproceedings.org','www.roboticsproceedings.org'}
PUBLISHER_HOSTS=({'link.springer.com','link.springernature.com','idp.springer.com'},{'www.mdpi.com','mdpi.com','mdpi-res.com'},{'roboticsproceedings.org','www.roboticsproceedings.org'})


def _arxiv_parts(value):
    """Canonical base ID plus a real supplied version; never invent a version."""
    value=str(value or '').strip()
    value=re.sub(r'^arxiv:', '', value, flags=re.I)
    match=re.fullmatch(r'(\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7})(?:v([1-9]\d*))?',value,re.I)
    if not match:return None
    key=match[1]
    if '/' in key:
        category,number=key.split('/',1)
        parts=category.split('.',1)
        key=parts[0].lower()+('.'+parts[1].upper() if len(parts)>1 else '')+'/'+number
    return key,int(match[2]) if match[2] else None


def repository_arxiv_id(url):
    """An arXiv page/PDF or registered arXiv DOI is an ID hint, not a PDF."""
    try:
        parsed=urllib.parse.urlsplit(str(url or ''))
        if (parsed.scheme not in {'https','http'} or parsed.username or parsed.password
                or parsed.port not in {None,80,443}):return None
        path=urllib.parse.unquote(parsed.path)
        if parsed.hostname in {'arxiv.org','www.arxiv.org','export.arxiv.org'}:
            match=re.fullmatch(r'/(?:abs|pdf)/(.+?)(?:\.pdf)?',path,re.I)
            value=match[1] if match else ''
        elif parsed.hostname in {'doi.org','dx.doi.org'}:
            match=re.fullmatch(r'/10\.48550/arxiv\.(.+)',path,re.I)
            value=match[1] if match else ''
        else:return None
        parts=_arxiv_parts(value)
        return parts[0] if parts else None
    except (TypeError,ValueError):return None


def _arxiv_key(value):
    parts=_arxiv_parts(value)
    return parts[0] if parts else repository_arxiv_id(value)


def publisher_hosts(host):
    return next((set(group) for group in PUBLISHER_HOSTS if host in group),{host})


def public_opener(*handlers):
    # Keep certificate/hostname verification enabled. Python's Windows roots
    # can lack a university server's chain; supplement with bundled public CAs.
    import certifi
    context=ssl.create_default_context()
    context.load_verify_locations(certifi.where())
    return urllib.request.build_opener(*handlers,urllib.request.HTTPSHandler(context=context))


def permitted_public_host(host,record,url=None):
    from .official_copy import AUTHOR_HOSTS,AUTHOR_REPOS
    if host in {'github.com','raw.githubusercontent.com'}:
        parts=urllib.parse.urlsplit(url or '').path.strip('/').split('/')
        from .official_copy import repository_allowed
        scoped=any(b.get('pdf_url')==url and b.get('doi')==(record or {}).get('doi')
                   and b.get('match_basis') in {'exact_doi_index_location_candidate_only','registered_doi_pdf_link_candidate_only'}
                   for b in (record or {}).get('public_copy_bindings',[]))
        return scoped or len(parts)>=2 and repository_allowed(tuple(parts[:2]),record)
    formal=urllib.parse.urlsplit((record or {}).get('publisher_url','')).hostname
    bound=any(urllib.parse.urlsplit(b.get('pdf_url','')).hostname==host for b in (record or {}).get('public_copy_bindings',[]))
    return bool(host and (bound or host in {'arxiv.org','export.arxiv.org'}|PUBLIC_REPOSITORIES|AUTHOR_HOSTS or host.endswith('.edu') or re.search(r'\.(?:edu|ac)\.[a-z]{2}$',host) or host in publisher_hosts(formal)))


def author_name_matches(left,right):
    """Initials may expand only with the same surname and ordered given names.

    This is supporting evidence under an explicit DOI, never a title bridge.
    """
    import unicodedata
    def parts(value):
        value=''.join(c for c in unicodedata.normalize('NFKD',str(value)) if not unicodedata.combining(c))
        return re.findall(r'[^\W\d_]+',value.lower())
    a,b=parts(left),parts(right)
    return bool(a and b and a[-1]==b[-1] and len(a)==len(b) and all(
        x==y or min(len(x),len(y))==1 and x[0]==y[0] for x,y in zip(a[:-1],b[:-1])))


def bind_index_location(record,link,provider,url,response):
    """An exact DOI/title/all-author index response supplies a scoped URL hint.

    This permits that public source; it never supplies a PDF identifier proof.
    Actual file identity remains mandatory, including for unfamiliar domains.
    """
    return {'doi':record['doi'],'title':record['title'],'authors':record['authors'],
            'pdf_url':link,'source_url':url,'provider':provider,
            'retrieved_at':response['retrieved_at'],'response_sha256':response.get('response_sha256'),
            'match_basis':'exact_doi_index_location_candidate_only'}


async def locate_proceedings(record):
    """The registered RSS DOI identifies an exact official openly published PDF."""
    from .institutional_access import rss_pdf_url
    if not record or not record.get('latest_verified'):raise DomainError('public_identity_unverified')
    url=rss_pdf_url(record.get('doi'))
    if not url:raise DomainError('public_publisher_not_supported')
    identity={**{k:record[k] for k in ('title','authors','doi')},'publisher_pdf_url':url}
    source={'publisher_url':url.removesuffix('.pdf')+'.html','access_url':url,'public_oa':True,'download_permitted':True,'pdf_version':'unknown','version_basis':'Official RSS proceedings PDF; actual document version remains unknown','fallback_reason':'Exact registered conference DOI identifies the official public proceedings paper','pdf_identity':identity}
    return {**record,'public_download_sources':[source,*record.get('public_download_sources',[])][:3]},source


async def locate_openalex(record):
    """Resolve an exact DOI's openly available locations, without topic search."""
    from . import research_public,paper_bibliography as bibliography
    if not record or not record.get('latest_verified') or not record.get('doi'):raise DomainError('public_identity_unverified')
    url='https://api.openalex.org/works/https://doi.org/'+urllib.parse.quote(record['doi'],safe='')
    response=await asyncio.to_thread(research_public.fetch,url)
    if response.get('status')!='ok':raise DomainError('public_index_no_record' if response.get('http_status')==404 else 'public_index_unavailable',502,provider='OpenAlex',http_status=response.get('http_status'),source_status=response.get('status'),retry_after_seconds=response.get('retry_after_seconds'))
    data=response.get('response',{})
    doi=str(data.get('doi') or '').lower().removeprefix('https://doi.org/')
    authors=[a.get('author',{}).get('display_name','') for a in data.get('authorships',[])]
    if doi!=record['doi'].lower() or bibliography.norm(data.get('title',''))!=bibliography.norm(record['title']) or len(authors)!=len(record['authors']) or not all(author_name_matches(a,b) for a,b in zip(authors,record['authors'])):raise DomainError('public_index_identity_mismatch')
    sources=[];bindings=[];repository_failures=[];repository_source=None;repository_record=None;repository_ids=set()
    for location in data.get('locations',[])[:30]:
        if len(sources)>=3:break
        if not isinstance(location,dict) or location.get('is_oa') is not True:continue
        link=location.get('pdf_url') or location.get('landing_page_url')
        if not link:continue
        try:
            from .official_copy import canonical_link
            link=safe_url(canonical_link(link))
        except DomainError:continue
        host=urllib.parse.urlsplit(link).hostname
        repository_id=repository_arxiv_id(link)
        if repository_id or host in {'arxiv.org','www.arxiv.org','export.arxiv.org'}:
            # Verify repository authors, declared DOI and actual version separately.
            if repository_id and repository_id not in repository_ids and len(repository_ids)<3:
                repository_ids.add(repository_id)
                try:
                    repository_record,repository_source=await locate_public(record,identifier=repository_id)
                except (DomainError,OSError,ValueError,asyncio.TimeoutError) as exc:
                    repository_failures.append(str(getattr(exc,'code','repository_source_unavailable')))
                # One unavailable repository must not hide the other OA copies.
            continue
        binding=bind_index_location(record,link,'OpenAlex exact DOI',url,response)
        bound={**record,'public_copy_bindings':[*record.get('public_copy_bindings',[]),binding]}
        if not permitted_public_host(host,bound,link):continue
        bindings.append(binding)
        version={'publishedVersion':'published','acceptedVersion':'accepted_manuscript','submittedVersion':'preprint'}.get(location.get('version'),'unknown')
        sources.append({'publisher_url':record['publisher_url'],'access_url':link,'version_source_url':url,'public_oa':True,'open_access_verified':True,'open_access_basis':'OpenAlex exact DOI location.is_oa','download_permitted':True,'pdf_version':version,'version_basis':'Exact DOI OpenAlex open location: '+str(location.get('version') or 'unknown'),'fallback_reason':'Exact DOI public index located an open copy','pdf_identity':{k:record[k] for k in ('title','authors','doi')}})
    if repository_source:sources.append(repository_source)
    if not sources:raise DomainError('public_index_no_open_pdf',502,repository_failures=repository_failures)
    evidence={'provider':'OpenAlex exact DOI','source_url':url,'doi':doi,'title':data['title'],'authors':authors,'retrieved_at':response['retrieved_at'],'response_sha256':response.get('response_sha256')}
    base=repository_record or record
    updated={**base,'public_copy_bindings':[*base.get('public_copy_bindings',[]),*bindings][-10:],
             'evidence':[*base.get('evidence',[]),evidence],'public_download_sources':list({s['access_url']:s for s in [*sources,*base.get('public_download_sources',[])]}.values())[:3]}
    if repository_failures:updated['public_location_failures']=repository_failures[:3]
    return updated,sources[0]


async def locate_index(record):
    """One DOI-specific official public index request for an author/OA copy."""
    from . import research_public,paper_bibliography as bibliography
    if not record or not record.get('latest_verified') or not record.get('doi'):raise DomainError('public_identity_unverified')
    url='https://api.semanticscholar.org/graph/v1/paper/DOI:'+urllib.parse.quote(record['doi'],safe='')+'?fields=title,authors,externalIds,openAccessPdf,url'
    response=await asyncio.to_thread(research_public.fetch,url)
    if response.get('status')!='ok':raise DomainError('public_index_no_record' if response.get('http_status')==404 else 'public_index_unavailable',502,provider='Semantic Scholar',http_status=response.get('http_status'),source_status=response.get('status'),retry_after_seconds=response.get('retry_after_seconds'))
    data=response.get('response',{});identifier=str(data.get('externalIds',{}).get('DOI','')).lower()
    authors=[a.get('name','') for a in data.get('authors',[]) if isinstance(a,dict)]
    if identifier!=record['doi'].lower() or bibliography.norm(data.get('title',''))!=bibliography.norm(record['title']) or len(authors)!=len(record['authors']) or not all(author_name_matches(a,b) for a,b in zip(authors,record['authors'])):raise DomainError('public_index_identity_mismatch')
    if not (data.get('openAccessPdf') or {}).get('url'):raise DomainError('public_index_no_open_pdf')
    from .official_copy import canonical_link
    link=safe_url(canonical_link(data['openAccessPdf']['url']))
    host=urllib.parse.urlsplit(link).hostname
    # arXiv must supply its original declared publication relationship/version.
    repository_id=repository_arxiv_id(link)
    if repository_id or host in {'arxiv.org','www.arxiv.org','export.arxiv.org'}:
        if not repository_id:raise DomainError('public_repository_original_record_required')
        updated,source=await locate_public(record,identifier=repository_id)
        evidence={'provider':'Semantic Scholar exact DOI','source_url':url,'url':link,
                  'doi':identifier,'title':data['title'],'authors':authors,
                  'retrieved_at':response['retrieved_at'],'response_sha256':response.get('response_sha256'),
                  'relationship':'repository_identifier_hint_original_record_verified'}
        return {**updated,'evidence':[*updated.get('evidence',[]),evidence]},source
    binding=bind_index_location(record,link,'Semantic Scholar exact DOI',url,response)
    record={**record,'public_copy_bindings':[*record.get('public_copy_bindings',[]),binding][-10:]}
    if not permitted_public_host(host,record,link):raise DomainError('public_pdf_source_outside_policy')
    evidence={'provider':'Semantic Scholar exact DOI','source_url':url,'url':link,'title':data['title'],'authors':authors,'doi':identifier,'retrieved_at':response['retrieved_at'],'response_sha256':response.get('response_sha256')}
    source={'publisher_url':record['publisher_url'],'access_url':link,'version_source_url':link,'public_oa':True,'open_access_verified':True,'open_access_basis':'Semantic Scholar exact DOI openAccessPdf','download_permitted':True,'pdf_version':'unknown','version_basis':'Public index locates an open copy; actual file version remains unknown','fallback_reason':'Publisher full text unavailable; exact DOI public index located an open author/repository copy','pdf_identity':{k:record[k] for k in ('title','authors','doi')}}
    return {**record,'evidence':[*record.get('evidence',[]),evidence],'public_download_sources':list({v['access_url']:v for v in [*record.get('public_download_sources',[]),source]}.values())[-3:]},source


async def locate_public(record,identifier=None):
    """One official arXiv query for this verified paper, never topic discovery."""
    import xml.etree.ElementTree as ET
    from . import paper_bibliography as bibliography
    if not record or not record.get('latest_verified'):raise DomainError('public_identity_unverified')
    known=list(dict.fromkeys(k for k in [_arxiv_key(v[6:]) for v in record.get('related_identifiers',[]) if v.startswith('arxiv:')]
                            +[_arxiv_key(record.get('arxiv_id'))] if k))
    explicit=_arxiv_key(identifier) if identifier is not None else None
    if identifier is not None and not explicit:raise DomainError('citation_identifier_required')
    requested_identifier=explicit or (known[0] if known else None)
    if requested_identifier:
        query='id_list='+urllib.parse.quote(requested_identifier,safe='')
    else:
        # A full final subtitle may differ from the preprint; sorting just the
        # title by recency also hides an older original behind newer extensions.
        # Search the exact title's distinctive prefix plus its first author,
        # then require the declared DOI or full-title/all-author bridge below.
        from html import unescape
        title=re.sub(r'\s*<(?:sup|sub)>\s*(.*?)\s*</(?:sup|sub)>\s*',r'\1',str(record['title']),flags=re.S)
        title=unescape(re.sub(r'<[^>]+>','',title)).split(':',1)[0]
        title=' '.join(title.split()).replace('"',' ').replace('\\',' ')
        author=str(record['authors'][0]).split()[-1].replace('"',' ').replace('\\',' ')
        expression='ti:"'+title+'" AND au:"'+author+'"'
        query='search_query='+urllib.parse.quote(expression,safe='')+'&max_results=5&sortBy=lastUpdatedDate&sortOrder=descending'
    url='https://export.arxiv.org/api/query?'+query
    try:
        root=ET.fromstring(await asyncio.wait_for(bibliography.fetch(url),20))
        if any('/api/errors' in e.findtext('{http://www.w3.org/2005/Atom}id','') for e in root.findall('{http://www.w3.org/2005/Atom}entry')):
            raise DomainError('public_locator_invalid_response',request_sent=True,url=url)
    except (DomainError,OSError,ValueError,asyncio.TimeoutError,ET.ParseError) as exc:
        if isinstance(exc,asyncio.TimeoutError):failure=DomainError('public_locator_timeout',request_sent=True,url=url)
        elif isinstance(exc,ET.ParseError):failure=DomainError('public_locator_invalid_response',request_sent=True,url=url)
        elif isinstance(exc,DomainError):failure=exc
        else:failure=DomainError('citation_source_unavailable',502,reason='network_error',request_sent=True,url=url)
        # A known original page is an independent bounded route. A 429 remains
        # a stop condition, never a cue to work around the source's limit.
        if requested_identifier and failure.code in {'citation_source_unavailable','public_locator_timeout','public_locator_invalid_response'} and failure.params.get('http_status')!=429:
            return await _locate_arxiv_page(record,requested_identifier,known,url,failure)
        raise failure
    return _arxiv_feed_record(record,root,url,known,requested_identifier)


def _arxiv_feed_record(record,root,url,known,requested_identifier):
    """One identity gate for original Atom entries and original-page metadata."""
    from . import paper_bibliography as bibliography
    ns='{http://www.w3.org/2005/Atom}';matches=[];candidates=[]
    for entry in root.findall(ns+'entry')[:5]:
        entry_identifier=entry.findtext(ns+'id','').rsplit('/abs/',1)[-1]
        version=_arxiv_parts(entry_identifier)
        if not version or not version[1]:continue
        key,number=version;versioned=key+'v'+str(number)
        title=' '.join(entry.findtext(ns+'title','').split())
        authors=[n.findtext(ns+'name','').strip() for n in entry.findall(ns+'author')]
        actual_doi=entry.findtext('{http://arxiv.org/schemas/atom}doi','').strip().lower().removeprefix('https://doi.org/')
        if requested_identifier and key!=requested_identifier:continue
        if actual_doi and actual_doi!=record.get('doi','').lower():continue
        exact_title=bibliography.norm(title)==bibliography.norm(record.get('title',''))
        declared=(bool(record.get('doi')) and actual_doi==record['doi'].lower()) or key in known or (not actual_doi and exact_title and record.get('metadata_status')=='verified' and record.get('doi'))
        actual_authors=[bibliography.norm(a) for a in authors]
        formal_authors=[bibliography.norm(a) for a in record.get('authors',[])]
        same_authors=actual_authors==formal_authors
        author_matches=sum(any(author_name_matches(a,b) for b in record.get('authors',[])) for a in authors)
        overlap=bool(authors and record.get('authors') and author_name_matches(authors[0],record['authors'][0])
                     and author_matches>=max(1,len(authors)*.75))
        # A primary repository's explicit DOI supports author-list changes;
        # a similar title alone never creates a publication/version bridge.
        explicit_doi=bool(actual_doi and actual_doi==record.get('doi','').lower())
        if not declared or not (same_authors or explicit_doi and overlap):
            from difflib import SequenceMatcher
            title_similarity=SequenceMatcher(None,bibliography.norm(title.split(':',1)[-1]),bibliography.norm(record.get('title','').split(':',1)[-1])).ratio()
            if overlap and (exact_title or title_similarity>=.72 or explicit_doi):
                candidates.append({'url':'https://arxiv.org/abs/'+versioned,'title':title,'authors':authors,
                                   'arxiv_id':key,'reason':'publication_version_link_unverified','pdf_version':'preprint'})
            continue
        matches.append((key,versioned,title,authors,actual_doi))
    api=urllib.parse.urlsplit(url).hostname=='export.arxiv.org' and urllib.parse.urlsplit(url).path=='/api/query'
    def trace(status,reason=None):
        return {'provider':'arXiv API' if api else 'arXiv original abstract page',
                'url':url,'status':status,'request_sent':True,**({'http_status':200} if api else {}),
                **({'reason':reason} if reason else {})}
    if not matches:
        code='public_repository_candidate_needs_review' if candidates else 'public_repository_no_identity_match'
        raise DomainError(code,candidates=candidates[:3],source_attempts=[trace('no_match',code)])
    if len(matches)!=1:raise DomainError('public_repository_identity_ambiguous',source_attempts=[trace('unavailable','public_repository_identity_ambiguous')])
    key,versioned,title,authors,actual_doi=matches[0];origin='https://arxiv.org/abs/'+versioned
    relationship='repository_declared_doi' if actual_doi else 'existing_verified_identifier_link' if key in known else 'exact_title_all_authors_unique_repository_record'
    evidence={'provider':'arXiv','source_url':url,'url':origin,'identity_key':'arxiv:'+key,'title':title,'authors':authors,'arxiv_id':key,'preprint_version':int(re.search(r'v(\d+)$',versioned)[1]),'formal_doi':actual_doi,'retrieved_at':stamp(),'relationship':relationship}
    updated={**record,'related_identifiers':list(dict.fromkeys([*record.get('related_identifiers',[]),'arxiv:'+key])),'evidence':[*record.get('evidence',[]),evidence],
             'public_location_attempts':[*record.get('public_location_attempts',[]),trace('located')][-8:]}
    source={'publisher_url':origin,'access_url':'https://arxiv.org/pdf/'+versioned,'version_source_url':origin,'public_oa':True,'download_permitted':True,'pdf_version':'preprint','version_basis':'Official arXiv latest entry identifies preprint '+versioned,'fallback_reason':'Official arXiv repository located the same verified paper','pdf_identity':{'title':title,'authors':authors,'arxiv_id':key}}
    return updated,source


async def _locate_arxiv_page(record,key,known,api_url,failure):
    """Read one known original abstract page, then apply the Atom identity gate."""
    import xml.etree.ElementTree as ET
    from html import unescape
    from html.parser import HTMLParser
    from .official_copy import fetch_page
    page='https://arxiv.org/abs/'+key
    api_attempt={'provider':'arXiv API','url':api_url,'status':'unavailable','reason':failure.code,
                 'request_sent':failure.params.get('request_sent',True),
                 **{k:failure.params[k] for k in ('http_status','retry_after_seconds') if k in failure.params}}
    try:
        response=await asyncio.wait_for(asyncio.to_thread(fetch_page,page),15)
        if repository_arxiv_id(response.get('url'))!=key:raise DomainError('public_repository_original_record_required')
        class Metadata(HTMLParser):
            def __init__(self):super().__init__();self.values={};self.history_depth=0;self.depth=0;self.history=[];self.history_links=[]
            def handle_starttag(self,tag,attrs):
                values=dict(attrs)
                if tag not in {'meta','link','br','img','hr','input','source','wbr'}:self.depth+=1
                if tag=='meta':
                    name=str(values.get('name','')).lower()
                    if name and values.get('content'):self.values.setdefault(name,[]).append(unescape(values['content']).strip())
                if 'submission-history' in str(values.get('class','')).split():self.history_depth=self.depth
                if self.history_depth and values.get('href'):
                    self.history_links.append(urllib.parse.urljoin(page,unescape(values['href'])))
            def handle_endtag(self,tag):
                if self.depth==self.history_depth:self.history_depth=0
                if tag not in {'meta','link','br','img','hr','input','source','wbr'}:self.depth=max(0,self.depth-1)
            def handle_data(self,data):
                if self.history_depth:self.history.append(data)
        parsed=Metadata();parsed.feed(response['html'])
        ids=parsed.values.get('citation_arxiv_id',[])
        if not ids or any(_arxiv_key(value)!=key for value in ids):raise DomainError('public_repository_original_record_required')
        versions=[parts[1] for value in ids if (parts:=_arxiv_parts(value)) and parts[1]]
        if len(set(versions))>1:raise DomainError('public_repository_version_unverified')
        if not versions:
            for value in parsed.values.get('citation_pdf_url',[]):
                value=urllib.parse.urljoin(page,value)
                if repository_arxiv_id(value)!=key:continue
                candidate=urllib.parse.unquote(urllib.parse.urlsplit(value).path).rsplit('/pdf/',1)[-1].rsplit('/abs/',1)[-1].removesuffix('.pdf')
                parts=_arxiv_parts(candidate)
                if parts and parts[1]:versions.append(parts[1])
            if len(set(versions))>1:raise DomainError('public_repository_version_unverified')
        if not versions:
            for value in parsed.history_links:
                if repository_arxiv_id(value)!=key:continue
                candidate=urllib.parse.unquote(urllib.parse.urlsplit(value).path).rsplit('/pdf/',1)[-1].rsplit('/abs/',1)[-1].removesuffix('.pdf')
                parts=_arxiv_parts(candidate)
                if parts and parts[1]:versions.append(parts[1])
            versions.extend(int(v) for v in re.findall(r'\[v([1-9]\d*)\]',' '.join(parsed.history)))
        if not versions:raise DomainError('public_repository_version_unverified')
        title=(parsed.values.get('citation_title') or [''])[0]
        authors=parsed.values.get('citation_author',[])
        if not title or not authors:raise DomainError('public_repository_original_record_required')
        declared_doi=(parsed.values.get('citation_doi') or [''])[0].strip().lower().removeprefix('https://doi.org/').removeprefix('doi:')
        if declared_doi.startswith('10.48550/arxiv.'):
            if repository_arxiv_id('https://doi.org/'+declared_doi)!=key:raise DomainError('public_repository_original_record_required')
            declared_doi=''
        ns='{http://www.w3.org/2005/Atom}'
        root=ET.Element(ns+'feed');entry=ET.SubElement(root,ns+'entry')
        ET.SubElement(entry,ns+'id').text=page+'v'+str(max(versions))
        ET.SubElement(entry,ns+'title').text=title
        for author in authors:ET.SubElement(ET.SubElement(entry,ns+'author'),ns+'name').text=author
        if declared_doi:ET.SubElement(entry,'{http://arxiv.org/schemas/atom}doi').text=declared_doi
        updated,source=_arxiv_feed_record(record,root,page,known,key)
        updated['evidence'][-1].update(response_sha256=response.get('response_sha256'),retrieved_at=response['retrieved_at'],
                                      source_kind='original_arxiv_abstract_metadata')
        updated['public_location_attempts']=[*record.get('public_location_attempts',[]),api_attempt,
            {'provider':'arXiv original abstract page','url':page,'status':'located','request_sent':True}][-8:]
        return updated,source
    except (DomainError,OSError,ValueError,asyncio.TimeoutError) as exc:
        code=getattr(exc,'code','public_locator_timeout' if isinstance(exc,asyncio.TimeoutError) else 'public_locator_unavailable')
        params=dict(getattr(exc,'params',{}))
        params.update(request_sent=True,source_attempts=[api_attempt,
            {'provider':'arXiv original abstract page','url':page,'status':'unavailable','reason':code,'request_sent':True}])
        raise DomainError(code,502,**params) from exc


class GuardedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self,hosts,public_copy=False):self.hosts=hosts;self.public_copy=public_copy
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not public_destination(newurl,self.hosts,allow_translated=True,public_copy=self.public_copy):raise DomainError('public_pdf_redirect_outside_source')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def fetch_pdf(store,node,record,source,seconds):
    from .institutional_access import normalized_pdf_identity
    identity=normalized_pdf_identity({**(record or node),'pdf_identity':source.get('pdf_identity')})
    access=safe_url(source.get('access_url') or source.get('publisher_url'),public_copy=True)
    publisher=safe_url(source['publisher_url']);host=urllib.parse.urlsplit(access).hostname
    university=bool(host.endswith('.edu') or re.search(r'\.(?:edu|ac)\.[a-z]{2}$',host))
    from .sci_hub import valid_source
    sci_hub_source=source.get('source_provider')=='Sci-Hub' and valid_source(source,record)
    if (source.get('public_oa') is not True and not sci_hub_source) or not permitted_public_host(host,record,access):raise DomainError('public_pdf_source_outside_policy')
    hosts=publisher_hosts(host) if host in publisher_hosts(urllib.parse.urlsplit((record or {}).get('publisher_url','')).hostname) else {host}
    if host in {'arxiv.org','export.arxiv.org'}:
        hosts|={'arxiv.org','export.arxiv.org'}
        if '/abs/' in access:access=access.replace('/abs/','/pdf/')
    legacy=urllib.parse.urlsplit(access).scheme=='http'
    if legacy:
        from .official_copy import binding_valid
        if not record:raise DomainError('official_source_proof_required')
        identity={**identity,'official_pdf_url':access}
        if not any(binding_valid(b,identity,record,store.root/'.kw-public-request.pdf') for b in record.get('public_copy_bindings',[])):raise DomainError('official_source_proof_required')
    if not public_destination(access,hosts,allow_translated=True,public_copy=legacy):raise DomainError('public_pdf_destination_unsafe')
    # Publisher OA may initialize an anonymous first-party session (Springer
    # redirects via its own idp). Keep cookies in this transfer's memory only;
    # never load, persist, or export the user's institution/browser credentials.
    stop=time.monotonic()+max(1,min(30,seconds));opener=public_opener(GuardedRedirect(hosts,public_copy=legacy),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    path=store.root/('.kw-public-'+uuid.uuid4().hex+'.pdf');size=0
    try:
        # One landing page and one same-source PDF link, no broad crawling.
        for attempt in range(2):
            with opener.open(urllib.request.Request(access,headers={'User-Agent':'Knowline public paper acquisition/1.0','Accept':'application/pdf,text/html'}),timeout=min(10,max(1,stop-time.monotonic()))) as response:
                headers=getattr(response,'headers',{})
                stream=gzip.GzipFile(fileobj=response) if str(headers.get('Content-Encoding','')).lower()=='gzip' else response
                head=stream.read(65536)
                if b'%PDF-' not in head[:1024]:
                    if attempt:raise DomainError('public_pdf_not_found')
                    html=head.decode('utf-8','replace')
                    if re.search(r'captcha|unusual traffic|cf-challenge|password',html,re.I):raise DomainError('public_pdf_requires_user')
                    from html.parser import HTMLParser
                    class PdfMeta(HTMLParser):
                        url=None
                        def handle_starttag(self,tag,attrs):
                            values=dict(attrs)
                            if tag=='meta' and str(values.get('name','')).lower()=='citation_pdf_url':self.url=values.get('content')
                    parser=PdfMeta();parser.feed(html)
                    if not parser.url:raise DomainError('public_pdf_not_found')
                    from html import unescape
                    access=safe_url(urllib.parse.urljoin(response.url,unescape(parser.url)))
                    if not public_destination(access,hosts,allow_translated=True):raise DomainError('public_pdf_redirect_outside_source')
                    continue
                with path.open('wb') as file:
                    file.write(head);size=len(head)
                    while True:
                        if time.monotonic()>=stop:raise DomainError('public_pdf_budget_reached')
                        chunk=stream.read(65536)
                        if not chunk:break
                        size+=len(chunk)
                        if size>MAX_PDF:raise DomainError('public_pdf_size_limit')
                        file.write(chunk)
                break
        identity=dict(identity)
        identity.pop('publisher_pdf_url',None)
        identity.pop('official_pdf_url',None)
        # A third-party repository page cannot prove publisher/file identity.
        # Its candidate must carry the independently verified DOI in the PDF.
        if not sci_hub_source and any(b.get('pdf_url')==access for b in (record or {}).get('public_copy_bindings',[])):identity['official_pdf_url']=access
        from .institutional_access import rss_pdf_url
        if access==rss_pdf_url((record or node).get('doi')):identity['publisher_pdf_url']=access
        target={**(record or node),'pdf_identity':identity,'pdf_version':source.get('pdf_version','unknown'),**({'citation_record':record} if record else {})}
        validate_pdf(path,target)
        # Watch/scan excludes .kw-* files. Promote only inside the verified
        # single-writer registration transaction, including after cancellation.
        sha=digest(path);final=store.root/('.kw-verified-'+sha[:20]+'-'+uuid.uuid4().hex[:8]+'.pdf')
        if final.exists():path.unlink()
        else:path.replace(final)
        from .official_copy import AUTHOR_HOSTS
        repository=(sci_hub_source or host in {'arxiv.org','export.arxiv.org','github.com','raw.githubusercontent.com'}|PUBLIC_REPOSITORIES|AUTHOR_HOSTS
                    or university and host!=urllib.parse.urlsplit((record or {}).get('publisher_url','')).hostname)
        return final,{'publisher_url':publisher,'access_url':access,'access_method':'public_repository' if repository else 'public_publisher','pdf_version':source.get('pdf_version','unknown'),'pdf_version_basis':{'statement':source.get('version_basis','Actual file version is unknown'),'url':safe_url(source.get('version_source_url') or publisher),'retrieved_at':stamp()},'fallback_reason':source.get('fallback_reason',''),'pdf_identity':identity,'acquired_at':stamp(),**({'source_provider':'Sci-Hub','open_access_verified':False} if sci_hub_source else {})}
    except urllib.error.HTTPError as exc:raise DomainError('public_pdf_http_'+str(exc.code))
    finally:
        if path.is_file():path.unlink()


async def acquire(store,node,record,source,write,domain,seconds=25):
    from . import paper_bibliography as bibliography
    def verified():
        if not record or record.get('metadata_status')!='verified' or record.get('formal_record_status')=='source_unavailable' or record.get('formal_doi_unverified') or not record.get('latest_verified') or not bibliography.fresh(record.get('latest_checked_at')) or any(not record.get(k) for k in ('title','authors','year','venue','source_type')):raise DomainError('public_citation_verification_required',409)
    verified()
    path,metadata=await asyncio.to_thread(fetch_pdf,store,node,record,source,seconds)
    def register():
        verified()
        from .safety import filename
        source_hash=digest(path)
        final=store.root/filename(record.get('year'),record['title'],record.get('venue'),source_hash,store.root,store.config['ui_locale'])
        base=final;counter=2
        while final.exists() and digest(final)!=source_hash:
            final=base.with_name(base.stem+'-'+str(counter)+base.suffix);counter+=1
        promoted=not final.exists()
        if promoted:path.replace(final)
        try:
            imported=store.import_local({'path':final.relative_to(store.project).as_posix()});resource=imported['resource']
            additions={k:v for k,v in metadata.items() if not resource['metadata'].get(k)}
            if additions:
                resource=store.update_resource(resource['id'],{'base_revision':resource['revision'],**additions})['resource']
            resource=bibliography.attach(store,record,resource['id'],metadata['pdf_identity'])
            if resource['metadata'].get('metadata_status')!='verified':raise DomainError('public_citation_verification_required',409)
            if domain:
                group=next(g for g in store.groups() if g['id']==domain)
                if resource['id'] not in group['resource_ids']:store.group_members(domain,{'base_revision':group['revision'],'resource_ids':group['resource_ids']+[resource['id']]})
            # Hash deduplication may reuse an original stored at another path.
            # Remove only this operation's promoted download, so later scans
            # cannot register an extra copy; existing originals stay intact.
            if promoted and imported['duplicate'] and resource['path']!=final.relative_to(store.project).as_posix():final.replace(path)
            return {'status':'imported','resource_id':resource['id'],'version_id':resource['version_id'],'sha256':resource['sha256'],'acquisition':metadata,'new_download':True,'new_registration':not imported['duplicate'],'duplicate':imported['duplicate']}
        except Exception:
            if promoted and final.is_file():final.replace(path)
            raise
    try:return await write('direct_public_pdf',{'operation_id':uid('op')},register)
    finally:
        # This operation owns only this scan-excluded temporary download.
        if path.is_file():path.unlink()
