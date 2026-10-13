"""Current, independently verified citation records. PDF outcomes never choose citations."""
import asyncio,json,re,uuid,time,xml.etree.ElementTree as ET
import urllib.request,urllib.error
from datetime import datetime,timezone
from urllib.parse import quote
from .safety import DomainError,json_text,hash_bytes,atomic_json,digest,contained
_gate=asyncio.Semaphore(2)
_rate=asyncio.Lock()
_last={}

FIELDS=('title','authors','year','venue','doi','source_type','volume','issue','pages','url')
FORMAL={'journal-article':'JournalArticle','proceedings-article':'ConferenceProceedings','book':'Book','book-chapter':'Book'}
def stamp():return datetime.now(timezone.utc).isoformat()
def doi(value):
    value=str(value or '').strip().lower().removeprefix('https://doi.org/')
    if not re.fullmatch(r'10\.\d{4,9}/\S{1,180}',value):raise DomainError('citation_identifier_required')
    return value
def arxiv(value):
    value=str(value or '').strip().removeprefix('https://arxiv.org/abs/').removeprefix('arXiv:')
    if not re.fullmatch(r'(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?',value):raise DomainError('citation_identifier_required')
    return re.sub(r'v\d+$','',value)
def fresh(value,seconds=86400):
    try:return 0<=(datetime.now(timezone.utc)-datetime.fromisoformat(value.replace('Z','+00:00'))).total_seconds()<seconds
    except (ValueError,TypeError,AttributeError):return False
def people(value):return [' '.join([str(a.get('given','')),str(a.get('family',''))]).strip() for a in value if isinstance(a,dict)]
def plain_abstract(value):
    from html import unescape
    return ' '.join(unescape(re.sub(r'<[^>]*>',' ',str(value or ''))).split())[:20000]
def norm(value):
    from .institutional_access import normalize
    # Formal registries sometimes omit accents preserved in the author's
    # repository record (Gomez/Gómez, Tardos/Tardós). Keep every author and
    # stable identifier check; only canonical diacritic differences collapse.
    import unicodedata
    from html import unescape
    value=unescape(re.sub(r'<[^>]+>','',str(value)))
    return normalize(''.join(c for c in unicodedata.normalize('NFKD', value) if not unicodedata.combining(c)))
def same_identity(a,b):
    # A title alone is never sufficient. Stable identifiers/author evidence are independent.
    aa=[norm(v) for v in a.get('authors',[])];bb=[norm(v) for v in b.get('authors',[])]
    return bool(a.get('title') and b.get('title') and norm(a['title'])==norm(b['title']) and aa and aa==bb)

def declared_author_identity(left,right):
    """Supporting author evidence only after an original declared DOI edge."""
    from .research_download import author_name_matches
    return bool(left and right and len(left)==len(right)
                and all(author_name_matches(a,b) for a,b in zip(left,right)))

async def _fetch(url):
    # Fixed public metadata APIs only. No institution credentials, HTML or arbitrary redirects.
    from urllib.parse import urlsplit
    target=urlsplit(url)
    if target.scheme!='https' or target.hostname not in {'api.crossref.org','export.arxiv.org'} or target.username or target.password or target.port not in {None,443}:
        raise DomainError('citation_source_invalid')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    def read():
        # The packaged asyncio TLS transport fails on some Windows installations.
        # Use the same system-trusted HTTPS stack as public discovery, without
        # disabling certificate/hostname checks or forwarding browser sessions.
        if target.hostname=='export.arxiv.org':
            from .research_download import public_opener
            opener=public_opener(NoRedirect())
        else:opener=urllib.request.build_opener(NoRedirect())
        request=urllib.request.Request(url,headers={'User-Agent':'Knowline citation verification/1.0','Accept':'application/json,application/atom+xml'})
        with opener.open(request,timeout=15) as response:
            if response.status!=200:raise DomainError('citation_source_unavailable',502,http_status=response.status,request_sent=True)
            data=response.read(2*1024*1024+1)
            if len(data)>2*1024*1024:raise DomainError('citation_source_invalid')
            return data
    return await asyncio.to_thread(read)
