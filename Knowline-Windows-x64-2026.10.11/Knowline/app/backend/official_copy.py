"""Verify an explicitly located official author/repository copy, never discover topics."""
import asyncio,hashlib,json,re,urllib.parse,urllib.request
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


def approved_url(url,record):
    from .research_download import permitted_public_host
    parsed=urllib.parse.urlsplit(url)
    if parsed.hostname in {'github.com','raw.githubusercontent.com'}:
        pieces=parsed.path.strip('/').split('/')
        return len(pieces)>=2 and tuple(pieces[:2]) in AUTHOR_REPOS
    return parsed.hostname in AUTHOR_HOSTS or permitted_public_host(parsed.hostname,record)


def canonical_link(url):
    if url in PUBLIC_ALIASES:return PUBLIC_ALIASES[url]
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme=='http' and url not in LEGACY_PUBLIC_PDFS:parsed=parsed._replace(scheme='https')
    if parsed.hostname=='github.com':
        parts=parsed.path.strip('/').split('/')
        if len(parts)>=5 and parts[2]=='blob' and tuple(parts[:2]) in AUTHOR_REPOS:
            parsed=parsed._replace(netloc='raw.githubusercontent.com',path='/'+ '/'.join([*parts[:2],*parts[3:]]))
    return parsed.geturl()


def fetch_page(url):
    from .research_download import GuardedRedirect,public_opener
    host=urllib.parse.urlsplit(url).hostname
    if not public_destination(url,{host},allow_translated=True):raise DomainError('public_pdf_destination_unsafe')
    opener=public_opener(GuardedRedirect({host}))
    with opener.open(urllib.request.Request(url,headers={'User-Agent':'Knowline official paper source verification/1.0'}),timeout=10) as response:
        content=response.read(2*1024*1024+1)
        if len(content)>2*1024*1024:raise DomainError('official_source_page_size_limit')
        html=content.decode('utf-8','replace')
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
        return {'url':response.url,'retrieved_at':stamp(),'response_sha256':hashlib.sha256(content).hexdigest(),
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


def binding_valid(binding,identity,citation,pdf_path):
    from .paper_bibliography import norm
    if not (binding.get('pdf_url')==identity.get('official_pdf_url') and binding.get('doi')==citation.get('doi')
            and norm(binding.get('title',''))==norm(identity['title'])
            and [norm(a) for a in binding.get('authors',[])]==[norm(a) for a in identity.get('authors',[])]
            and binding.get('match_basis') in {'official_page_declared_doi','official_link_exact_title_all_authors_unique_formal_doi'}):return False
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
