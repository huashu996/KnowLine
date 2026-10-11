"""Normal task execution for verifiable SLAM full-text quotas, without login/model."""
import asyncio,json,re,time,urllib.parse
from . import paper_bibliography as bibliography
from .safety import DomainError,contained,atomic_json,digest
from .store import uid


def kind(job):
    query=job['context'].get('literature_search',{}).get('search_plan',{}).get('topic_query') or job['context'].get('literature_search',{}).get('query','')
    if re.search(r'visual\s*(?:inertial\s*)?SLAM|视觉\s*(?:惯性\s*)?SLAM',query,re.I):return 'visual'
    if re.search(r'(?:lidar|laser)\s*SLAM|激光\s*SLAM',query,re.I):return 'lidar'
    return None


def relevant(record,topic):
    text=' '.join([record.get('title',''),record.get('abstract',''),*[v.get('abstract','') for v in record.get('evidence',[])]]).lower()
    localization=bool(re.search(r'\bslam\b|simultaneous localization|odometry|relocalization|mapping',text))
    sensor=bool(re.search(r'visual|camera|rgb[- ]?d|image',text) if topic=='visual' else re.search(r'li\s*dar|laser|point cloud',text))
    return localization and sensor


def clean_title(value):return re.sub(r'\[(?:HTML|PDF|BOOK|CITATION)\]','',str(value),flags=re.I).strip()


def preferred(job,value):
    plan=job['context']['literature_search'].get('search_plan',{})
    venues=plan.get('preferred_venues',[])
    if venues and any(bibliography.norm(v) in bibliography.norm(value.get('venue','')) for v in venues):return True
    if plan.get('preferred_publisher')=='IEEE':
        return bool(str(value.get('doi','')).startswith('10.1109/') or 'ieeexplore.ieee.org' in str(value.get('publisher_url') or value.get('paper_url','')) or 'IEEE' in (value.get('venue','')+' '+value.get('byline','')))
    return not venues


async def identify(candidate):
    """Resolve one located candidate; title lookup is exact and bounded to 3."""
    title=clean_title(candidate.get('title',''));identifier=candidate.get('doi')
    repository=candidate.get('arxiv_id')
    for url in [candidate.get('pdf_url',''),candidate.get('paper_url','')]:
        found=re.search(r'https?://(?:export\.)?arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})',url)
        if found:repository=found[1];break
    if repository:
        record=await bibliography.resolve(identifier,repository)
        if bibliography.norm(record['title'])!=bibliography.norm(title) and not any(e.get('arxiv_id')==repository and bibliography.norm(e.get('title',''))==bibliography.norm(title) for e in record.get('evidence',[])):raise DomainError('citation_identity_conflict')
        return record
    if not identifier:
        for url in [candidate.get('paper_url',''),candidate.get('pdf_url','')]:
            found=re.search(r'10\.\d{4,9}/[^?\s]+',urllib.parse.unquote(url),re.I)
            if found:identifier=found[0].removesuffix('/full').removesuffix('/pdf');break
    if not identifier:
        url='https://api.crossref.org/works?'+urllib.parse.urlencode({'query.title':title,'rows':3})
        try:works=json.loads(await bibliography.fetch(url))['message']['items']
        except (ValueError,KeyError,TypeError):raise DomainError('citation_source_invalid')
        matches=[w for w in works[:3] if bibliography.norm((w.get('title') or [''])[0])==bibliography.norm(title)]
        if len(matches)==1:identifier=matches[0].get('DOI')
        elif len(matches)>1:raise DomainError('citation_identity_ambiguous')
    if not identifier and not repository:raise DomainError('citation_identifier_unavailable')
    record=await bibliography.resolve(identifier,repository if not identifier else None)
    if bibliography.norm(record['title'])!=bibliography.norm(title):raise DomainError('citation_identity_conflict')
    if repository:
        try:
            linked=await bibliography.resolve(identifier,repository)
            if linked['identity_key']==record['identity_key'] and 'arxiv:'+repository in linked.get('related_identifiers',[]):record=linked
        except DomainError:pass  # The independently verified formal record survives.
    return record


def plans(candidate,record):
    from .research_import import choices
    from .research_download import permitted_public_host
    sources=choices({},record)
    url=candidate.get('pdf_url') or ''
    try:
        from .institutional_access import safe_url
        url=safe_url(url);host=urllib.parse.urlsplit(url).hostname
        if host not in {'arxiv.org','export.arxiv.org'} and permitted_public_host(host,record):
            sources.insert(0,{'publisher_url':record['publisher_url'],'access_url':url,'public_oa':True,'download_permitted':True,'pdf_version':'unknown','version_basis':'Located open source; actual PDF version requires evidence','fallback_reason':'Public full text located independently of institution login','pdf_identity':{k:record[k] for k in ('doi','title','authors')}})
    except DomainError:pass
    from .research_policy import source_priority
    return sorted(sources,key=lambda source:source_priority(source,record))[:3]