async def fetch(url):
    try:
        async with _gate:
            host='arxiv' if 'export.arxiv.org' in url else 'crossref'
            async with _rate:
                delay=(3 if host=='arxiv' else 1)-(time.monotonic()-_last.get(host,0))
                if delay>0:await asyncio.sleep(delay)
                _last[host]=time.monotonic()
            return await _fetch(url)
    except urllib.error.HTTPError as exc:raise DomainError('citation_source_unavailable',502,http_status=exc.code,request_sent=True)
    except (urllib.error.URLError,OSError):raise DomainError('citation_source_unavailable',502,reason='network_error',request_sent=True)

def crossref(work,checked):
    identifier=doi(work.get('DOI'));kind=FORMAL.get(work.get('type'))
    date=next((work[k]['date-parts'][0] for k in ['published-print','published','published-online','issued'] if isinstance(work.get(k),dict) and work[k].get('date-parts') and work[k]['date-parts'][0]),[])
    record={'title':str((work.get('title') or [''])[0]).strip()[:1000],'authors':people(work.get('author',[])),
            'year':date[0] if date else None,'venue':str((work.get('container-title') or [work.get('publisher','')])[0])[:300],
            'doi':identifier,'source_type':kind or 'Report','volume':str(work.get('volume',''))[:40],'issue':str(work.get('issue',''))[:40],
            'pages':str(work.get('page') or work.get('article-number') or '')[:100],'url':'https://doi.org/'+identifier,
            'publication_status':'published' if kind else 'preprint' if work.get('type')=='posted-content' else 'unverified',
            'identity_key':'doi:'+identifier,'latest_checked_at':checked,'latest_verified':True,'related_identifiers':[],
            'source_url':'https://api.crossref.org/works/'+quote(identifier,safe='/'),'publisher_url':work.get('resource',{}).get('primary',{}).get('URL') or work.get('URL') or 'https://doi.org/'+identifier}
    from .institutional_access import safe_url
    try:record['publisher_url']=safe_url(record['publisher_url'])
    except DomainError:record['publisher_url']=record['url']
    for name in ['has-preprint','is-preprint-of','is-version-of','has-version']:
        for link in work.get('relation',{}).get(name,[])[:10]:
            if link.get('id-type')=='doi':
                try:record['related_identifiers'].append('doi:'+doi(link['id']))
                except DomainError:pass
    record['relation']=work.get('relation',{})
    if work.get('abstract'):record['abstract']=plain_abstract(work['abstract'])
    record['metadata_status']='verified' if kind and record['title'] and record['authors'] and record['year'] and record['venue'] else 'partially_verified'
    # Exact DOI registrations may contain the direct publisher PDF even when
    # the article page/index is unavailable. Such links remain candidates until
    # their actual PDF title, authors and identifier have all been verified.
    from .official_copy import canonical_link
    # Registration of a PDF URL is not an OA grant. Retain an explicit,
    # currently effective CC licence separately from the download candidate.
    oa_licenses=[]
    for license in work.get('license',[])[:10]:
        url=str(license.get('URL') or '') if isinstance(license,dict) else ''
        if not re.match(r'https?://(?:www\.)?creativecommons\.org/(?:licenses/|publicdomain/)',url,re.I):continue
        start=str((license.get('start') or {}).get('date-time') or '')
        if start and start[:10]>checked[:10]:continue
        oa_licenses.append({'url':url,'content_version':license.get('content-version'),'source_url':record['source_url']})
    record['open_access_verified']=any(v['content_version'] in {None,'vor','unspecified'} for v in oa_licenses)
    if oa_licenses:record['open_access_evidence']=oa_licenses
    sources=[];bindings=[]
    for link in work.get('link',[])[:10]:
        if len(sources)>=3:break
        if not isinstance(link,dict):continue
        raw=link.get('URL','')
        if link.get('content-type')!='application/pdf' and not re.search(r'\.pdf(?:$|[?#])|/_pdf(?:$|[?#])',str(raw),re.I):continue
        try:pdf_url=safe_url(canonical_link(raw))
        except (DomainError,ValueError,TypeError):continue
        version={'vor':'published','am':'accepted_manuscript'}.get(link.get('content-version'),'unknown')
        open_copy=record['open_access_verified'] or any(v['content_version']==link.get('content-version') for v in oa_licenses)
        bindings.append({'doi':identifier,'title':record['title'],'authors':record['authors'],'pdf_url':pdf_url,
                         'source_url':record['source_url'],'declared_pdf_url':raw,'retrieved_at':checked,
                         'match_basis':'registered_doi_pdf_link_candidate_only'})
        sources.append({'publisher_url':record['publisher_url'],'access_url':pdf_url,'public_oa':bool(open_copy),'open_access_verified':bool(open_copy),'download_permitted':True,
                        'pdf_version':version,'version_source_url':record['source_url'],
                        'version_basis':'Exact DOI registration PDF link content-version: '+str(link.get('content-version') or 'unknown'),
                        'fallback_reason':'Exact DOI registry PDF link; only explicit OA evidence permits anonymous download',
                        'pdf_identity':{k:record[k] for k in ('title','authors','doi')}})
    if sources:record.update(public_download_sources=sources,public_copy_bindings=bindings)
    return record

