"""Search-based bibliography updates, independent of PDF identity. No agent jobs.

Network work happens outside Store.mutate; results commit through the public
writer after checking the current PDF version/hash. Only a short title or stable
identifier goes to the fixed public metadata APIs, never PDF/authentication data.
"""
import asyncio
import json
import logging
import re
import time
import unicodedata
from urllib.parse import urlencode
from . import paper_bibliography as bibliography
from .pdf import open_pdf
from .safety import DomainError, digest
from .store import uid


def lookup_signature(resource):
    meta=resource['metadata']
    return bibliography.hash_bytes(json.dumps([resource['title'],meta.get('doi'),meta.get('arxiv_id'),
        meta.get('authors'),resource.get('version_id'),resource.get('sha256'),
        sorted(k for k,v in meta.get('field_sources',{}).items() if v.get('locked'))],sort_keys=True).encode())


def verification_due(resource):
    """Only unresolved searches retry; completed citations do not poll the web."""
    if resource.get('type')!='paper' or resource.get('state')!='ready':return False
    meta=resource['metadata'];report=meta.get('metadata_verification') or {}
    if report.get('policy')!='publication_record_v2':return True
    if report.get('state')=='verified' and meta.get('metadata_status')=='verified' and not report.get('refresh_state'):return False
    if report.get('lookup_signature') and report['lookup_signature']!=lookup_signature(resource):return True
    delays=(30,120,600,3600) if (report.get('refresh_state') or report.get('state'))=='source_unavailable' else (300,1800,21600)
    attempt=report.get('retry_count')
    attempt=max(1,attempt) if isinstance(attempt,int) else 1
    return not bibliography.fresh(report.get('refresh_checked_at') or report.get('checked_at'),delays[min(attempt-1,len(delays)-1)])


def inspect_pdf(path, hints):
    with open_pdf(path) as doc:
        if not doc.is_pdf or not len(doc):raise DomainError('pdf_invalid')
        page=doc[0];text=page.get_text()[:30000]
        # References on a one-page PDF must not supply the imported paper's DOI.
        text=re.split(r'(?im)^\s*(?:references|bibliography|参考文献)\s*$',text)[0]
        top=page.get_text(clip=(0,0,page.rect.width,page.rect.height*.6))[:12000]
        top=re.split(r'(?im)^\s*(?:references|bibliography|参考文献)\s*$',top)[0]
        header=re.split(r'(?im)^\s*(?:abstract|摘要)\s*[-—:.]?\s*',top)[0]
        # Keep the raw header for title evidence. Use the PDF's actual
        # superscript span flag to separate author affiliation markers (Lia)
        # from surnames (Li); never guess or strip letters from author names.
        author_lines=[]
        for block in page.get_text('dict',clip=(0,0,page.rect.width,page.rect.height*.6)).get('blocks',[]):
            if block.get('type')!=0:continue
            for line in block.get('lines',[]):
                author_lines.append(''.join(' ' if s.get('flags',0)&1 and re.fullmatch(r'[A-Za-z0-9*†‡,]{1,3}',s.get('text','')) else s.get('text','') for s in line.get('spans',[])))
        author_header=re.split(r'(?im)^\s*(?:abstract|摘要)\s*[-—:.]?\s*','\n'.join(author_lines))[0]
        # Keep the author/title region independent of bibliography/body matching.
        normalized=bibliography.norm(header)
        title=''
        candidates=[hints.get('title'),(doc.metadata or {}).get('title')]
        # Font-size runs provide a bounded fallback for local PDFs with no hints.
        runs=[]
        for block in page.get_text('dict').get('blocks',[]):
            if block.get('type')!=0 or block['bbox'][1]>page.rect.height*.5:continue
            lines=block.get('lines',[])
            value=' '.join(''.join(s.get('text','') for s in line.get('spans',[])).strip() for line in lines)
            size=max((s.get('size',0) for line in lines for s in line.get('spans',[])),default=0)
            if 15<=len(value)<=600:runs.append((size,value))
        candidates += [v for size,v in sorted(runs,key=lambda v:-v[0])[:5] if size>12]
        candidates += [line.strip() for line in header.splitlines() if 15<=len(line.strip())<=400][:3]
        for value in candidates:
            if value and 15<=len(str(value))<=1000 and bibliography.norm(str(value)) in normalized:
                title=' '.join(str(value).split());break
        identifiers=list(dict.fromkeys(v.rstrip('.,;:)') for v in re.findall(r'(?i)10\.\d{4,9}/[^\s<>"\]]+',text)))
        identifiers=[v.lower() for v in identifiers][:4]
        ax=re.search(r'(?i)arxiv\s*:\s*((?:\d{4}\.\d{4,5}|[a-z-]+/\d{7})(?:v\d+)?)',text)
        return {'title':title,'header':header,'author_header':author_header,'dois':identifiers,'arxiv_id':ax[1] if ax else '',
                'sha256':digest(path),'pages_inspected':1}


