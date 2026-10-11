"""PDF source evidence and independently selected citation metadata."""
import json
import re
from pathlib import Path
from .safety import DomainError, atomic_json, digest, hash_bytes, json_text
from .institutional_access import normalize, safe_url

def capture(data,url,retrieved_at):
    """Only fixed citation fields leave WebView2; no DOM, cookies or signed links."""
    try:url=safe_url(url)
    except Exception:return {}
    title=str(data.get('title') or '')[:500].strip()
    authors=[a.strip()[:120] for a in data.get('authors',[])[:100] if isinstance(a,str) and a.strip()]
    year=re.search(r'\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b',str(data.get('date') or ''))
    doi=str(data.get('doi') or '').strip().lower().removeprefix('https://doi.org/')
    if not re.fullmatch(r'10\.\d{4,9}/\S{1,180}',doi):doi=''
    kind=data.get('source_type')
    if kind not in {'JournalArticle','ConferenceProceedings','Report','Book'}:kind=''
    return {'url':url,'retrieved_at':retrieved_at,'bibliography':{'title':title,'authors':authors,'year':int(year[0]) if year else None,'venue':str(data.get('venue') or '')[:200].strip(),'doi':doi,'source_type':kind}}

def apply_source(store, resource, target, result, duplicate=False):
    source=result.get('source_metadata') or {}
    fields=source.get('bibliography') or {}
    missing=[k for k in ['title','authors','year','venue','source_type'] if not fields.get(k)]
    if target.get('doi') and not fields.get('doi'):missing.append('doi')
    conflicts=[]
    url=source.get('url')
    try:url=safe_url(url)
    except Exception:url=None
    if not url:missing.append('source_url')
    if fields.get('title') and normalize(fields['title'])!=normalize(target['title']):conflicts.append('来源题名与下载论文不一致')
    if fields.get('authors'):
        expected={normalize(a.split()[-1]) for a in target['authors']}
        actual=[normalize(a) for a in fields['authors']]
        if not expected or not all(any(author in name for name in actual) for author in expected):conflicts.append('来源作者与下载论文不一致')
    if fields.get('doi') and target.get('doi') and fields['doi'].casefold()!=target['doi'].casefold() and target['pdf_version']=='published':conflicts.append('出版方 DOI 与下载目标不一致')
    if fields.get('source_type') not in {'JournalArticle','ConferenceProceedings','Report','Book'}:missing.append('source_type')
    if not isinstance(fields.get('year'),int) or isinstance(fields.get('year'),bool) or not 1500<=fields.get('year',0)<=2200:missing.append('year')
    updates={}
    # Complete downloaded-source identity is required before attaching verified fields.
    complete=not missing and not conflicts
    if complete:
        bounded={'url':url,'retrieved_at':source.get('retrieved_at') or result['acquired_at'],'bibliography':fields,'pdf_sha256':result['sha256'],'version_id':resource['version_id'],'identity_check':result['identity_check'],'provider':'same_session_download'}
        sha=hash_bytes(json_text(bounded).encode());path=store.state/'metadata-sources'/('acquisition-'+sha+'.json');atomic_json(path,bounded)
        sources={}
        for key in ['title','authors','year','venue','source_type','doi']:
            if not fields.get(key):continue
            value=fields[key];old=resource['title'] if key=='title' else resource['metadata'].get(key)
            prior=resource['metadata'].get('field_sources',{}).get(key,{})
            equal=normalize(str(old))==normalize(str(value))
            if key=='authors' and isinstance(old,list):
                equal=[sorted(re.findall(r'\w+',str(a).casefold())) for a in old]==[sorted(re.findall(r'\w+',str(a).casefold())) for a in value]
            if duplicate and prior.get('locked') and old and not equal:
                conflicts.append('人工锁定字段与来源不一致：'+key);continue
            updates[key]=value
            sources[key]={'source':'same_session_download','url':url,'retrieved_at':bounded['retrieved_at'],'raw_response_path':path.relative_to(store.project).as_posix(),'raw_response_sha256':digest(path),'raw_value':value,'locked':bool(duplicate and prior.get('locked'))}
        if 'doi' in sources and fields['doi'].casefold()!=target.get('doi','').casefold() and target['pdf_version']!='published':
            sources['doi']['basis']={'downloaded_version_doi':fields['doi'],'requested_publication_doi':target.get('doi'),'publication_doi_separately_unverified':True}
        updates['field_sources']=sources
    if not duplicate or resource['metadata'].get('metadata_status')!='verified':
        updates['metadata_status']='verified' if complete and not conflicts else 'partially_verified'
        updates.setdefault('field_sources',{})['metadata_status']={'source':'same_session_download','url':url,'retrieved_at':result['acquired_at'],'basis':{'missing_fields':list(dict.fromkeys(missing)),'conflicts':conflicts,'same_session':True}}
    if updates:resource=store.update_resource(resource['id'],{'base_revision':resource['revision'],**updates})['resource']
    return resource,{'status':resource['metadata'].get('metadata_status'),'same_session':True,'missing_fields':list(dict.fromkeys(missing)),'conflicts':conflicts,'source_url':url}