async def resolve(identifier=None,arxiv_id=None):
    if not arxiv_id and re.fullmatch(r'(?i)10\.48550/arxiv\..+',str(identifier or '')):arxiv_id=re.sub(r'(?i)^10\.48550/arxiv\.','',str(identifier))
    checked=stamp();visited=set();evidence=[];related=[]
    async def load(value):
        value=doi(value)
        if value in visited or len(visited)>=5:raise DomainError('citation_relation_invalid')
        visited.add(value)
        try:work=json.loads(await fetch('https://api.crossref.org/works/'+quote(value,safe='/')))['message']
        except (ValueError,KeyError,TypeError):raise DomainError('citation_source_invalid')
        if doi(work.get('DOI'))!=value:raise DomainError('citation_identity_conflict',409)
        record=crossref(work,checked);evidence.append(record.copy());return record
    if arxiv_id:
        key=arxiv(arxiv_id)
        try:
            root=ET.fromstring(await fetch('https://export.arxiv.org/api/query?id_list='+quote(key,safe='')))
            entry=root.find('{http://www.w3.org/2005/Atom}entry')
            if entry is None:raise ValueError()
            def text(name):return entry.findtext('{http://www.w3.org/2005/Atom}'+name,'').strip()
            versioned=text('id').rsplit('/abs/',1)[-1];version=re.search(r'v(\d+)$',versioned)
            if arxiv(versioned)!=key or not version:raise ValueError()
            record={'title':' '.join(text('title').split()),'authors':[n.findtext('{http://www.w3.org/2005/Atom}name','').strip() for n in entry.findall('{http://www.w3.org/2005/Atom}author')],
                    'year':int(text('updated')[:4]),'first_posted_at':text('published'),'version_posted_at':text('updated'),'venue':'arXiv','doi':'','source_type':'Report','url':'https://arxiv.org/abs/'+versioned,
                    'publication_status':'preprint','identity_key':'arxiv:'+key,'arxiv_id':key,'preprint_version':int(version[1]),
                    'latest_verified':True,'latest_checked_at':checked,'metadata_status':'verified','source_url':'https://arxiv.org/abs/'+key,
                    'publisher_url':'https://arxiv.org/abs/'+key,'related_identifiers':['arxiv:'+key],'formal_record_status':'not_verified'}
            evidence.append(record.copy());formal=entry.findtext('{http://arxiv.org/schemas/atom}doi','').strip()
            if text('summary'):record['abstract']=plain_abstract(text('summary'));evidence[-1]['abstract']=record['abstract']
            if formal:
                try:publication=await load(formal)
                except DomainError as exc:
                    if exc.code!='citation_source_unavailable':raise
                    record['formal_doi_unverified']=doi(formal);record['formal_record_status']='source_unavailable';record['metadata_status']='partially_verified';publication=None
                # The repository DOI relationship and author agreement allow changed final titles.
                if publication:
                    if not declared_author_identity(publication.get('authors'),record['authors']):raise DomainError('citation_identity_conflict',409)
                    related=['arxiv:'+key];record=publication
            else:
                # A repository may omit the subsequently published DOI. Only an
                # exact full title, every author and a unique formal primary
                # record can establish this bridge; nearest-title hits cannot.
                original=record
                from urllib.parse import urlencode
                query='https://api.crossref.org/works?'+urlencode({'query.title':record['title'],'rows':5})
                try:
                    works=json.loads(await fetch(query))['message']['items']
                    exact=[w for w in works[:5] if w.get('type') in FORMAL and norm((w.get('title') or [''])[0])==norm(record['title']) and [norm(v) for v in people(w.get('author',[]))]==[norm(v) for v in record['authors']]]
                    identifiers=list(dict.fromkeys(doi(w['DOI']) for w in exact))
                    if len(identifiers)>1:raise DomainError('citation_relation_ambiguous',409)
                    if identifiers:
                        publication=await load(identifiers[0])
                        if not same_identity(publication,original):raise DomainError('citation_identity_conflict',409)
                        evidence.append({'source_url':query,'retrieved_at':checked,'relationship':'exact_title_all_authors_unique_formal_record','arxiv_id':key,'doi':publication['doi'],'title':original['title'],'authors':original['authors']})
                        related=['arxiv:'+key];record=publication
                except DomainError as exc:
                    if exc.code!='citation_source_unavailable':raise
                    record['formal_record_status']='source_unavailable';record['metadata_status']='partially_verified'
                except (ValueError,KeyError,TypeError):raise DomainError('citation_source_invalid')
        except (ET.ParseError,ValueError,AttributeError):raise DomainError('citation_source_invalid')
    else:record=await load(identifier)
    # Follow declared version/publication edges, never a nearest-title search result.
    for _ in range(4):
        if record['publication_status']=='published':break
        links=record.get('relation',{}).get('is-preprint-of',[]) or record.get('relation',{}).get('is-version-of',[])
        links=[link for link in links if link.get('id-type')=='doi']
        if len(links)>1:raise DomainError('citation_relation_ambiguous',409)
        if not links:break
        previous=record;new=await load(links[0]['id'])
        if not declared_author_identity(new.get('authors'),previous['authors']):raise DomainError('citation_identity_conflict',409)
        related.extend([previous['identity_key'],*previous.get('related_identifiers',[])]);record=new
    if record['publication_status']=='preprint' and not arxiv_id:
        # Current DOI metadata alone cannot prove a repository's latest preprint version.
        raise DomainError('citation_latest_preprint_unverified',409)
    if record['publication_status']=='unverified':raise DomainError('citation_publication_unverified',409)
    record['related_identifiers']=list(dict.fromkeys([*related,*record.get('related_identifiers',[])]))
    record['formal_record_status']='verified' if record['publication_status']=='published' else record.get('formal_record_status','not_verified')
    record['evidence']=evidence
    return record

