"""Verify an explicitly located official author/repository copy, never discover topics."""
import asyncio,hashlib,json,re,urllib.parse,urllib.request,gzip,io,zlib
from pathlib import Path
from html.parser import HTMLParser
from html import unescape
from .institutional_access import safe_url,public_destination,stamp,LEGACY_PUBLIC_PDFS
from .safety import DomainError,atomic_json,digest

# Exact official hosts checked against their university/author project pages.
AUTHOR_HOSTS={'cvg.cit.tum.de','vision.in.tum.de','rpg.ifi.uzh.ch',
              'www.research-collection.ethz.ch','www.ipb.uni-bonn.de',
              'webdiis.unizar.es','doriangalvez.com','jacqueskaiser.com',
              'gisbi-kim.github.io'}
AUTHOR_REPOS={('RobustFieldAutonomyLab','LeGO-LOAM'),('PRBonn','puma'),
              ('gaoxiang12','faster-lio'),('hku-mars','Swarm-LIO2'),('hku-mars','r3live')}
PUBLIC_ALIASES={'http://doriangalvez.com/php/dl.php?dlp=GalvezTRO12.pdf':'http://doriangalvez.com/papers/GalvezTRO12.pdf'}
# Discovery hints only. These URLs confer no identity/version proof: the page
# must still link a PDF and the downloaded document must pass validate_pdf.
AUTHOR_PAGES={
    '10.1109/lra.2022.3152830':'https://github.com/gaoxiang12/faster-lio',
    '10.1109/tro.2024.3522155':'https://github.com/hku-mars/Swarm-LIO2',
}


def repository_allowed(repository,record):
    """Static author hints or a repository bound to this exact paper."""
    from .paper_bibliography import norm
    return repository in AUTHOR_REPOS or any(
        tuple(b.get('repository',[]))==repository and b.get('doi')==record.get('doi')
        and norm(b.get('title',''))==norm(record.get('title',''))
        and b.get('authors')==record.get('authors')
        and b.get('match_basis')=='exact_paper_repository_page'
        for b in (record or {}).get('repository_bindings',[]))


