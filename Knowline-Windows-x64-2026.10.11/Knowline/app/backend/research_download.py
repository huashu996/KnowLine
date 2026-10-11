"""Bounded public PDF acquisition, independent of institution login and citations."""
import asyncio,time,urllib.request,urllib.parse,urllib.error,re,uuid,http.cookiejar,ssl
from pathlib import Path
from .institutional_access import safe_url,public_destination,validate_pdf,MAX_PDF,stamp
from .safety import DomainError,digest
from .store import uid


PUBLIC_REPOSITORIES={'hal.science','inria.hal.science','pmc.ncbi.nlm.nih.gov','openaccess.thecvf.com','proceedings.neurips.cc','roboticsproceedings.org','www.roboticsproceedings.org'}
PUBLISHER_HOSTS=({'link.springer.com','link.springernature.com','idp.springer.com'},{'www.mdpi.com','mdpi.com','mdpi-res.com'},{'roboticsproceedings.org','www.roboticsproceedings.org'})


def publisher_hosts(host):
    return next((set(group) for group in PUBLISHER_HOSTS if host in group),{host})


def public_opener(*handlers):
    # Keep certificate/hostname verification enabled. Python's Windows roots
    # can lack a university server's chain; supplement with bundled public CAs.
    import certifi
    context=ssl.create_default_context()
    context.load_verify_locations(certifi.where())
    return urllib.request.build_opener(*handlers,urllib.request.HTTPSHandler(context=context))


def permitted_public_host(host,record):
    from .official_copy import AUTHOR_HOSTS
    formal=urllib.parse.urlsplit((record or {}).get('publisher_url','')).hostname
    bound=any(urllib.parse.urlsplit(b.get('pdf_url','')).hostname==host for b in (record or {}).get('public_copy_bindings',[]))
    return bool(host and (bound or host in {'arxiv.org','export.arxiv.org'}|PUBLIC_REPOSITORIES|AUTHOR_HOSTS or host.endswith('.edu') or re.search(r'\.(?:edu|ac)\.[a-z]{2}$',host) or host in publisher_hosts(formal)))


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
    if response.get('status')!='ok':raise DomainError('public_index_unavailable',502,http_status=response.get('http_status'))
    data=response.get('response',{})
    doi=str(data.get('doi') or '').lower().removeprefix('https://doi.org/')
    authors=[a.get('author',{}).get('display_name','') for a in data.get('authorships',[])]
    if doi!=record['doi'].lower() or bibliography.norm(data.get('title',''))!=bibliography.norm(record['title']) or [bibliography.norm(a) for a in authors]!=[bibliography.norm(a) for a in record['authors']]:raise DomainError('public_index_identity_mismatch')
    sources=[]
    for location in data.get('locations',[])[:30]:
        if not isinstance(location,dict) or location.get('is_oa') is not True:continue
        link=location.get('pdf_url') or location.get('landing_page_url')
        if not link:continue
        try:link=safe_url(link)
        except DomainError:continue
        host=urllib.parse.urlsplit(link).hostname
        if host in {'arxiv.org','export.arxiv.org'}:
            # Verify repository authors, declared DOI and actual version separately.
            found=re.search(r'/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?',link)
            if found:
                return await locate_public(record,identifier=found[1])
            continue
        if not permitted_public_host(host,record):continue
        version={'publishedVersion':'published','acceptedVersion':'accepted_manuscript','submittedVersion':'preprint'}.get(location.get('version'),'unknown')
        sources.append({'publisher_url':record['publisher_url'],'access_url':link,'version_source_url':url,'public_oa':True,'download_permitted':True,'pdf_version':version,'version_basis':'Exact DOI OpenAlex open location: '+str(location.get('version') or 'unknown'),'fallback_reason':'Exact DOI public index located an open copy','pdf_identity':{k:record[k] for k in ('title','authors','doi')}})
    if not sources:raise DomainError('public_index_no_open_pdf')
    evidence={'provider':'OpenAlex exact DOI','source_url':url,'doi':doi,'title':data['title'],'authors':authors,'retrieved_at':response['retrieved_at'],'response_sha256':response.get('response_sha256')}
    updated={**record,'evidence':[*record.get('evidence',[]),evidence],'public_download_sources':list({s['access_url']:s for s in [*record.get('public_download_sources',[]),*sources]}.values())[-3:]}
    return updated,sources[0]