def rows(store):return [json.loads(r['data']) for r in store.rows('SELECT data FROM paper_records ORDER BY updated_at DESC')]
def get(store,identifier):
    visited=set()
    for _ in range(5):
        if identifier in visited:break
        visited.add(identifier)
        value=store.one('SELECT data FROM paper_records WHERE id=?',(identifier,))
        if not value:raise DomainError('citation_record_not_found',404)
        record=json.loads(value['data'])
        if not record.get('alias_of'):return record
        identifier=record['alias_of']
    raise DomainError('citation_relation_invalid',409)
def _primary_arxiv_keys(record):
    """Original verified repository evidence, separate from inherited aliases."""
    from .research_download import _arxiv_key,repository_arxiv_id
    aliases={_arxiv_key(value[6:]) for value in record.get('related_identifiers',[]) if value.startswith('arxiv:')}
    keys=set()
    for item in record.get('evidence',[]):
        if not isinstance(item,dict):continue
        key=_arxiv_key(item.get('arxiv_id') or str(item.get('identity_key','')).removeprefix('arxiv:'))
        if not key or key not in aliases:continue
        if not any(repository_arxiv_id(item.get(name))==key for name in ('url','source_url')):continue
        if item.get('formal_doi') and str(item['formal_doi']).casefold()!=str(record.get('doi','')).casefold():continue
        relationship=item.get('relationship')
        primary=relationship in {'repository_declared_doi','existing_verified_identifier_link','exact_title_all_authors_unique_repository_record'}
        if relationship=='exact_title_all_authors_unique_repository_record' and not same_identity(item,record):continue
        # resolve() also retains its original repository metadata record.
        primary=primary or bool(item.get('publication_status')=='preprint' and item.get('latest_verified')
            and item.get('preprint_version') and [norm(a) for a in item.get('authors',[])]==[norm(a) for a in record.get('authors',[])])
        if primary:keys.add(key)
    return keys