async def locate_github(record):
    """One exact-paper repository search and at most three candidate pages.

    Search results supply hints only; page and actual PDF identity remain
    separate checks. No account, code search, cloning or topic expansion.
    """
    from . import research_public,paper_bibliography as bibliography
    from .research_download import locate_public,repository_arxiv_id
    if not record or not record.get('latest_verified'):raise DomainError('public_identity_unverified')
    title=unescape(re.sub(r'<[^>]+>','',record['title'])).split(':',1)[0].strip()
    query='"'+title.replace('"',' ')+'" in:readme fork:false'
    url='https://api.github.com/search/repositories?'+urllib.parse.urlencode({'q':query,'per_page':3})
    response=await asyncio.to_thread(research_public.fetch,url)
    search_trace={'provider':'GitHub search','url':url,'request_sent':response.get('request_sent',True),
                  **{k:response[k] for k in ('http_status','retry_after_seconds') if k in response}}
    if response.get('status')!='ok':raise DomainError('github_search_unavailable',502,
        provider='GitHub',http_status=response.get('http_status'),source_status=response.get('status'),
        request_sent=response.get('request_sent'),retry_after_seconds=response.get('retry_after_seconds'),
        source_attempts=[{**search_trace,'status':'cooldown' if response.get('status')=='rate_limited' else 'unavailable','reason':'github_search_unavailable'}])
    failures=[];candidates=[];repository_ids=set()
    for item in response.get('response',{}).get('items',[])[:3]:
        name=item.get('full_name','')
        if item.get('fork') or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',name):continue
        page='https://github.com/'+name
        try:content=await asyncio.to_thread(fetch_page,page)
        except (DomainError,OSError,ValueError) as exc:failures.append(getattr(exc,'code','github_page_unavailable'));continue
        if bibliography.norm(record['title']) not in bibliography.norm(content['text']):continue
        declared=record.get('doi','').lower() in content['html'].lower()
        author_text=bibliography.norm(content['text'])
        authors=record.get('authors',[])
        author_match=bool(authors) and all(bibliography.norm(a.split()[-1]) in author_text for a in authors)
        if not declared and not author_match:
            if any(repository_arxiv_id(v) or re.search(r'\.pdf(?:$|[?#])',v,re.I) for v in content['original_links']):
                candidates.append({'url':page,'title':record['title'],'reason':'github_paper_identity_unverified'})
            continue
        binding={'repository':name.split('/'),'doi':record.get('doi'),'title':record['title'],'authors':authors,
                 'source_url':page,'search_url':url,'retrieved_at':content['retrieved_at'],
                 'response_sha256':content['response_sha256'],'match_basis':'exact_paper_repository_page'}
        updated={**record,'repository_bindings':[*record.get('repository_bindings',[]),binding][-6:]}
        sources=[]
        pdf_links=[v for v in dict.fromkeys(content['original_links']) if repository_arxiv_id(v) or re.search(r'\.pdf(?:$|[?#])',v,re.I)][:6]
        for link in pdf_links:
            if len(sources)>=3:break
            parsed=urllib.parse.urlsplit(link)
            repository_id=repository_arxiv_id(link)
            if repository_id or parsed.hostname in {'arxiv.org','www.arxiv.org','export.arxiv.org'}:
                if repository_id and repository_id not in repository_ids and len(repository_ids)<3:
                    repository_ids.add(repository_id)
                    try:
                        updated,source=await locate_public(updated,identifier=repository_id);sources.append(source)
                    except (DomainError,OSError,ValueError,asyncio.TimeoutError) as exc:failures.append(getattr(exc,'code','public_locator_unavailable'))
                continue
            link=canonical_link(link)
            if not urllib.parse.urlsplit(link).path.lower().endswith('.pdf'):continue
            if not approved_url(link,updated):continue
            source,_=await verify(updated,{'pdf_url':link})
            source.update(publisher_url=page,version_source_url=page,
                          fallback_reason='Exact-paper GitHub page linked this candidate; downloaded PDF must independently match its identifier, title and authors')
            sources.append(source)
        if sources:
            updated['evidence']=[*updated.get('evidence',[]),{'provider':'GitHub exact paper repository',**binding}]
            updated['public_download_sources']=list({s['access_url']:s for s in [*sources,*updated.get('public_download_sources',[])]}.values())[:3]
            updated['public_location_attempts']=[*updated.get('public_location_attempts',[]),{**search_trace,'status':'located'}][-8:]
            return updated,sources[0]
    reason='github_source_unavailable' if failures else 'github_no_verified_pdf'
    raise DomainError(reason,failures=failures[:3],candidates=candidates[:3],request_sent=search_trace['request_sent'],
        source_attempts=[{**search_trace,'status':'unavailable' if failures else 'no_match','reason':reason}])