def surname_in_header(author, header):
    """Match a surname in the author header, allowing PDF affiliation markers."""
    text=unicodedata.normalize('NFKC',header).casefold()
    text=re.sub(r"(?<=\w)[\-\u00ad\u2010-\u2015'\u2018\u2019]\s*(?=\w)",'',text)
    surname=bibliography.norm(author.split()[-1]) if author.split() else ''
    if len(surname)<2:return False
    # Superscript affiliations become digits under NFKC. Keep the surname's
    # word boundaries so Xu1 is accepted while Xue or Zhangson is rejected.
    return bool(re.search(r'(?<!\w)'+re.escape(surname)+r'(?:\d{1,3})?(?!\w)',text))


def identity(record, evidence):
    """No nearest-title attachment; compare the actual first-page header."""
    header=evidence['header'];normalized=bibliography.norm(header)
    options=[record,*record.get('evidence',[])]
    keys={record['identity_key'],*record.get('related_identifiers',[])}
    for option in options:
        key=option.get('identity_key')
        if not key and option.get('provider')=='arXiv' and option.get('arxiv_id') and option.get('relationship') in {'repository_declared_doi','existing_verified_identifier_link','exact_title_all_authors_unique_repository_record'}:
            # Older located repository evidence omits identity_key; use only
            # its explicitly verified link already present in this record.
            key='arxiv:'+bibliography.arxiv(option['arxiv_id'])
        if key not in keys:continue
        authors=option.get('authors',[]);title=option.get('title','')
        if not title or bibliography.norm(title) not in normalized or not authors:continue
        author_header=evidence.get('author_header',header)
        surnames=all(surname_in_header(a,author_header) for a in authors)
        if not surnames:continue
        identifier=(key.startswith('doi:') and key[4:] in evidence['dois']) or (key.startswith('arxiv:') and evidence['arxiv_id'] and bibliography.arxiv(evidence['arxiv_id'])==key[6:])
        # DOI-free PDFs need every full author name and a unique exact API result.
        full_names=all(bibliography.norm(a) in bibliography.norm(author_header) for a in authors)
        if not identifier and (evidence['dois'] or evidence['arxiv_id'] or not full_names):continue
        return {'title':title,'authors':authors,'doi':option.get('doi',''),'arxiv_id':option.get('arxiv_id',''),
                'basis':'header_title_authors_identifier' if identifier else 'unique_exact_title_all_full_authors',
                'pages_inspected':evidence['pages_inspected']}
    raise DomainError('citation_identity_conflict',409)


async def search_title(query):
    """Select one exact public title result, without comparing its PDF contents."""
    title=query.get('title','')
    if not title:raise DomainError('citation_identifier_required')
    url='https://api.crossref.org/works?'+urlencode({'query.title':title,'rows':5})
    try:works=json.loads(await bibliography.fetch(url))['message']['items']
    except (ValueError,KeyError,TypeError):raise DomainError('citation_source_invalid')
    matches={}
    for work in works[:5]:
        try:record=bibliography.crossref(work,bibliography.stamp())
        except DomainError:continue
        if record['publication_status']=='published' and bibliography.norm(record['title'])==bibliography.norm(title):
            matches[record['doi']]=record
    if len(matches)>1 and query.get('authors'):
        authors=[bibliography.norm(a) for a in query['authors']]
        matches={key:value for key,value in matches.items() if [bibliography.norm(a) for a in value['authors']]==authors}
    if not matches:raise DomainError('citation_match_not_found',409)
    if len(matches)!=1:raise DomainError('citation_search_ambiguous',409)
    return await bibliography.resolve(next(iter(matches)))