def save(store,record,domain_id=None):
    if not record.get('latest_verified') or not fresh(record.get('latest_checked_at')):raise DomainError('citation_refresh_required',409)
    if record['publication_status']=='preprint' and not record.get('preprint_version'):raise DomainError('citation_latest_preprint_unverified',409)
    matches=[r for r in rows(store) if not r.get('alias_of') and (r['identity_key']==record['identity_key'] or r['identity_key'] in record.get('related_identifiers',[]) or record['identity_key'] in r.get('related_identifiers',[]))]
    existing=next((r for r in matches if r['identity_key']==record['identity_key']),matches[0] if matches else None)
    if domain_id and not store.one('SELECT id FROM groups WHERE id=?',(domain_id,)):raise DomainError('group_not_found',404)
    if existing and (existing['publication_status']=='published' and record['publication_status']!='published' or existing.get('latest_checked_at','')>record['latest_checked_at']):
        if domain_id and domain_id not in existing['domain_ids']:
            existing={**existing,'domain_ids':existing['domain_ids']+[domain_id],'revision':existing['revision']+1}
            store.db.execute('UPDATE paper_records SET data=?,updated_at=? WHERE id=?',(json_text(existing),stamp(),existing['id']));store.event('paper_record',existing['id'],existing['revision'])
        return existing
    if existing and existing['publication_status']==record['publication_status']=='preprint' and existing.get('preprint_version',0)>record.get('preprint_version',0):raise DomainError('citation_older_version',409)
    identifier=existing['id'] if existing else 'pr_'+uuid.uuid4().hex
    domains=list(dict.fromkeys([*[d for r in matches for d in r.get('domain_ids',[])],*([domain_id] if domain_id else [])]))
    record={**record,'related_identifiers':list(dict.fromkeys([*record.get('related_identifiers',[]),*[v for r in matches for v in r.get('related_identifiers',[])]]))}
    # Official-copy proofs remain valid across a fresh formal-record lookup
    # only while the DOI, complete title and every author remain the same.
    bindings=[b for r in [*matches,record] for b in r.get('public_copy_bindings',[])
              if b.get('doi')==record.get('doi') and norm(b.get('title',''))==norm(record['title'])
              and [norm(a) for a in b.get('authors',[])]==[norm(a) for a in record['authors']]]
    if bindings:
        record={**record,'public_copy_bindings':list({b['pdf_url']:b for b in bindings}.values())[-10:]}
        allowed={b['pdf_url'] for b in record['public_copy_bindings']}
        sources=[s for r in [*matches,record] for s in r.get('public_download_sources',[]) if s.get('access_url') in allowed]
        record['public_download_sources']=list({s['access_url']:s for s in [*sources,*record.get('public_download_sources',[])]}.values())[-3:]
    repositories=[b for r in [*matches,record] for b in r.get('repository_bindings',[])
                  if b.get('doi')==record.get('doi') and norm(b.get('title',''))==norm(record['title'])
                  and b.get('authors')==record['authors'] and b.get('match_basis')=='exact_paper_repository_page']
    if repositories:
        record['repository_bindings']=list({tuple(b['repository']):b for b in repositories}.values())[-6:]
        from urllib.parse import urlsplit
        allowed={tuple(b['repository']) for b in record['repository_bindings']}
        sources=[s for r in [*matches,record] for s in r.get('public_download_sources',[])
                 if urlsplit(s.get('access_url','')).hostname in {'github.com','raw.githubusercontent.com'}
                 and tuple(urlsplit(s.get('access_url','')).path.strip('/').split('/')[:2]) in allowed]
        record['public_download_sources']=list({s['access_url']:s for s in [*sources,*record.get('public_download_sources',[])]}.values())[-3:]
    evidence={k:record[k] for k in [*FIELDS,'publication_status','source_url','latest_checked_at','related_identifiers'] if k in record}
    evidence['identity_evidence']=record.get('evidence',[])
    if record.get('public_copy_bindings'):evidence['public_copy_bindings']=record['public_copy_bindings']
    if record.get('repository_bindings'):evidence['repository_bindings']=record['repository_bindings']
    if 'open_access_verified' in record:evidence['open_access_verified']=record['open_access_verified']
    if record.get('open_access_evidence'):evidence['open_access_evidence']=record['open_access_evidence']
    # Keep the snapshot containing the actual repository bridge even if this
    # refresh has the same alias set. The snapshot before an alias was added
    # cannot supply that evidence. Fresh formal metadata never redates it.
    stable=[r for r in matches if record.get('doi') and r.get('doi')==record['doi'] and same_identity(r,record)]
    bridge_evidence=list(dict.fromkeys(p for r in stable for p in r.get('bridge_evidence_paths',[])))
    for prior in stable:
        if not prior.get('evidence_path') or not _primary_arxiv_keys(prior):continue
        try:
            previous_path=contained(store.project,prior['evidence_path'])
            address=re.fullmatch(r'citation-([0-9a-f]{64})\.json',previous_path.name)
            if (not address or previous_path.stat().st_size>2*1024*1024
                    or address[1]!=prior.get('evidence_sha256') or digest(previous_path)!=address[1]):continue
            bridge_evidence.append(prior['evidence_path'])
        except (OSError,ValueError,DomainError):continue
    evidence['bridge_evidence_paths']=list(dict.fromkeys(bridge_evidence))[-20:]
    from .research_download import _arxiv_key
    current_repository_keys=_primary_arxiv_keys(record)
    inherited=[value for value in record['related_identifiers'] if value.startswith('arxiv:') and _arxiv_key(value[6:]) not in current_repository_keys]
    evidence['inherited_related_identifiers']=inherited
    sha=hash_bytes(json_text(evidence).encode());path=store.state/'metadata-sources'/('citation-'+sha+'.json');atomic_json(path,evidence)
    value={**record,'bridge_evidence_paths':evidence['bridge_evidence_paths'],'inherited_related_identifiers':inherited,'id':identifier,'domain_ids':domains,'resource_ids':list(dict.fromkeys(v for r in matches for v in r.get('resource_ids',[]))),'pdf_status':(existing or {}).get('pdf_status',{'status':'not_requested'}),
           'revision':(existing or {}).get('revision',0)+1,'evidence_path':path.relative_to(store.project).as_posix(),'evidence_sha256':digest(path)}
    value.pop('relation',None)
    store.db.execute('INSERT OR REPLACE INTO paper_records(id,identity_key,data,updated_at) VALUES(?,?,?,?)',(identifier,record['identity_key'],json_text(value),stamp()))
    store.event('paper_record',identifier,value['revision'])
    # Preserve old reference IDs as explicit aliases; title similarity never triggers a merge.
    for prior in matches:
        if prior['id']==identifier:continue
        alias={**value,'id':prior['id'],'identity_key':prior['identity_key'],'alias_of':identifier,'revision':prior['revision']+1}
        store.db.execute('UPDATE paper_records SET data=?,updated_at=? WHERE id=?',(json_text(alias),stamp(),prior['id']));store.event('paper_record',prior['id'],alias['revision'])
    return value