async def locate_publisher(record):
    """Locate a PDF on a publisher page already verified as open access."""
    from .paper_bibliography import norm
    if not record or not record.get('latest_verified') or not record.get('doi'):raise DomainError('public_identity_unverified')
    from .research_policy import known_open_access
    if not known_open_access(record):raise DomainError('publisher_open_access_not_verified')
    response=await asyncio.to_thread(fetch_page,record['publisher_url'],True)
    page=response['url'];host=urllib.parse.urlsplit(page).hostname
    class PdfMetadata(HTMLParser):
        def __init__(self):super().__init__();self.links=[];self.doi=''
        def handle_starttag(self,tag,attrs):
            v=dict(attrs)
            name=str(v.get('name','')).lower()
            if tag=='meta' and name=='citation_pdf_url' and v.get('content'):
                self.links.append(urllib.parse.urljoin(page,unescape(v['content'])))
            if tag=='meta' and name in {'citation_doi','dc.identifier','dc.identifier.doi'} and v.get('content'):
                value=unescape(v['content']).strip().lower().removeprefix('https://doi.org/').removeprefix('doi:')
                if value.startswith('10.'):self.doi=value
    parser=PdfMetadata();parser.feed(response['html'])
    if parser.doi and parser.doi!=record['doi'].lower():raise DomainError('publisher_page_identity_conflict')
    links=[*parser.links,*[v for v in response['links'] if re.search(r'(?:\.pdf|/_pdf)(?:$|[?#])',v,re.I)]]
    sources=[];bindings=[];proofs=[]
    for link in dict.fromkeys(links):
        if len(sources)>=3:break
        try:link=safe_url(link)
        except DomainError:continue
        target=urllib.parse.urlsplit(link).hostname
        # First-party publisher PDF/CDN only; unrelated outbound links are hints.
        suffix='.'.join(host.split('.')[-2:])
        from .research_download import publisher_hosts
        if target!=host and not target.endswith('.'+suffix) and target not in publisher_hosts(host):continue
        source={'publisher_url':page,'access_url':link,'version_source_url':page,
                        'public_oa':True,'open_access_verified':True,'open_access_basis':'Verified record OA plus official article PDF link','download_permitted':True,'pdf_version':'unknown',
                        'version_basis':'Official article page links this PDF; actual file version remains unknown',
                        'fallback_reason':'Registered official article page linked this candidate; downloaded identifier, title and authors still require verification',
                        'pdf_identity':{k:record[k] for k in ('title','authors','doi')}}
        if parser.doi==record['doi'].lower() and link in parser.links:
            binding={'pdf_url':link,'source_url':page,'doi':record['doi'],'title':record['title'],'authors':record['authors'],
                     'declared_pdf_url':link,'match_basis':'publisher_metadata_declared_doi',
                     'retrieved_at':response['retrieved_at'],'response_sha256':response['response_sha256']}
            source['pdf_identity']['official_pdf_url']=link
            proofs.append({'source':source,'proof':{'binding':binding,'source_response':response,'formal_response':None}})
        else:
            # This permits the exact first-party host, never substitutes for
            # the identifier inside the PDF when page metadata is incomplete.
            bindings.append({'pdf_url':link,'source_url':page,'doi':record['doi'],'title':record['title'],
                             'authors':record['authors'],'match_basis':'publisher_candidate_link_only',
                             'retrieved_at':response['retrieved_at'],'response_sha256':response['response_sha256']})
        sources.append(source)
    if not sources:raise DomainError('publisher_page_no_public_pdf')
    return {**record,'publisher_url':page,'pending_public_source_proofs':proofs,
            'public_copy_bindings':[*record.get('public_copy_bindings',[]),*bindings][-10:],
            'evidence':[*record.get('evidence',[]),{'provider':'Official publisher article page','url':page,
                        'retrieved_at':response['retrieved_at'],'response_sha256':response['response_sha256'],
                        'doi':record['doi'],'identity_basis':'publisher_metadata_declared_doi' if parser.doi else 'registered_article_url_candidate_only'}],
            'public_download_sources':list({s['access_url']:s for s in [*sources,*record.get('public_download_sources',[])]}.values())[:3]},sources[0]


async def discover(record):
    """At most two already-associated official pages; never topic crawling."""
    from .paper_bibliography import norm
    if not record or not record.get('latest_verified'):raise DomainError('public_identity_unverified')
    known=AUTHOR_PAGES.get(str(record.get('doi','')).lower())
    pages=[known] if known else []
    for item in record.get('evidence',[]):
        if not isinstance(item,dict):continue
        for key in ('url','source_url'):
            url=item.get(key)
            if not url:continue
            try:url=safe_url(url)
            except (DomainError,ValueError):continue
            if approved_url(url,record) and urllib.parse.urlsplit(url).hostname not in {'arxiv.org','export.arxiv.org',urllib.parse.urlsplit(record.get('publisher_url','')).hostname}:
                pages.append(url)
    pages=list(dict.fromkeys(pages))[:2]
    if not pages:raise DomainError('official_source_not_located')
    sources=[];evidence=[];failures=[]
    for page in pages:
        try:response=await asyncio.to_thread(fetch_page,page)
        except (DomainError,OSError,ValueError) as exc:
            failures.append(str(getattr(exc,'code','official_source_unavailable')));continue
        if page!=known and norm(record['title']) not in norm(response['text']):continue
        for link in dict.fromkeys(response['links']):
            if len(sources)>=3:break
            if not urllib.parse.urlsplit(link).path.lower().endswith('.pdf'):continue
            try:link=safe_url(link,public_copy=True)
            except (DomainError,ValueError):continue
            if not approved_url(link,record):continue
            source,_=await verify(record,{'pdf_url':link})
            source.update(publisher_url=page,version_source_url=page,
                          fallback_reason='Official author page linked this candidate; downloaded PDF identity must still match the formal record')
            sources.append(source)
        evidence.append({'provider':'Official author page','url':page,'retrieved_at':response['retrieved_at'],
                         'response_sha256':response['response_sha256'],'relationship':'candidate_links_only'})
    if not sources:raise DomainError('official_source_unavailable' if failures else 'official_source_no_pdf',failures=failures)
    updated={**record,'evidence':[*record.get('evidence',[]),*evidence],
             'public_download_sources':list({s['access_url']:s for s in [*sources,*record.get('public_download_sources',[])]}.values())[:3]}
    return updated,sources[0]