async def locate_index(record):
    """One DOI-specific official public index request for an author/OA copy."""
    from . import research_public,paper_bibliography as bibliography
    if not record or not record.get('latest_verified') or not record.get('doi'):raise DomainError('public_identity_unverified')
    url='https://api.semanticscholar.org/graph/v1/paper/DOI:'+urllib.parse.quote(record['doi'],safe='')+'?fields=title,authors,externalIds,openAccessPdf,url'
    response=await asyncio.to_thread(research_public.fetch,url)
    if response.get('status')!='ok':raise DomainError('public_index_unavailable',502,http_status=response.get('http_status'))
    data=response.get('response',{});identifier=str(data.get('externalIds',{}).get('DOI','')).lower()
    authors=[a.get('name','') for a in data.get('authors',[]) if isinstance(a,dict)]
    if identifier!=record['doi'].lower() or bibliography.norm(data.get('title',''))!=bibliography.norm(record['title']) or [bibliography.norm(a) for a in authors]!=[bibliography.norm(a) for a in record['authors']]:raise DomainError('public_index_identity_mismatch')
    if not (data.get('openAccessPdf') or {}).get('url'):raise DomainError('public_index_no_open_pdf')
    link=safe_url(data['openAccessPdf']['url'])
    host=urllib.parse.urlsplit(link).hostname
    # arXiv must supply its original declared publication relationship/version.
    if host in {'arxiv.org','export.arxiv.org'}:raise DomainError('public_repository_original_record_required')
    if not permitted_public_host(host,record):raise DomainError('public_pdf_source_outside_policy')
    evidence={'provider':'Semantic Scholar exact DOI','source_url':url,'url':link,'title':data['title'],'authors':authors,'doi':identifier,'retrieved_at':response['retrieved_at'],'response_sha256':response.get('response_sha256')}
    source={'publisher_url':record['publisher_url'],'access_url':link,'version_source_url':link,'public_oa':True,'download_permitted':True,'pdf_version':'unknown','version_basis':'Public index locates an open copy; actual file version remains unknown','fallback_reason':'Publisher full text unavailable; exact DOI public index located an open author/repository copy','pdf_identity':{k:record[k] for k in ('title','authors','doi')}}
    return {**record,'evidence':[*record.get('evidence',[]),evidence],'public_download_sources':list({v['access_url']:v for v in [*record.get('public_download_sources',[]),source]}.values())[-3:]},source


