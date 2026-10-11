"""Current, independently verified citation records. PDF outcomes never choose citations."""
import asyncio,json,re,uuid,time,xml.etree.ElementTree as ET
from datetime import datetime,timezone
from urllib.parse import quote
import httpx
from .safety import DomainError,json_text,hash_bytes,atomic_json,digest
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
    return normalize(''.join(c for c in unicodedata.normalize('NFKD', value) if not unicodedata.combining(c)))
def same_identity(a,b):
    # A title alone is never sufficient. Stable identifiers/author evidence are independent.
    aa=[norm(v) for v in a.get('authors',[])];bb=[norm(v) for v in b.get('authors',[])]
    return bool(a.get('title') and b.get('title') and norm(a['title'])==norm(b['title']) and aa and aa==bb)

async def _fetch(url):
    # Fixed public metadata APIs only. No institution credentials, HTML or arbitrary redirects.
    async with httpx.AsyncClient(timeout=15,follow_redirects=False,trust_env=False) as client:
        async with client.stream('GET',url,headers={'User-Agent':'Knowline citation verification/1.0','Accept':'application/json,application/atom+xml'}) as response:
            if response.status_code!=200:raise DomainError('citation_source_unavailable',502,http_status=response.status_code)
            data=bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data)>2*1024*1024:raise DomainError('citation_source_invalid')
            return bytes(data)
async def fetch(url):
    try:
        async with _gate:
            host='arxiv' if 'export.arxiv.org' in url else 'crossref'
            async with _rate:
                delay=(3 if host=='arxiv' else 1)-(time.monotonic()-_last.get(host,0))
                if delay>0:await asyncio.sleep(delay)
                _last[host]=time.monotonic()
            return await _fetch(url)
    except httpx.HTTPError:raise DomainError('citation_source_unavailable',502,reason='network_error')

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
                    if not publication.get('authors') or [norm(v) for v in publication['authors']]!=[norm(v) for v in record['authors']]:raise DomainError('citation_identity_conflict',409)
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
        if not new.get('authors') or [norm(v) for v in new['authors']]!=[norm(v) for v in previous['authors']]:raise DomainError('citation_identity_conflict',409)
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
    evidence={k:record[k] for k in [*FIELDS,'publication_status','source_url','latest_checked_at','related_identifiers'] if k in record}
    evidence['identity_evidence']=record.get('evidence',[])
    if record.get('public_copy_bindings'):evidence['public_copy_bindings']=record['public_copy_bindings']
    # Keep a bounded audit trail for previously verified cross-version bridges.
    bridge_evidence=list(dict.fromkeys([p for r in matches for p in r.get('bridge_evidence_paths',[])]))
    if existing and set(record['related_identifiers'])!=set(existing.get('related_identifiers',[])):
        bridge_evidence.extend(r['evidence_path'] for r in matches if r.get('evidence_path'))
    evidence['bridge_evidence_paths']=list(dict.fromkeys(bridge_evidence))[-20:]
    sha=hash_bytes(json_text(evidence).encode());path=store.state/'metadata-sources'/('citation-'+sha+'.json');atomic_json(path,evidence)
    value={**record,'bridge_evidence_paths':evidence['bridge_evidence_paths'],'id':identifier,'domain_ids':domains,'resource_ids':list(dict.fromkeys(v for r in matches for v in r.get('resource_ids',[]))),'pdf_status':(existing or {}).get('pdf_status',{'status':'not_requested'}),
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
    value=get(store,identifier);identifier=value['id'];value['pdf_status']={'status':status,'checked_at':stamp(),**details};value['revision']+=1
    if details.get('resource_id'):value['resource_ids']=list(dict.fromkeys(value['resource_ids']+[details['resource_id']]))
    store.db.execute('UPDATE paper_records SET data=?,updated_at=? WHERE id=?',(json_text(value),stamp(),identifier));store.event('paper_record',identifier,value['revision']);return value
def metadata(record):
    return {**{k:record[k] for k in FIELDS if k in record},'metadata_status':record['metadata_status'],'publication_status':record['publication_status'],
            'latest_checked_at':record['latest_checked_at'],'publication_record_id':record['id'],'publication_record':record,
            'field_sources':{k:{'source':'independent_publication_record','url':record['source_url'],'retrieved_at':record['latest_checked_at'],'raw_response_path':record['evidence_path'],'raw_response_sha256':record['evidence_sha256'],'raw_value':record[k]} for k in FIELDS if record.get(k)}}
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
