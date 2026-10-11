"""Direct, frozen graph selection import; no second literature search or model run."""
import asyncio,json,time
from pathlib import Path
from urllib.parse import urlsplit
from .safety import contained,digest,atomic_json,DomainError
from .store import uid
from . import paper_bibliography as bibliography
from .institutional_access import validate_pdf


def choices(node,record):
    # Prefer acquisition plans already reviewed during graph preparation.
    explicit=node.get('download_sources')
    explicit=explicit if isinstance(explicit,list) else []
    if not record:return explicit[:3]
    identity={k:record[k] for k in ('doi','title','authors')}
    sources=[]
    if record['publication_status']=='published':
        sources.append({'publisher_url':record['publisher_url'],'access_url':record['publisher_url'],
            'pdf_identity':identity,'pdf_version':'unknown','download_permitted':True,
            'version_basis':'Publisher original page; actual PDF version requires page evidence',
            'fallback_reason':'Actual PDF version has not yet been identified; formal citation is kept independently'})
    related=[v[6:] for v in record.get('related_identifiers',[]) if v.startswith('arxiv:')]
    if record.get('arxiv_id'):related.insert(0,record['arxiv_id'])
    for identifier in dict.fromkeys(related):
        evidence=next((v for v in record.get('evidence',[]) if v.get('arxiv_id')==identifier),None)
        if not evidence:continue
        url=evidence.get('url') or 'https://arxiv.org/abs/'+identifier
        sources.append({'publisher_url':url,'access_url':url,'public_oa':True,'pdf_version':'preprint',
            'pdf_identity':{'title':evidence['title'],'authors':evidence['authors'],'arxiv_id':identifier},
            'version_basis':'Latest arXiv version '+str(evidence.get('preprint_version'))+' verified against the repository record',
            'fallback_reason':'Publisher full text unavailable or no active institution authorization',
            'download_permitted':True})
    # Keep reviewed, located OA PDF links. Repository version plans are rebuilt
    # from the current record instead of retaining an old arXiv version.
    for value in [*explicit,*record.get('public_download_sources',[])]:
        if not isinstance(value,dict) or 'arxiv.org' in str(value.get('access_url','')):continue
        if value.get('public_oa') is True:
            # Older graph plans store the actual PDF in `url`, not access_url.
            sources.insert(0,{**value,'access_url':value.get('access_url') or value.get('url') or value.get('publisher_url'),
                'pdf_identity':value.get('pdf_identity') or identity,
                'version_basis':value.get('version_basis') or value.get('pdf_version_basis') or 'Located public copy; actual file version remains unknown',
                'fallback_reason':value.get('fallback_reason') or 'Verified public copy located independently of institution access'})
    from .research_policy import source_priority
    sources=list({s.get('access_url') or s.get('publisher_url'):s for s in sources}.values())
    return sorted(sources,key=lambda source:source_priority(source,record))[:3]


async def run(store,job,write,broker,progress=lambda message:None):
    frozen=job['context']['paper_graph_selection']
    if digest(contained(store.project,frozen['artifact']))!=frozen['sha256']:
        raise DomainError('artifact_hash_mismatch')
    output=contained(store.project,job['context']['output_dir']);output.mkdir(parents=True,exist_ok=True)
    domain=job['context']['scope'].get('domain_id')
    rows=[];started=time.monotonic();first_available=None
    from .research_enrich import enrich,matching
    prepared,metadata_timing=await enrich(store,frozen['candidates'],write,domain,budget=None)
    existing=bibliography.rows(store)
    async def write_row(kind,action):return await write(kind,{'operation_id':uid('op')},action)
    for index,node in enumerate(prepared):
        row_started=time.monotonic();download_seconds=0
        row={'candidate_id':node['id'],'title':node['title']};record=None
        progress('直接导入 '+str(index+1)+'/'+str(len(frozen['candidates']))+'：核对当前书目及已有全文。')
        try:
            if store.job(job['id'])['status'] not in {'running','waiting_user'}:raise asyncio.CancelledError()
            from .graph_fulltext import acquire_node
            response=await acquire_node(store,job,node,write,broker,domain)
            row.update(response)
            record=matching(node,bibliography.rows(store),store)
            if record:row['citation_record_id']=record['id']
            elif not row.get('resource_id'):row['citation_unavailable_reason']=node.get('metadata_refresh_reason','current_publication_not_verified')
            download_seconds=row.get('duration_seconds',0)
        except asyncio.TimeoutError:row['unavailable_reason']='bounded_download_or_metadata_timeout'
        except (DomainError,OSError,ValueError) as exc:row['unavailable_reason']=getattr(exc,'code','source_or_file_unavailable')
        row['metadata_status']=record.get('metadata_status') if record else 'needs_review'
        row['duration_seconds']=round(time.monotonic()-row_started,3);row['pdf_acquisition_seconds']=download_seconds
        if row.get('resource_id') and first_available is None:first_available=round(time.monotonic()-started,3)
        rows.append(row)
        atomic_json(output/'direct-import-progress.json',{'rows':rows,'elapsed_seconds':round(time.monotonic()-started,3),'first_available_seconds':first_available,'metadata':metadata_timing,'new_literature_search':False})
    report=output/'direct-import-progress.json'
    result={'schema_version':2,'job_id':job['id'],'status':'completed','partial':any(not r.get('resource_id') or r.get('metadata_status')!='verified' for r in rows),
        'claims':[],'proposed_relations':[],'imported_papers':rows,
        'artifacts':[{'type':'research_evidence','path':report.relative_to(store.project).as_posix(),'sha256':digest(report)}],
        'warnings':['直接复用冻结候选与已有全文，不执行新的论文搜索；书目按当前核验结果保存。','PDF 实际版本独立记录；来源不足、需要登录或站点确认时保留具体缺项。']}
    atomic_json(output/'result.json',result)
    return result
