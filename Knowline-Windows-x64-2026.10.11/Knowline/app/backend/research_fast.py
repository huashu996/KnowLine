"""Finish unchanged, previously verified research without repeated model analysis."""
import copy,json,re,time,urllib.request,urllib.parse,hashlib
from pathlib import Path
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
from .safety import contained,digest,atomic_json,DomainError,json_text

def stamp():return datetime.now(timezone.utc).isoformat()
def fresh(value):
    try:return 0<=(datetime.now(timezone.utc)-datetime.fromisoformat(value.replace('Z','+00:00'))).total_seconds()<86400
    except (ValueError,TypeError,AttributeError):return False

def request(url):
    # This cache refresher has no institution browser session. Never refresh signed URLs.
    from .institutional_access import safe_url
    try:
        parsed=urllib.parse.urlsplit(url)
        # Preserve bounded, public metadata searches; no authentication parameters allowed.
        allowed_query={'query.title','query.bibliographic','rows','filter'}
        if parsed.hostname in {'api.crossref.org','api.github.com'} and parsed.query and not parsed.fragment:
            if set(urllib.parse.parse_qs(parsed.query))-allowed_query:raise DomainError('institution_url_invalid')
            safe_url(urllib.parse.urlunsplit(parsed._replace(query='')))
        else:url=safe_url(url)
    except DomainError:
        return {'retrieved_at':stamp(),'error':'unsafe_or_transient_source_url','institution_session_reused':False}
    record={'url':url,'retrieved_at':stamp()};started=time.monotonic()
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Knowline verified research cache refresh'}),timeout=15) as response:
            body=response.read(2*1024*1024+1)
            record.update(status=response.status,content_type=response.headers.get('Content-Type'),response_sha256=hashlib.sha256(body).hexdigest(),final_url='https://'+(urllib.parse.urlsplit(response.url).hostname or '')+'/',institution_session_reused=False)
            if len(body)>2*1024*1024:record['error']='response exceeds bounded metadata inspection'
            elif body.startswith(b'%PDF-'):record['pdf_available']=True
            else:
                try:record['response']=json.loads(body)
                except ValueError:record['error']='non_json_response_requires_review'
    except Exception as exc:record['error']=type(exc).__name__
    record['duration_seconds']=round(time.monotonic()-started,3)
    return record

def artifacts(store,output):
    return [{'type':'research_evidence','path':file.relative_to(store.project).as_posix(),'sha256':digest(file)} for file in output.iterdir() if file.is_file() and file.suffix in {'.json','.md'} and file.name!='result.json']