def outcome(store,identifier,status,**details):
    value=get(store,identifier);identifier=value['id']
    prior=value.get('pdf_status',{})
    # Background metadata attachment must not erase the successful lookup's
    # diagnostics. A new full lookup replaces its own report; an attachment
    # never brings a prior failed reason forward into an acquired result.
    retained={k:prior[k] for k in ('full_text_policy','full_text_attempts','publisher_attempt') if k in prior} if status=='acquired' and prior.get('status')=='acquired' and 'full_text_attempts' not in details else {}
    value['pdf_status']={'status':status,'checked_at':stamp(),**retained,**details};value['revision']+=1
    if details.get('resource_id'):value['resource_ids']=list(dict.fromkeys(value['resource_ids']+[details['resource_id']]))
    store.db.execute('UPDATE paper_records SET data=?,updated_at=? WHERE id=?',(json_text(value),stamp(),identifier));store.event('paper_record',identifier,value['revision']);return value
def metadata_report(record, **details):
    missing=[k for k in ('title','authors','year','venue','source_type') if not record.get(k)]
    return {'policy':'publication_record_v2','independent_of_pdf':True,
            'state':'verified' if record.get('metadata_status')=='verified' and not missing else 'partial',
            'reason':'public_source_verified' if not missing else 'missing_fields',
            'checked_at':record['latest_checked_at'],'source_url':record['source_url'],
            'missing_fields':missing,'conflicting_fields':[],**details}

def metadata(record):
    return {**{k:record[k] for k in FIELDS if k in record},'metadata_status':record['metadata_status'],'publication_status':record['publication_status'],
            'latest_checked_at':record['latest_checked_at'],'publication_record_id':record['id'],'publication_record':record,
            'metadata_verification':metadata_report(record),
            'field_sources':{k:{'source':'independent_publication_record','url':record['source_url'],'retrieved_at':record['latest_checked_at'],'raw_response_path':record['evidence_path'],'raw_response_sha256':record['evidence_sha256'],'raw_value':record[k]} for k in FIELDS if record.get(k)}}