async def locate_public(record,identifier=None):
    """One official arXiv query for this verified paper, never topic discovery."""
    import xml.etree.ElementTree as ET
    from . import paper_bibliography as bibliography
    if not record or not record.get('latest_verified'):raise DomainError('public_identity_unverified')
    known=[v[6:] for v in record.get('related_identifiers',[]) if v.startswith('arxiv:')]
    if record.get('arxiv_id'):known.append(record['arxiv_id'])
    requested_identifier=identifier
    if known or identifier:
        query='id_list='+urllib.parse.quote(known[0] if known else identifier,safe='')
    else:
        # A full final subtitle may differ from the preprint; sorting just the
        # title by recency also hides an older original behind newer extensions.
        # Search the exact title's distinctive prefix plus its first author,
        # then require the declared DOI or full-title/all-author bridge below.
        title=str(record['title']).split(':',1)[0].replace('"',' ').replace('\\',' ')
        author=str(record['authors'][0]).split()[-1].replace('"',' ').replace('\\',' ')
        expression='ti:"'+title+'" AND au:"'+author+'"'
        query='search_query='+urllib.parse.quote(expression,safe='')+'&max_results=5&sortBy=lastUpdatedDate&sortOrder=descending'
    url='https://export.arxiv.org/api/query?'+query
    try:root=ET.fromstring(await asyncio.wait_for(bibliography.fetch(url),20))
    except asyncio.TimeoutError:raise DomainError('public_locator_timeout')
    except ET.ParseError:raise DomainError('public_locator_invalid_response')
    ns='{http://www.w3.org/2005/Atom}';matches=[]
    for entry in root.findall(ns+'entry')[:5]:
        entry_identifier=entry.findtext(ns+'id','').rsplit('/abs/',1)[-1]
        version=re.fullmatch(r'(\d{4}\.\d{4,5})v(\d+)',entry_identifier)
        if not version:continue
        title=' '.join(entry.findtext(ns+'title','').split())
        authors=[n.findtext(ns+'name','').strip() for n in entry.findall(ns+'author')]
        actual_doi=entry.findtext('{http://arxiv.org/schemas/atom}doi','').strip().lower().removeprefix('https://doi.org/')
        if known and version[1]!=known[0]:continue
        if requested_identifier and version[1]!=requested_identifier:continue
        if actual_doi and actual_doi!=record.get('doi','').lower():continue
        exact_title=bibliography.norm(title)==bibliography.norm(record.get('title',''))
        declared=(bool(record.get('doi')) and actual_doi==record['doi'].lower()) or 'arxiv:'+version[1] in record.get('related_identifiers',[]) or record.get('arxiv_id')==version[1] or (not actual_doi and exact_title and record.get('metadata_status')=='verified' and record.get('doi'))
        if not declared or [bibliography.norm(a) for a in authors]!=[bibliography.norm(a) for a in record.get('authors',[])]:continue
        matches.append((version[1],entry_identifier,title,authors,actual_doi))
    if not matches:raise DomainError('public_repository_no_identity_match')
    if len(matches)!=1:raise DomainError('public_repository_identity_ambiguous')
    key,versioned,title,authors,actual_doi=matches[0];origin='https://arxiv.org/abs/'+versioned
    relationship='repository_declared_doi' if actual_doi else 'existing_verified_identifier_link' if key in known else 'exact_title_all_authors_unique_repository_record'
    evidence={'provider':'arXiv','source_url':url,'url':origin,'identity_key':'arxiv:'+key,'title':title,'authors':authors,'arxiv_id':key,'preprint_version':int(re.search(r'v(\d+)$',versioned)[1]),'formal_doi':actual_doi,'retrieved_at':stamp(),'relationship':relationship}
    updated={**record,'related_identifiers':list(dict.fromkeys([*record.get('related_identifiers',[]),'arxiv:'+key])),'evidence':[*record.get('evidence',[]),evidence]}
    source={'publisher_url':origin,'access_url':'https://arxiv.org/pdf/'+versioned,'version_source_url':origin,'public_oa':True,'download_permitted':True,'pdf_version':'preprint','version_basis':'Official arXiv latest entry identifies preprint '+versioned,'fallback_reason':'Publisher full text unavailable; official repository located the same verified paper','pdf_identity':{'title':title,'authors':authors,'arxiv_id':key}}
    return updated,source


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
    if source.get('public_oa') is not True or not permitted_public_host(host,record):raise DomainError('public_pdf_source_outside_policy')
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
                head=response.read(65536)
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
                        chunk=response.read(65536)
                        if not chunk:break
                        size+=len(chunk)
                        if size>MAX_PDF:raise DomainError('public_pdf_size_limit')
                        file.write(chunk)
                break
        identity=dict(identity)
        identity.pop('publisher_pdf_url',None)
        identity.pop('official_pdf_url',None)
        if any(b.get('pdf_url')==access for b in (record or {}).get('public_copy_bindings',[])):identity['official_pdf_url']=access
        from .institutional_access import rss_pdf_url
        if access==rss_pdf_url((record or node).get('doi')):identity['publisher_pdf_url']=access
        target={**(record or node),'pdf_identity':identity,'pdf_version':source.get('pdf_version','unknown'),**({'citation_record':record} if record else {})}
        validate_pdf(path,target)
        # Watch/scan excludes .kw-* files. Promote only inside the verified
        # single-writer registration transaction, including after cancellation.
        sha=digest(path);final=store.root/('.kw-verified-'+sha[:20]+'-'+uuid.uuid4().hex[:8]+'.pdf')
        if final.exists():path.unlink()
        else:path.replace(final)
        repository=host in {'arxiv.org','export.arxiv.org'}|PUBLIC_REPOSITORIES or university and host!=urllib.parse.urlsplit((record or {}).get('publisher_url','')).hostname
        return final,{'publisher_url':publisher,'access_url':access,'access_method':'public_repository' if repository else 'public_publisher','pdf_version':source.get('pdf_version','unknown'),'pdf_version_basis':{'statement':source.get('version_basis','Actual file version is unknown'),'url':safe_url(source.get('version_source_url') or publisher),'retrieved_at':stamp()},'fallback_reason':source.get('fallback_reason',''),'pdf_identity':identity,'acquired_at':stamp()}
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