def finish(store,job,preparation):
    output=contained(store.project,job['context']['output_dir']);started=time.monotonic()
    result={'schema_version':2,'job_id':job['id'],'status':'completed','claims':[],'proposed_relations':[],'warnings':[]}
    if job['task']=='paper_relationships' and preparation.get('cache') in {'warm','field_warm'}:
        from .paper_graph import validate
        graph=json.loads((output/'paper-graph.json').read_text('utf-8'))
        if graph.get('network_policy')!='topical-multihop-real-citations-v2':return None
        audit=json.loads((output/'citation-audit.json').read_text('utf-8'))
        rows={r['node_id']:r for r in audit['rows']}
        if set(rows)!={n['id'] for n in graph['nodes']}:return None
        if any(not fresh(n['metadata_source']['retrieved_at']) or not n.get('citation_record_id') or n.get('metadata_refresh_reason') for n in graph['nodes']):return None
        # A changed/missing evidence file invalidates reuse instead of silently
        # publishing a cached graph whose provenance can no longer be checked.
        prior=store.job(preparation['source_job_id'])
        for artifact in (prior.get('result') or {}).get('artifacts',[]):
            if digest(contained(store.project,artifact['path']))!=artifact['sha256']:return None
        for node in graph['nodes']:
            row=rows[node['id']]
            node['citation_count']=row['citation_count']
            if row['citation_count'] is not None:
                if not fresh(row['citation_source']['retrieved_at']):return None
                node['citation_source']=row['citation_source']
                node['citation_identity']={k:row.get(k) for k in ['source_doi','source_title','source_authors','source_year','match_basis']}
                for field in ['citation_unknown_reason','citation_unavailable_reason']:node.pop(field,None)
            else:
                node.pop('citation_source',None);node['citation_unknown_reason']=row['reason']
        validate(graph,job['context']['literature_search']);atomic_json(output/'paper-graph.json',graph)
        result.update(paper_graph_artifact=(output/'paper-graph.json').relative_to(store.project).as_posix(),partial=any(n['citation_count'] is None for n in graph['nodes']) or len(graph['nodes'])<job['context']['literature_search'].get('target_count',0)+1)
        result['warnings']=['复用已有领域中已校验论文和真实引用关系；当前正式书目与引用次数已核对，摘要和获取来源供导入复用。','Crossref 被引次数不是全球引用总数；未知次数保留原因。','本任务保存全文获取来源；只有实际获取并登记 PDF 才算导入成功。']
        if preparation.get('cache')=='field_warm':result['warnings'].append('本轮使用已有领域证据中距新起点两跳内的论文；未做新论文发现，不代表覆盖该领域所有新发表论文。数量不足保持部分完成。')
    elif job['task']=='discover_papers' and preparation.get('cache')=='warm':
        papers=json.loads((output/'papers.json').read_text('utf-8'));cached=preparation.get('previous_import_results',[])
        from .paper_bibliography import get as citation_record,fresh as citation_fresh
        if any(not r.get('citation_record_id') for r in cached):return None
        if any(not citation_fresh(citation_record(store,r['citation_record_id']).get('latest_checked_at'),300) for r in cached):return None
        if not fresh(papers.get('retrieved_at')):return None
        current={r['candidate_id']:r for r in preparation.get('current_full_texts',[])}
        if not cached or any(not r['ready'] for r in current.values()):return None
        missing=[p for p in papers['papers'] if p['id'] not in current]
        # Previously missing subscriptions need the controlled browser broker,
        # even when a public metadata refresher finds no new download URL.
        institution=getattr(store,'institutional',None)
        if missing and institution and institution.status().get('config'):return None
        # New URLs or new candidates need a fresh identity review through Codex.
        if any(p.get('full_text_url') for p in missing):return None
        urls=[]
        for paper in missing:
            for source in paper.get('sources',[]):
                parsed=urllib.parse.urlsplit(source)
                if parsed.hostname=='doi.org':urls.append('https://api.crossref.org/works/'+urllib.parse.quote(parsed.path.lstrip('/'),safe='/'))
                elif parsed.hostname=='github.com' and len(parsed.path.strip('/').split('/'))==2:urls.append('https://api.github.com/repos/'+parsed.path.strip('/')+'/git/trees/HEAD?recursive=1')
        responses=list(ThreadPoolExecutor(max_workers=4).map(request,list(dict.fromkeys(urls))))
        atomic_json(output/'missing-full-text-refresh.json',{'responses':responses,'scope':'only previously unavailable candidates','retrieved_at':stamp()})
        links=[]
        for response in responses:
            raw=response.get('response',{})
            if response.get('pdf_available') or any(str(item.get('path','')).lower().endswith('.pdf') for item in raw.get('tree',[])):return None
            links.extend(link['URL'] for link in raw.get('message',{}).get('link',[])[:2] if isinstance(link.get('URL'),str) and urllib.parse.urlsplit(link['URL']).scheme=='https')
        link_responses=list(ThreadPoolExecutor(max_workers=4).map(request,list(dict.fromkeys(links))))
        responses.extend(link_responses)
        atomic_json(output/'missing-full-text-refresh.json',{'responses':responses,'scope':'only previously unavailable candidates','retrieved_at':stamp()})
        if any(r.get('pdf_available') for r in link_responses):return None
        rows=[]
        for previous in cached:
            row=copy.deepcopy(previous);check=current.get(row['candidate_id'])
            if check:
                resource=store.resource(check['resource_id'])
                if resource['version_id']!=check['version_id'] or digest(store.snapshot(resource))!=check['sha256']:return None
                if previous.get('version_id')!=resource['version_id']:
                    from . import pdf
                    with pdf.open_pdf(store.snapshot(resource)) as current_doc,pdf.open_pdf(store.snapshot(resource,previous['version_id'])) as previous_doc:
                        if len(current_doc)!=len(previous_doc) or any(current_doc[i].get_text()!=previous_doc[i].get_text() for i in range(min(2,len(current_doc)))):return None
                row.update(resource_id=resource['id'],version_id=resource['version_id'],sha256=resource['sha256'],new_download=False,new_registration=False,duplicate=True,metadata_status=resource['metadata'].get('metadata_status'))
            else:row['unavailable_reason']='本轮有限查询仍未取得可核验PDF；具体HTTP响应、限流或作者仓库文件清单见 missing-full-text-refresh.json。原缺项：'+str(row.get('unavailable_reason',''))
            rows.append(row)
        result.update(imported_papers=rows,partial=bool(missing))
        result['warnings']=['相同冻结范围的候选与书目来源使用24小时内缓存；可用全文核对当前版本及真实SHA256，复用已入库文件。','缺失全文只查询原出版标识和作者仓库；查询范围有限，不代表已穷尽所有获取途径。','未新增下载或重复登记；元数据状态按当前资源保留，全文可用不等于书目信息完全核实。']
    else:return None
    atomic_json(output/'fast-path-review.json',{'provider':'hash_validated_research_reuse','source_job_id':preparation['source_job_id'],'scope_unchanged':preparation.get('scope_unchanged',True),'duration_seconds':round(time.monotonic()-started,3),'repeated_model_analysis':False})
    result['artifacts']=artifacts(store,output);atomic_json(output/'result.json',result)
    return result

def metadata(store,job):
    """Explicit citation verification refreshes current publication/version metadata.

    PDF and vector reuse remain unchanged. A byte-identical file is not evidence
    that its citation still describes the current published/latest preprint record.
    """
    return None