async def run(store,job,write,broker,progress=lambda text:None):
    from .research_policy import acquisition_limits
    from .research_query import names
    from .research_discovery import more
    limits=acquisition_limits(job);scope=job['context']['literature_search'];domain=job['context']['scope']['domain_id']
    output=contained(store.project,job['context']['output_dir']);topic=kind(job);rows=[];seen=set();seen_candidates=set();identities=set();used=set();start=time.monotonic()
    source=output/names(scope)['scholar'];pool=json.loads(source.read_text('utf-8')).get('papers',[]) if source.is_file() else []
    discovery_file=output/names(scope)['discovery']
    if not pool and discovery_file.is_file():pool=json.loads(discovery_file.read_text('utf-8')).get('papers',[])
    repository_discovery=output/'repository-discovery.json'
    if repository_discovery.is_file():pool.extend(json.loads(repository_discovery.read_text('utf-8')).get('papers',[]))
    journal_discovery=output/'journal-discovery.json'
    if journal_discovery.is_file():pool.extend(json.loads(journal_discovery.read_text('utf-8')).get('papers',[]))
    previous=output/'acquisition-progress.json'
    if previous.is_file():
        from .institutional_access import validate_pdf
        unique={}
        for prior in json.loads(previous.read_text('utf-8')).get('rows',[]):
            unique[prior['candidate_id']]=prior
        for prior in unique.values():
            if prior.get('candidate_id')=='discovery_source':continue
            row=dict(prior);seen.add(row.get('doi') or row['candidate_id']);seen_candidates.add(row['candidate_id'])
            if row.get('resource_id'):
                try:
                    resource=store.resource(row['resource_id']);record=bibliography.get(store,row['citation_record_id'])
                    if resource['sha256']!=row['sha256'] or resource['metadata'].get('metadata_status')!='verified' or not bibliography.fresh(record.get('latest_checked_at')) or domain not in resource['groups']:raise DomainError('prior_fulltext_requires_refresh')
                    validate_pdf(store.snapshot(resource),{**record,'citation_record':record,'pdf_identity':resource['metadata'].get('pdf_identity') or {k:record[k] for k in ('doi','title','authors')}})
                    used.add(resource['id']);identities.add(record['identity_key'])
                    row.update(duplicate=True,new_download=False,new_registration=False)
                except (DomainError,KeyError):
                    seen.discard(row.get('doi') or row['candidate_id']);seen_candidates.discard(row['candidate_id']);row.pop('resource_id',None);row['unavailable_reason']='prior_fulltext_requires_refresh'
            rows.append(row)
    # Prefer independently verified instance memory; no other project/catalog.
    resources={r['id']:r for r in store.resources()}
    for record in bibliography.rows(store):
        available=any(rid in resources and resources[rid]['metadata'].get('metadata_status')=='verified' and (not resources[rid]['groups'] or domain in resources[rid]['groups']) for rid in record.get('resource_ids',[]))
        if available and record.get('latest_verified') and relevant(record,topic) and scope['from_year']<=record.get('year',0)<=scope['to_year']:
            pool.insert(0,{'id':'memory_'+record['id'],'title':record['title'],'doi':record.get('doi'),'arxiv_id':record.get('arxiv_id'),'venue':record.get('venue'),'paper_url':record.get('url'),'citation_record_id':record['id'],'source':{'provider':'Verified instance memory'}})
    pool.sort(key=lambda value:not preferred(job,value))
    # Resume the same finite candidate list; do not repeat failed downloads.
    pool=[p for p in pool if p['id'] not in seen_candidates and (p.get('doi') or p['id']) not in seen]
    preference=bool(scope.get('search_plan',{}).get('preferred_venues') or scope.get('search_plan',{}).get('preferred_publisher'))
    nonpreferred_limit=(limits['target_verified_fulltexts']-1)//2
    async def active_write(kind,body,action):
        def guard():
            if store.job(job['id'])['status'] not in {'running','waiting_user'}:raise asyncio.CancelledError()
            return action()
        return await write(kind,body,guard)
    def checkpoint():
        atomic_json(output/'acquisition-progress.json',{'target_count':limits['target_verified_fulltexts'],'verified_fulltexts':len(used),'attempted_candidates':len(rows),'rows':rows,'duration_seconds':round(time.monotonic()-start,3)})
    attempted_this_run=0
    while len(used)<limits['target_verified_fulltexts'] and attempted_this_run<limits['maximum_candidates']:
        if store.job(job['id'])['status'] not in {'running','waiting_user'}:raise asyncio.CancelledError()
        if not pool:
            refill=await asyncio.to_thread(more,store,job)
            if not refill.get('papers'):break
            pool.extend(refill['papers'])
        candidate=pool.pop(0);key=candidate.get('doi') or candidate['id']
        if key in seen or candidate['id'] in seen_candidates:continue
        seen.add(key);seen_candidates.add(candidate['id']);attempted_this_run+=1;row={'candidate_id':candidate['id'],'title':clean_title(candidate['title']),**({'doi':candidate['doi']} if candidate.get('doi') else {})}
        progress('已核实入库 '+str(len(used))+'/'+str(limits['target_verified_fulltexts'])+'；正在核对下一候选及合法公开全文。')
        try:
            memory=bibliography.get(store,candidate['citation_record_id']) if candidate.get('citation_record_id') else None
            record=memory if memory and memory.get('metadata_status')=='verified' and bibliography.fresh(memory.get('latest_checked_at')) else await identify(candidate)
            if not relevant(record,topic) or not scope['from_year']<=record['year']<=scope['to_year']:raise DomainError('candidate_outside_topic_or_year')
            if record.get('metadata_status')!='verified':raise DomainError('public_citation_verification_required')
            preferred_match=preferred(job,record)
            if preference and not preferred_match and sum(bool(r.get('resource_id')) and not r.get('preferred_source_match') for r in rows)>=nonpreferred_limit:raise DomainError('candidate_outside_preferred_majority')
            # Exclude same exact paper already used in this quota.
            if record['identity_key'] in identities:raise DomainError('duplicate_verified_candidate')
            record=await active_write('discovery_citation',{'operation_id':uid('op')},lambda:bibliography.save(store,record,domain))
            row.update(title=record['title'],doi=record.get('doi'),year=record['year'],venue=record['venue'],citation_record_id=record['id'],identity_key=record['identity_key'],preferred_source_match=preferred_match)
            cached=next((r for r in store.resources() if r['id'] in record.get('resource_ids',[]) and r['metadata'].get('metadata_status')=='verified'),None)
            if cached:
                from .institutional_access import validate_pdf
                validate_pdf(store.snapshot(cached),{**record,'citation_record':record,'pdf_identity':cached['metadata'].get('pdf_identity') or {k:record[k] for k in ('doi','title','authors')}})
                if cached.get('groups') and domain not in cached['groups']:raise DomainError('candidate_already_used_in_other_domain')
                def reuse():
                    resource=bibliography.attach(store,record,cached['id'],cached['metadata'].get('pdf_identity'))
                    group=next(g for g in store.groups() if g['id']==domain)
                    if resource['id'] not in group['resource_ids']:store.group_members(domain,{'base_revision':group['revision'],'resource_ids':[*group['resource_ids'],resource['id']]})
                    return resource
                resource=await active_write('discovery_reuse',{'operation_id':uid('op')},reuse)
                acquired={'status':'imported','resource_id':resource['id'],'version_id':resource['version_id'],'sha256':resource['sha256'],'duplicate':True,'new_download':False,'new_registration':False}
            else:
                paper={**{k:record.get(k) for k in ('doi','title','authors','year','venue')},'candidate_id':candidate['id'],'citation_record_id':record['id'],'sources':plans(candidate,record)}
                acquired=await broker.acquire({'job_id':job['id'],'paper':paper,'timeout_seconds':scope.get('source_request_timeout_seconds',10)})
            if acquired.get('resource_id'):
                row.update(acquired);used.add(acquired['resource_id']);identities.add(record['identity_key'])
            else:row['unavailable_reason']=acquired.get('reason','bounded_public_sources_exhausted')
        except (DomainError,ValueError,OSError,KeyError,TypeError) as exc:row['unavailable_reason']=getattr(exc,'code',type(exc).__name__)
        rows.append(row);checkpoint()
    partial=len(used)<limits['target_verified_fulltexts']
    if not rows:
        rows=[{'candidate_id':'discovery_source','title':scope['query'],'unavailable_reason':'No candidates available from the finite permitted discovery sources'}];checkpoint()
    warnings=['Finite permitted sources exhausted: '+str(len(used))+'/'+str(limits['target_verified_fulltexts'])+' verified fulltexts'] if partial else []
    report=output/'report.md';report.write_text('Verified fulltexts: '+str(len(used))+'/'+str(limits['target_verified_fulltexts'])+'\n\n'+'\n'.join(r['title']+': '+('verified and registered' if r.get('resource_id') else r.get('unavailable_reason','unavailable')) for r in rows),'utf-8')
    artifacts=[{'path':p.relative_to(store.project).as_posix(),'sha256':digest(p)} for p in [report,output/'acquisition-progress.json']]
    result={'schema_version':2,'job_id':job['id'],'status':'completed','partial':partial,'target_count':limits['target_verified_fulltexts'],'imported_papers':rows,'artifacts':artifacts,'claims':[],'proposed_relations':[],'warnings':warnings,'acquisition_duration_seconds':round(time.monotonic()-start,3)}
    atomic_json(output/'result.json',result);return result