def attach_metadata(store,record,resource_id,report=None):
    """Apply the current search record without opening or certifying the PDF."""
    resource=store.resource(resource_id)
    if resource['type']!='paper':raise DomainError('scope_violation',409)
    locks=resource['metadata'].get('field_sources',{})
    update=metadata(record)
    conflicts=[k for k in FIELDS if locks.get(k,{}).get('locked') and record.get(k)
               and (resource['title'] if k=='title' else resource['metadata'].get(k))
               and norm(str(resource['title'] if k=='title' else resource['metadata'][k]))!=norm(str(record[k]))]
    update={k:v for k,v in update.items() if k not in FIELDS or not locks.get(k,{}).get('locked')}
    update['field_sources']={k:v for k,v in update['field_sources'].items() if not locks.get(k,{}).get('locked')}
    verification={**metadata_report(record),**(report or {})}
    if conflicts:verification.update(state='partial',reason='locked_field_conflict',conflicting_fields=conflicts)
    update.update(metadata_verification=verification,metadata_status='verified' if verification['state']=='verified' else 'partially_verified')
    for field in ('metadata_verification','metadata_status','latest_checked_at','publication_record','publication_record_id','publication_status'):
        update['field_sources'][field]={'source':'independent_publication_record','retrieved_at':record['latest_checked_at'],'url':record['source_url']}
    result=store.update_resource(resource_id,{'base_revision':resource['revision'],**update})['resource']
    # Citation membership is independent of the downloaded-file outcome.
    if resource_id not in record.get('resource_ids',[]):
        linked={**record,'resource_ids':[*record.get('resource_ids',[]),resource_id],'revision':record['revision']+1}
        store.db.execute('UPDATE paper_records SET data=?,updated_at=? WHERE id=?',(json_text(linked),stamp(),record['id']))
        store.event('paper_record',record['id'],linked['revision'])
    return result
def attach(store,record,resource_id,pdf_identity=None):
    from .institutional_access import validate_pdf
    resource=store.resource(resource_id)
    if resource['type']!='paper':raise DomainError('scope_violation',409)
    target={**record,'pdf_version':resource['metadata'].get('pdf_version','unknown'),'citation_record':record,**({'pdf_identity':pdf_identity} if pdf_identity else {})}
    validate_pdf(store.snapshot(resource),target)
    from .acquisition_metadata import apply
    result={'sha256':resource['sha256'],'identity_check':{'linked_publication':True},'acquired_at':stamp()}
    resource,_=apply(store,resource,target,result,True)
    outcome(store,record['id'],'acquired',resource_id=resource_id,pdf_version=resource['metadata'].get('pdf_version','unknown'))
    return resource
def export(record,format='text'):
    if not record.get('latest_verified') or not fresh(record.get('latest_checked_at'),300):raise DomainError('citation_refresh_required',409)
    if record.get('metadata_status')!='verified':raise DomainError('citation_metadata_unverified',409)
    if format=='json':return json.dumps(record,ensure_ascii=False,indent=2)
    label=' [预印本，正式出版记录未核实；v'+str(record.get('preprint_version'))+']' if record['publication_status']=='preprint' else ''
    if format=='ris':
        clean=lambda value:str(value).replace('\r',' ').replace('\n',' ')
        return '\n'.join(['TY  - '+('JOUR' if record['source_type']=='JournalArticle' else 'CONF' if record['source_type']=='ConferenceProceedings' else 'BOOK' if record['source_type']=='Book' else 'RPRT'),'TI  - '+clean(record['title']),*['AU  - '+clean(a) for a in record['authors']],'PY  - '+str(record['year']),'JO  - '+clean(record['venue']),*[(tag+'  - '+clean(record[key])) for key,tag in [('volume','VL'),('issue','IS'),('pages','SP')] if record.get(key)],'DO  - '+clean(record.get('doi','')),'UR  - '+clean(record['url']),'N1  - '+(label.strip() or 'Verified published record'),'ER  - '])
    if format!='text':raise DomainError('invalid_request')
    return '. '.join(filter(None,[', '.join(record['authors']),record['title']+label,record['venue'],str(record['year']),record.get('volume','')+('('+record['issue']+')' if record.get('issue') else ''),record.get('pages'),('DOI: '+record['doi']) if record.get('doi') else record['url']]))+'.'