def approved_url(url,record):
    from .research_download import permitted_public_host
    parsed=urllib.parse.urlsplit(url)
    if parsed.hostname in {'github.com','raw.githubusercontent.com'}:
        pieces=parsed.path.strip('/').split('/')
        return len(pieces)>=2 and repository_allowed(tuple(pieces[:2]),record)
    return parsed.hostname in AUTHOR_HOSTS or permitted_public_host(parsed.hostname,record,url)


def canonical_link(url):
    if url in PUBLIC_ALIASES:return PUBLIC_ALIASES[url]
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme=='http' and url not in LEGACY_PUBLIC_PDFS:parsed=parsed._replace(scheme='https')
    if parsed.hostname=='github.com':
        parts=parsed.path.strip('/').split('/')
        if len(parts)>=5 and parts[2]=='blob':
            parsed=parsed._replace(netloc='raw.githubusercontent.com',path='/'+ '/'.join([*parts[:2],*parts[3:]]))
    return parsed.geturl()


class PublisherRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        target=urllib.parse.urlsplit(newurl)
        if target.scheme=='http':
            newurl=target._replace(scheme='https').geturl();target=urllib.parse.urlsplit(newurl)
        if target.scheme!='https' or not public_destination(newurl,{target.hostname},allow_translated=True):raise DomainError('public_pdf_destination_unsafe')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


async def resolve_publisher_url(record):
    """Resolve a verified DOI's real article route before choosing an account."""
    if urllib.parse.urlsplit(record.get('publisher_url','')).hostname!='doi.org':return record
    from .research_download import public_opener
    original=record['publisher_url']
    if not public_destination(original,{'doi.org'},allow_translated=True):raise DomainError('public_pdf_destination_unsafe')
    def resolve():
        opener=public_opener(PublisherRedirect())
        try:
            with opener.open(urllib.request.Request(original,method='HEAD',headers={'User-Agent':'Knowline DOI publisher routing/1.0'}),timeout=10) as response:target=response.url
        except urllib.error.HTTPError as exc:
            target=exc.url;status=exc.code;exc.close()
            if status not in {401,403,405} or urllib.parse.urlsplit(target).hostname=='doi.org':raise DomainError('publisher_route_http_'+str(status))
        target=safe_url(target)
        if urllib.parse.urlsplit(target).hostname=='doi.org':return record
        return {**record,'publisher_url':target,'evidence':[*record.get('evidence',[]),
            {'provider':'DOI publisher route','source_url':original,'url':target,'doi':record['doi'],'retrieved_at':stamp()}]}
    return await asyncio.to_thread(resolve)