class PaperMetadataVerifier:
    def __init__(self,store,write):
        self.store=store;self.write=write;self.pending={};self.lookups={};self.gate=asyncio.Semaphore(2)

    async def resolve(self,identifier=None,arxiv_id=None,refresh=False):
        key='arxiv:'+bibliography.arxiv(arxiv_id) if arxiv_id else 'doi:'+bibliography.doi(identifier)
        task=self.lookups.get(key)
        if refresh and task and task.done():self.lookups.pop(key,None);task=None
        if task and task.done() and (task.cancelled() or task.exception() or task.result().get('metadata_status')!='verified' or not bibliography.fresh(task.result().get('latest_checked_at'),300)):
            self.lookups.pop(key,None);task=None
        if task is None:
            for prior in list(self.lookups):
                if len(self.lookups)<64:break
                if self.lookups[prior].done():self.lookups.pop(prior,None)
            task=asyncio.create_task(bibliography.resolve(identifier,arxiv_id));self.lookups[key]=task
        return await asyncio.shield(task)

    async def imported(self,result,hints=None):
        resource=result.get('resource')
        if not resource or resource['type']!='paper':return result
        verification=await self.verify(resource['id'],hints or {})
        return {**result,'resource':self.store.resource(resource['id']),'metadata_verification':verification,'metadata_job':None}

    async def repair_pending(self,limit=20):
        # This is a bounded maintenance pass, not an agent task or full re-import.
        resources=self.store.resources(summary=True)
        pending_ids={key[0] for key,task in self.pending.items() if not task.done()}
        candidates=[r for r in resources if r['id'] not in pending_ids and verification_due(r)]
        candidates.sort(key=lambda r:(r['metadata'].get('metadata_verification') or {}).get('refresh_checked_at') or
                        (r['metadata'].get('metadata_verification') or {}).get('checked_at') or '')
        reports=[]
        for offset in range(0,min(limit,len(candidates)),2):
            batch=candidates[offset:min(offset+2,limit)]
            results=await asyncio.gather(*(self.verify(r['id'],{'refresh':True}) for r in batch),return_exceptions=True)
            for result in results:
                if isinstance(result,Exception):
                    if not isinstance(result,DomainError) or result.code not in {'resource_not_found','resource_unavailable'}:
                        logging.getLogger(__name__).warning('Automatic citation retry failed: %s',type(result).__name__)
                elif isinstance(result,dict):reports.append(result)
        return reports

    async def maintain(self):
        while True:
            await self.repair_pending()
            await asyncio.sleep(30)

    async def verify(self,resource_id,hints=None):
        resource=self.store.resource(resource_id)
        if resource['type']!='paper':return {'state':'not_applicable'}
        key=(resource_id,resource['version_id'],resource['sha256'])
        if key not in self.pending:self.pending[key]=asyncio.create_task(self._verify(resource,hints or {}))
        task=self.pending[key]
        try:return await asyncio.shield(task)
        finally:
            if task.done() and self.pending.get(key) is task:self.pending.pop(key,None)

    async def _verify(self,resource,hints):
        started=time.perf_counter();timings={}
        version=resource['version_id'];sha=resource['sha256'];rid=resource['id']
        async def commit(report,record=None):
            def action():
                current=self.store.resource(rid)
                if (current['version_id'],current['sha256'])!=(version,sha):return {**report,'state':'superseded','reason':'version_changed'}
                if record:
                    saved=bibliography.save(self.store,record)
                    current=bibliography.attach_metadata(self.store,saved,rid,report)
                    return current['metadata']['metadata_verification']
                prior=current['metadata'].get('metadata_status')
                previous=current['metadata'].get('metadata_verification') or {}
                attempts=previous.get('retry_count')
                current_report={**report,'retry_count':max(0,attempts)+1 if isinstance(attempts,int) else 1,'lookup_signature':lookup_signature(current)}
                # A temporary failed refresh cannot revoke an evidenced citation.
                # Keep the successful check time and expose the retry separately.
                if report['state']=='source_unavailable' and prior=='verified' and previous.get('policy')=='publication_record_v2' and previous.get('state')=='verified':
                    current_report={**previous,'refresh_state':report['state'],'refresh_reason':report['reason'],
                                    'refresh_checked_at':report['checked_at'],'retry_count':current_report['retry_count'],
                                    'lookup_signature':current_report['lookup_signature'],'timings_ms':report['timings_ms']}
                status=prior if prior in {'verified','partially_verified'} else 'needs_review'
                self.store.update_resource(rid,{'base_revision':current['revision'],'metadata_status':status,'metadata_verification':current_report,
                    'field_sources':{'metadata_status':{'source':'automatic_publication_search','retrieved_at':report['checked_at']},'metadata_verification':{'source':'automatic_publication_search','retrieved_at':report['checked_at']}}})
                return current_report
            return await self.write('automatic_paper_metadata',{'operation_id':uid('op'),'resource_id':rid,'version_id':version},action)
        at=started
        try:
            async with self.gate:
                at=time.perf_counter()
                meta=resource['metadata'];publication=meta.get('publication_record') or {}
                identifier=hints.get('doi') or meta.get('doi') or publication.get('doi')
                arxiv_id=hints.get('arxiv_id') or meta.get('arxiv_id') or publication.get('arxiv_id')
                query={'title':hints.get('title') or resource['title'],'authors':hints.get('authors') or meta.get('authors') or []}
                # For an unlabelled local import the PDF may supply search clues.
                # These clues never become an acceptance gate for source metadata.
                if not identifier and not arxiv_id and not publication:
                    try:
                        clues=await asyncio.to_thread(inspect_pdf,self.store.snapshot(resource),{**meta,'title':resource['title'],**hints})
                        identifier=next(iter(clues['dois']),None)
                        arxiv_id=clues['arxiv_id'] or None
                        if clues['title']:query['title']=clues['title']
                    except (DomainError,OSError,ValueError,KeyError,TypeError):pass
                timings['search_clues_ms']=round((time.perf_counter()-at)*1000,2)
                at=time.perf_counter()
                async def lookup():
                    if identifier:return await self.resolve(identifier,refresh=hints.get('refresh',False))
                    if arxiv_id:return await self.resolve(arxiv_id=arxiv_id,refresh=hints.get('refresh',False))
                    return await search_title(query)
                record=await asyncio.wait_for(lookup(),35)
                timings['source_lookup_ms']=round((time.perf_counter()-at)*1000,2)
                report=bibliography.metadata_report(record,version_id=version,sha256=sha,
                    timings_ms={**timings,'total_ms':round((time.perf_counter()-started)*1000,2)})
                return await commit(report,record)
        except asyncio.CancelledError:raise
        except (DomainError,TimeoutError,OSError,ValueError,KeyError,TypeError) as exc:
            timings.setdefault('source_lookup_ms',round((time.perf_counter()-at)*1000,2))
            reason=exc.code if isinstance(exc,DomainError) else 'citation_source_timeout' if isinstance(exc,TimeoutError) else 'citation_source_invalid'
            # Any conflict here is between search-source records, never with the PDF.
            if reason in {'citation_identity_conflict','citation_relation_ambiguous'}:reason='citation_search_ambiguous'
            state='source_unavailable' if reason in {'citation_source_unavailable','citation_source_timeout'} else 'needs_review'
            report={'policy':'publication_record_v2','independent_of_pdf':True,'state':state,'reason':reason,
                    'checked_at':bibliography.stamp(),'missing_fields':[],'version_id':version,'sha256':sha,
                    'timings_ms':{**timings,'total_ms':round((time.perf_counter()-started)*1000,2)}}
            if isinstance(exc,DomainError) and isinstance(exc.params.get('http_status'),int):report['http_status']=exc.params['http_status']
            return await commit(report)

    async def close(self):
        jobs=[*self.pending.values(),*self.lookups.values()]
        for task in jobs:task.cancel()
        await asyncio.gather(*jobs,return_exceptions=True)
