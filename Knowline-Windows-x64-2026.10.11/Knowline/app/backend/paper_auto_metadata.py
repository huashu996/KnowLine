"""Import-scoped bibliography verification. No agent jobs or full-text discovery.

Network work happens outside Store.mutate; results commit through the public
writer after checking the current PDF version/hash. Only a short title or stable
identifier goes to the fixed public metadata APIs, never PDF/authentication data.
"""
import asyncio
import json
import re
import time
import unicodedata
from urllib.parse import urlencode
from . import paper_bibliography as bibliography
from .pdf import open_pdf
from .safety import DomainError, digest
from .store import uid


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


async def search_title(evidence):
    if not evidence['title']:raise DomainError('citation_identifier_required')
    url='https://api.crossref.org/works?'+urlencode({'query.title':evidence['title'],'rows':5})
    try:works=json.loads(await bibliography.fetch(url))['message']['items']
    except (ValueError,KeyError,TypeError):raise DomainError('citation_source_invalid')
    matches=[]
    for work in works[:5]:
        try:
            record=bibliography.crossref(work,bibliography.stamp())
            if record['publication_status']!='published':continue
            check=identity(record,evidence)
            # Query results must match the extracted title exactly as well as PDF authors.
            if bibliography.norm(record['title'])!=bibliography.norm(evidence['title']):continue
            matches.append((record,check))
        except DomainError:continue
    if len(matches)!=1:raise DomainError('citation_identity_conflict' if matches else 'citation_match_not_found',409)
    # Fetch the authoritative identifier record, not a search snippet.
    record=await bibliography.resolve(matches[0][0]['doi'])
    return record,identity(record,evidence)


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

    async def verify(self,resource_id,hints=None):
        resource=self.store.resource(resource_id)
        if resource['type']!='paper':return {'state':'not_applicable'}
        key=(resource_id,resource['version_id'],resource['sha256'],bool((hints or {}).get('refresh')))
        if key not in self.pending:self.pending[key]=asyncio.create_task(self._verify(resource,hints or {}))
        task=self.pending[key]
        try:return await asyncio.shield(task)
        finally:
            if task.done() and self.pending.get(key) is task:self.pending.pop(key,None)

    async def _verify(self,resource,hints):
        started=time.perf_counter();timings={};cached=False;record=None;check=None
        version=resource['version_id'];sha=resource['sha256'];rid=resource['id']
        async def commit(report,record=None,check=None):
            def action():
                nonlocal report
                current=self.store.resource(rid)
                if (current['version_id'],current['sha256'])!=(version,sha):return {**report,'state':'superseded','reason':'version_changed'}
                if record:
                    locks=current['metadata'].get('field_sources',{})
                    conflicts=[field for field in bibliography.FIELDS if locks.get(field,{}).get('locked') and record.get(field) and
                        (current['title'] if field=='title' else current['metadata'].get(field)) and bibliography.norm(str(current['title'] if field=='title' else current['metadata'].get(field)))!=bibliography.norm(str(record[field]))]
                    if conflicts:report={**report,'state':'partial','reason':'locked_field_conflict','conflicting_fields':conflicts}
                    saved=bibliography.save(self.store,record)
                    from .acquisition_metadata import apply
                    current,_=apply(self.store,current,{'doi':saved.get('doi',''),'title':saved['title'],'authors':saved['authors'],'pdf_version':current['metadata'].get('pdf_version','unknown'),'citation_record':saved,'pdf_identity':check},
                        {'sha256':sha,'identity_check':check,'acquired_at':bibliography.stamp()},True)
                    bibliography.outcome(self.store,saved['id'],'acquired',resource_id=rid,pdf_version=current['metadata'].get('pdf_version','unknown'))
                prior=current['metadata'].get('metadata_status')
                status='verified' if report['state']=='verified' else 'partially_verified' if record else prior if prior=='verified' else 'needs_review'
                self.store.update_resource(rid,{'base_revision':current['revision'],'metadata_status':status,'metadata_verification':report,
                    **({'pdf_version':'unknown'} if not current['metadata'].get('pdf_version') else {}),
                    'field_sources':{'metadata_status':{'source':'automatic_import_verification','retrieved_at':report['checked_at']},'metadata_verification':{'source':'automatic_import_verification','retrieved_at':report['checked_at']}}})
                return report
            return await self.write('automatic_paper_metadata',{'operation_id':uid('op'),'resource_id':rid,'version_id':version},action)
        try:
            async with self.gate:
                at=time.perf_counter()
                evidence=await asyncio.to_thread(inspect_pdf,self.store.snapshot(resource),{**resource['metadata'],'title':resource['title'],**hints})
                timings['pdf_identity_ms']=round((time.perf_counter()-at)*1000,2)
                if evidence['sha256']!=sha:raise DomainError('hash_conflict',409)
                at=time.perf_counter()
                # Reuse only local verified records with intact immutable source evidence.
                known=bibliography.rows(self.store)
                for candidate in ([] if hints.get('refresh') else known):
                    if candidate.get('alias_of') or candidate.get('metadata_status')!='verified' or not candidate.get('latest_verified') or not bibliography.fresh(candidate.get('latest_checked_at'),300):continue
                    try:
                        path=self.store.project/candidate['evidence_path']
                        if digest(path)!=candidate['evidence_sha256']:continue
                        identity_check=identity(candidate,evidence)
                        if not evidence['dois'] and not evidence['arxiv_id']:
                            same=[r for r in known if not r.get('alias_of') and r.get('title')==candidate['title'] and r.get('authors')==candidate['authors']]
                            if len(same)!=1:continue
                        record=candidate;check=identity_check;cached=True;break
                    except (DomainError,OSError,KeyError):continue
                if not record:
                    # Bound the entire public lookup, including rate-limit waiting.
                    async def lookup():
                        if evidence['arxiv_id']:
                            value=await self.resolve(arxiv_id=evidence['arxiv_id'],refresh=hints.get('refresh',False));return value,identity(value,evidence)
                        # Prefer a header DOI confirmed by the caller when several identifiers occur.
                        identifiers=evidence['dois'];preferred=str(hints.get('doi') or resource['metadata'].get('doi') or '').lower()
                        if preferred in identifiers:identifiers=[preferred]+[v for v in identifiers if v!=preferred]
                        for identifier in identifiers[:2]:
                            value=await self.resolve(identifier,refresh=hints.get('refresh',False))
                            try:return value,identity(value,evidence)
                            except DomainError:continue
                        return await search_title(evidence)
                    record,check=await asyncio.wait_for(lookup(),35)
                timings['source_lookup_ms']=round((time.perf_counter()-at)*1000,2)
                previous=resource['metadata'].get('metadata_verification',{})
                if cached and previous.get('state')=='verified' and previous.get('version_id')==version and previous.get('sha256')==sha and all(
                    not record.get(k) or bibliography.norm(str(resource['title'] if k=='title' else resource['metadata'].get(k)))==bibliography.norm(str(record[k])) for k in bibliography.FIELDS):
                    return {**previous,'source_reused':True,'timings_ms':{**timings,'total_ms':round((time.perf_counter()-started)*1000,2)}}
                missing=[k for k in ['title','authors','year','venue','source_type'] if not record.get(k)]
                conflicts=[]
                locks=resource['metadata'].get('field_sources',{})
                for field in bibliography.FIELDS:
                    old=resource['title'] if field=='title' else resource['metadata'].get(field)
                    if locks.get(field,{}).get('locked') and old and record.get(field) and bibliography.norm(str(old))!=bibliography.norm(str(record[field])):conflicts.append(field)
                report={'state':'partial' if missing or conflicts or record.get('metadata_status')!='verified' else 'verified','reason':'locked_field_conflict' if conflicts else 'missing_fields' if missing else 'verified_source_reused' if cached else 'public_source_verified',
                        'checked_at':bibliography.stamp(),'source_url':record['source_url'],'missing_fields':missing,'conflicting_fields':conflicts,'identity_basis':check['basis'],
                        'source_reused':cached,'version_id':version,'sha256':sha,'timings_ms':{**timings,'total_ms':round((time.perf_counter()-started)*1000,2)}}
                return await commit(report,record,check)
        except asyncio.CancelledError:raise
        except (DomainError,TimeoutError,OSError,ValueError,KeyError,TypeError) as exc:
            timings.setdefault('source_lookup_ms',round((time.perf_counter()-at)*1000,2))
            reason=exc.code if isinstance(exc,DomainError) else 'citation_source_timeout' if isinstance(exc,TimeoutError) else 'citation_source_invalid'
            state='source_unavailable' if reason in {'citation_source_unavailable','citation_source_timeout'} else 'identity_conflict' if 'identity' in reason else 'needs_review'
            report={'state':state,'reason':reason,'checked_at':bibliography.stamp(),'missing_fields':[], 'version_id':version,'sha256':sha,'timings_ms':{**timings,'total_ms':round((time.perf_counter()-started)*1000,2)}}
            if isinstance(exc,DomainError) and isinstance(exc.params.get('http_status'),int):report['http_status']=exc.params['http_status']
            return await commit(report)

    async def close(self):
        jobs=[*self.pending.values(),*self.lookups.values()]
        for task in jobs:task.cancel()
        await asyncio.gather(*jobs,return_exceptions=True)