def fetch_page(url,resolve_doi=False):
    from .research_download import GuardedRedirect,public_opener
    host=urllib.parse.urlsplit(url).hostname
    if not public_destination(url,{host},allow_translated=True):raise DomainError('public_pdf_destination_unsafe')
    opener=public_opener(PublisherRedirect() if resolve_doi and host=='doi.org' else GuardedRedirect({host}))
    with opener.open(urllib.request.Request(url,headers={'User-Agent':'Knowline official paper source verification/1.0','Accept-Encoding':'gzip, deflate'}),timeout=10) as response:
        http_status=getattr(response,'status',None)
        content=response.read(2*1024*1024+1)
        if len(content)>2*1024*1024:raise DomainError('official_source_page_size_limit')
        response_hash=hashlib.sha256(content).hexdigest()
        headers=getattr(response,'headers',{})
        encoding=str(headers.get('Content-Encoding','')).lower()
        if encoding=='gzip' or content.startswith(b'\x1f\x8b'):
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(content)) as decoded:content=decoded.read(2*1024*1024+1)
            except (OSError,EOFError):raise DomainError('official_source_invalid_encoding')
        elif encoding=='deflate':
            try:content=zlib.decompressobj().decompress(content,2*1024*1024+1)
            except zlib.error:raise DomainError('official_source_invalid_encoding')
        if len(content)>2*1024*1024:raise DomainError('official_source_page_size_limit')
        charset=headers.get_content_charset() if hasattr(headers,'get_content_charset') else None
        try:html=content.decode(charset or 'utf-8','replace')
        except LookupError:raise DomainError('official_source_invalid_encoding')
        class Page(HTMLParser):
            def __init__(self):super().__init__();self.links=[];self.original_links=[];self.text=[];self.hidden=0
            def handle_starttag(self,tag,attrs):
                values=dict(attrs)
                if tag in {'script','style'}:self.hidden+=1
                if values.get('href'):
                    original=urllib.parse.urljoin(response.url,unescape(values['href']))
                    self.original_links.append(original);self.links.append(canonical_link(original))
            def handle_endtag(self,tag):
                if tag in {'script','style'}:self.hidden=max(0,self.hidden-1)
            def handle_data(self,data):
                if not self.hidden:self.text.append(data)
        page=Page();page.feed(html)
        visible=' '.join(page.text)
        # Public GitHub pages mention captcha in hidden login scripts. Only
        # a visible challenge or an actual challenge form stops this source.
        if (re.search(r'checking your browser|unusual traffic|verify (?:that )?you are human|complete (?:the )?captcha|enable javascript and cookies',visible,re.I)
                or re.search(r'<form\b[^>]*\bid\s*=\s*[\"\']challenge-form[\"\']',html,re.I)):
            raise DomainError('public_pdf_requires_user')
        return {'url':response.url,'http_status':http_status,'retrieved_at':stamp(),'response_sha256':response_hash,
                'html':html,'text':visible,'links':page.links,'original_links':page.original_links}


async def verify(record,hint):
    from . import paper_bibliography as bibliography
    if not record or not record.get('latest_verified') or record.get('metadata_status')!='verified':raise DomainError('public_identity_unverified')
    if not isinstance(hint,dict) or set(hint)-{'page_url','pdf_url'}:raise DomainError('invalid_request')
    try:pdf=safe_url(hint['pdf_url'],public_copy=True);page=safe_url(hint['page_url']) if hint.get('page_url') else None
    except (KeyError,TypeError):raise DomainError('invalid_request')
    if not approved_url(pdf,record) or page and not approved_url(page,record):raise DomainError('public_pdf_source_outside_policy')
    identity={k:record[k] for k in ('title','authors','doi')}
    source={'publisher_url':page or record['publisher_url'],'access_url':pdf,'public_oa':True,'download_permitted':True,
            'pdf_version':'unknown','version_basis':'Located official public copy; actual file version remains unknown',
            'fallback_reason':'Explicitly located official author/university copy for this selected paper','pdf_identity':identity}
    if not page:
        if pdf in LEGACY_PUBLIC_PDFS:raise DomainError('official_source_proof_required')
        # A direct hint supplies no publication bridge. The actual PDF must
        # carry its verified DOI (or the independently verified arXiv ID).
        return source,None
    response=await asyncio.to_thread(fetch_page,page)
    if pdf not in response['links'] or bibliography.norm(record['title']) not in bibliography.norm(response['text']):raise DomainError('official_source_link_identity_mismatch')
    declared=record['doi'].lower() in response['html'].lower()
    match_basis='official_page_declared_doi'
    verification=None
    if not declared:
        # As for the original arXiv bridge: an exact full title and every
        # author must identify one unique formal DOI in the primary registry.
        url='https://api.crossref.org/works?'+urllib.parse.urlencode({'query.title':record['title'],'rows':5})
        verification=json.loads(await bibliography.fetch(url))
        exact=[w for w in verification.get('message',{}).get('items',[])[:5]
               if w.get('type') in bibliography.FORMAL and bibliography.norm((w.get('title') or [''])[0])==bibliography.norm(record['title'])
               and [bibliography.norm(a) for a in bibliography.people(w.get('author',[]))]==[bibliography.norm(a) for a in record['authors']]]
        if {str(w.get('DOI','')).lower() for w in exact}!={record['doi'].lower()}:raise DomainError('official_copy_publication_ambiguous')
        match_basis='official_link_exact_title_all_authors_unique_formal_doi'
    identity['official_pdf_url']=pdf
    source['pdf_identity']=identity
    binding={'doi':record['doi'],'title':record['title'],'authors':record['authors'],'pdf_url':pdf,'source_url':page,
             'declared_pdf_url':next((v for v in response.get('original_links',response['links']) if canonical_link(v)==pdf),pdf),
             'retrieved_at':response['retrieved_at'],'response_sha256':response['response_sha256'],'match_basis':match_basis}
    proof={'binding':binding,'source_response':response,'formal_response':verification}
    return source,proof