def apply(store,resource,target,result,duplicate=False):
    from .paper_bibliography import rows,metadata
    record=target.get('citation_record') or next((r for r in rows(store) if r.get('doi')==target.get('doi')),None)
    if record:
        # PDF identity was checked before this transaction. No file/annotation/version change.
        update=metadata(record)
        if target.get('pdf_identity'):
            identity=target['pdf_identity'];previous=resource['metadata'].get('pdf_identity') or {}
            if (previous.get('official_pdf_url') or previous.get('publisher_pdf_url')) and not (identity.get('official_pdf_url') or identity.get('publisher_pdf_url')):
                from .institutional_access import validate_pdf
                try:
                    validate_pdf(store.snapshot(resource),{**record,'citation_record':record,'pdf_identity':previous,'pdf_version':resource['metadata'].get('pdf_version','unknown')})
                    identity=previous
                except (DomainError,OSError,ValueError,KeyError,TypeError):pass
            update['pdf_identity']=identity
        locks=resource['metadata'].get('field_sources',{})
        if duplicate:
            update={k:v for k,v in update.items() if k not in {'title','authors','doi','year','venue','volume','issue','pages','source_type','url'} or not locks.get(k,{}).get('locked')}
            update['field_sources']={k:v for k,v in update['field_sources'].items() if not locks.get(k,{}).get('locked')}
        if not duplicate:update['pdf_source_metadata']=result.get('source_metadata') or {}
        resource=store.update_resource(resource['id'],{'base_revision':resource['revision'],**update})['resource']
        return resource,{'status':record['metadata_status'],'publication_status':record['publication_status'],'record_id':record['id'],'latest_checked_at':record['latest_checked_at'],'independent_of_pdf':True,'missing_fields':[],'conflicts':[]}
    if target.get('pdf_version')!='published':
        update={'pdf_source_metadata':result.get('source_metadata') or {}}
        if resource['metadata'].get('metadata_status')!='verified':update['metadata_status']='partially_verified'
        if not duplicate:resource=store.update_resource(resource['id'],{'base_revision':resource['revision'],**update})['resource']
        return resource,{'status':resource['metadata'].get('metadata_status'),'publication_status':'unverified','independent_of_pdf':True,'reason':'formal_record_not_verified','missing_fields':['verified_citation_record'],'conflicts':[]}
    # Direct publisher-page evidence may verify an OA PDF's formal bibliography.
    # It does not require a separate institution subscription or replace a formal record with a preprint.
    return apply_source(store,resource,target,result,duplicate)

def reverify(store,frozen,lookup):
    from .institutional_access import validate_pdf
    resource=store.resource(frozen['resource_id'])
    if resource['version_id']!=frozen['version_id']:raise DomainError('version_conflict',409)
    meta=resource['metadata'];source={'url':lookup.get('source_url'),'retrieved_at':lookup.get('retrieved_at'),'bibliography':lookup.get('bibliography',{})}
    target={'title':resource['title'],'authors':meta.get('authors') or source['bibliography'].get('authors') or [],'doi':meta.get('doi') or source['bibliography'].get('doi') or '', 'pdf_version':meta.get('pdf_version','unknown')}
    path=store.snapshot(resource,frozen['version_id'])
    check=validate_pdf(path,target)
    resource,verification=apply(store,resource,target,{'source_metadata':source,'sha256':digest(path),'identity_check':check,'acquired_at':lookup['retrieved_at']},True)
    return {**verification,'resource_id':resource['id'],'version_id':resource['version_id']}