def save(store,record,source,proof,domain=None):
    """Called inside the existing cancellation-guarded single-writer mutation."""
    from . import paper_bibliography as bibliography
    bindings=list(record.get('public_copy_bindings',[]))
    if proof:
        raw=json.dumps(proof,ensure_ascii=False,sort_keys=True).encode('utf-8')
        path=store.state/'metadata-sources'/('official-copy-'+hashlib.sha256(raw).hexdigest()+'.json')
        if not path.exists():atomic_json(path,proof)
        binding={**proof['binding'],'evidence_path':path.relative_to(store.project).as_posix(),'evidence_absolute_path':str(path.resolve()),'evidence_sha256':digest(path)}
        bindings=list({b['pdf_url']:b for b in [*bindings,binding]}.values())[-10:]
    updated={**record,'public_copy_bindings':bindings,
             'public_download_sources':list({s['access_url']:s for s in [*record.get('public_download_sources',[]),source]}.values())[-3:]}
    return bibliography.save(store,updated,domain)


def persist_sources(store,record,domain=None):
    """Persist primary-page DOI/PDF bindings in the existing writer transaction."""
    from . import paper_bibliography as bibliography
    record=dict(record);pending=record.pop('pending_public_source_proofs',[])
    for item in pending[:3]:record=save(store,record,item['source'],item['proof'],domain)
    return record if pending else bibliography.save(store,record,domain)


def binding_valid(binding,identity,citation,pdf_path):
    from .paper_bibliography import norm
    if not (binding.get('pdf_url')==identity.get('official_pdf_url') and binding.get('doi')==citation.get('doi')
            and norm(binding.get('title',''))==norm(identity['title'])
            and [norm(a) for a in binding.get('authors',[])]==[norm(a) for a in identity.get('authors',[])]
            and binding.get('match_basis') in {'official_page_declared_doi','official_link_exact_title_all_authors_unique_formal_doi','publisher_metadata_declared_doi'}):return False
    try:
        path=Path(binding['evidence_absolute_path'])
        relative=Path(binding['evidence_path'])
        if relative.is_absolute() or '..' in relative.parts or not relative.parts:return False
        # Derive the proof's catalog from its persisted relative path, and
        # reject another catalog before reading its proof or following links.
        project=path.parents[len(relative.parts)-1].resolve()
        if (project/relative).resolve()!=path.resolve() or not path.resolve().is_relative_to(project) or not Path(pdf_path).resolve().is_relative_to(project):return False
        if not path.is_absolute() or path.parent.name!='metadata-sources' or path.parent.parent.name!='.knowledge' or not re.fullmatch(r'official-copy-[0-9a-f]{64}\.json',path.name) or path.stat().st_size>5*1024*1024:return False
        if digest(path)!=binding['evidence_sha256']:return False
        proof=json.loads(path.read_text('utf-8'))
        return all(proof['binding'].get(k)==binding.get(k) for k in ('doi','title','authors','pdf_url','declared_pdf_url','source_url','response_sha256','match_basis','retrieved_at'))
    except (KeyError,OSError,ValueError,TypeError,IndexError):return False
