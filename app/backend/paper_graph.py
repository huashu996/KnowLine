"""Validated literature relationships, produced by the current Codex session."""
import json
import math
import re
import hashlib
import unicodedata
from functools import lru_cache
from collections import deque
from difflib import SequenceMatcher
from urllib.parse import urlsplit, unquote
from .safety import DomainError, contained, digest


def source(value):
    if not isinstance(value, dict):
        raise DomainError('graph_source_required')
    url=value.get('url', '')
    if not isinstance(url,str) or urlsplit(url).scheme not in {'http','https'} or not urlsplit(url).hostname or not isinstance(value.get('retrieved_at'),str) or len(value['retrieved_at'])<10:
        raise DomainError('graph_source_required')


def canonical_doi(value):
    """Keep DOI punctuation; only strip a DOI label or resolver URL."""
    value=str(value or '').strip()
    if re.match(r'^https?://(?:dx\.)?doi\.org/',value,re.I):
        value=unquote(urlsplit(value).path.lstrip('/'))
    value=re.sub(r'^doi\s*:\s*','',value,flags=re.I)
    return value.strip().casefold()


def audit_records(node,row):
    """Recognize exact-source Crossref and S2 records without guessing identity."""
    expected=canonical_doi(node.get('doi'));records=[];seen=set()
    for attempt in row.get('attempts',[]):
        for item in [attempt,attempt.get('retry') or {}]:
            response=item.get('response')
            if not isinstance(response,dict):continue
            message=response.get('message')
            works=(message.get('items',[]) if 'items' in message else [message]) if isinstance(message,dict) else response.get('results',[response])
            openalex_dois={work.get('id'):canonical_doi(work.get('doi')) for work in works if isinstance(work,dict) and work.get('id') and work.get('doi')}
            for work in works:
                if not isinstance(work,dict):continue
                identifier=canonical_doi(work.get('DOI') or (work.get('externalIds') or {}).get('DOI') or (work.get('doi') if item.get('provider')=='OpenAlex' else None))
                if not expected or identifier!=expected:continue
                provider='OpenAlex' if item.get('provider')=='OpenAlex' else 'Crossref' if 'DOI' in work else 'Semantic Scholar'
                refs=work.get('reference') if provider=='Crossref' else work.get('referenced_works') if provider=='OpenAlex' else work.get('references')
                if not isinstance(refs,list):continue
                if provider=='OpenAlex':refs=[{'openalex_work_id':ref,**({'DOI':openalex_dois[ref]} if openalex_dois.get(ref) else {})} for ref in refs if isinstance(ref,str)]
                key=(provider,identifier,json.dumps(refs,sort_keys=True,ensure_ascii=False))
                if key in seen:continue
                seen.add(key)
                records.append({'provider':provider,'work':work,'references':refs,'attempt':item,
                    'url':item.get('url') or attempt.get('url') or 'https://api.crossref.org/works/'+identifier,
                    'retrieved_at':item.get('retrieved_at') or attempt.get('retrieved_at') or row.get('citation_source',{}).get('retrieved_at','')})
    return records


def coverage_annotations(graph,audit=None,supplemental_records=None):
    """A read-only view: counts and references are different coverage gates."""
    rows={row.get('node_id'):row for row in (audit or {}).get('rows',[]) if isinstance(row,dict)}
    enriched=[];coverage=[]
    for node in graph['nodes']:
        row=rows.get(node['id'],{});records=audit_records(node,row)+list((supplemental_records or {}).get(node['id'],[]));footprints=[]
        for attempt in row.get('attempts',[]):
            url=str(attempt.get('url') or '')
            provider=attempt.get('provider') or ('Semantic Scholar' if 'semanticscholar.org' in url else 'Crossref' if 'crossref.org' in url or isinstance((attempt.get('response') or {}).get('message'),dict) else 'Unknown')
            code=attempt.get('http_status',attempt.get('status'))
            status='checked' if any(record['attempt'] is attempt or record['attempt'] is attempt.get('retry') for record in records) else 'rate_limited' if code==429 else 'unavailable' if attempt.get('error') or isinstance(code,int) and code>=400 else 'identity_unverified'
            footprints.append({'provider':provider,'status':status,'url':url,'retrieved_at':attempt.get('retrieved_at'),
                'request_sent':attempt.get('request_sent',bool(attempt.get('response') is not None or isinstance(code,int))),
                **({'http_status':code} if isinstance(code,int) else {}),
                **({'reason':attempt['error']} if attempt.get('error') else {})})
        for provider in ('Crossref','Semantic Scholar'):
            if not any(item['provider']==provider for item in footprints):
                footprints.append({'provider':provider,'status':'not_checked','request_sent':False})
        for record in (supplemental_records or {}).get(node['id'],[]):
            footprints.append({'provider':record['provider'],'status':'checked','url':record['url'],
                'retrieved_at':record['retrieved_at'],'request_sent':False,'resource_id':record['resource_id'],'resource_sha256':record['resource_sha256']})
        count=node.get('citation_count');provenance=node.get('citation_source')
        valid_count=isinstance(count,int) and not isinstance(count,bool) and count>=0 and isinstance(provenance,dict) and bool(provenance.get('url'))
        count_status='verified' if valid_count else 'query_incomplete' if any(item['status'] in {'rate_limited','unavailable'} for item in footprints) else 'unknown'
        refs_checked=any(record['references'] for record in records);reference_count=sum(len(record['references']) for record in records)
        crossref_missing=sum(not(ref.get('DOI') or ref.get('doi')) for record in records if record['provider']=='Crossref' for ref in record['references'] if isinstance(ref,dict))
        details={'node_id':node['id'],'references_checked':refs_checked,
            'references_status':'checked' if refs_checked else 'source_returned_no_references' if records else 'query_incomplete' if any(item['status'] in {'rate_limited','unavailable'} for item in footprints) else 'not_checked',
            'reference_count':reference_count,'references_without_doi':crossref_missing,'reference_sources':footprints,
            'citation_count_status':count_status}
        coverage.append(details);enriched.append({**node,**{k:v for k,v in details.items() if k!='node_id'}})
    network={**(graph.get('network_audit') or {}),'selected_nodes':len(enriched),
        'reference_coverage':coverage,'references_checked_nodes':sum(row['references_checked'] for row in coverage),
        'references_unchecked_node_ids':[row['node_id'] for row in coverage if not row['references_checked']],
        'citation_counts_verified':sum(row['citation_count_status']=='verified' for row in coverage),
        'coverage_is_not_exhaustive':True,'citation_counts_are_not_reference_lists':True}
    return {**graph,'nodes':enriched,'network_audit':network}


def _title(value):
    return re.sub(r'[^\w]+','',str(value or '').casefold())


def _name(value):
    return value if isinstance(value,str) else ' '.join(str(value.get(key,'')) for key in ('given','family'))


def _arxiv(value):
    match=re.search(r'(?:arxiv\s*[:/]|arxiv\.org/(?:abs|pdf)/)(\d{4}\.\d{4,5})(?:v\d+)?',str(value),re.I)
    return 'arxiv:'+match[1] if match else None


def _reference_text(value):
    return _title(''.join(c for c in unicodedata.normalize('NFKD',str(value or '')) if not unicodedata.combining(c)))


def _reference_author(value,author):
    def words(text):
        return re.sub(r'[^\w]+',' ',''.join(c for c in unicodedata.normalize('NFKD',str(text)).casefold() if not unicodedata.combining(c))).strip()
    surname=words(_name(author).split()[-1]);text=words(value)
    return bool(surname and re.search(r'(?<!\w)'+re.escape(surname)+r'(?!\w)',text))


def _match_reference(ref,nodes,by_doi,aliases):
    """Exact identifiers or an unambiguous full bibliographic entry, never a search snippet."""
    ids=ref.get('externalIds') or {};doi=canonical_doi(ref.get('DOI') or ref.get('doi') or ids.get('DOI'))
    target=by_doi.get(doi);basis='exact_reference_doi';alias=None
    text=str(ref.get('unstructured') or '')
    if not doi and text:
        found={node_id for candidate,node_id in by_doi.items() if re.search(r'(?<![\w/])'+re.escape(candidate)+r'(?=$|[\s.,;:)\]])',text,re.I)}
        if len(found)==1:target=found.pop();basis='exact_reference_doi_in_text'
    arxiv=_arxiv('arxiv:'+str(ids['ArXiv'])) if ids.get('ArXiv') else _arxiv(str(ref))
    if doi.startswith('10.48550/arxiv.'):arxiv=_arxiv('arxiv:'+doi.split('arxiv.',1)[1])
    if not target and arxiv and arxiv in aliases and (not doi or doi.startswith('10.48550/arxiv.')):
        alias=aliases[arxiv];target=alias['node_id'];basis='verified_publication_version_alias'
    if not target and not doi and not arxiv:
        title=ref.get('article-title') or ref.get('title');author=ref.get('author')
        if not author and ref.get('authors'):author=' '.join(_name(a) if isinstance(a,str) or 'name' not in a else a['name'] for a in ref['authors'])
        year=ref.get('year');matches=[]
        for candidate in nodes.values():
            candidate_title=_reference_text(candidate['title'])
            structured=bool(title and _reference_text(title)==candidate_title and author and _reference_author(author,candidate['authors'][0]) and str(year)==str(candidate['year']))
            unstructured=bool(text and len(candidate_title)>=15 and candidate_title in _reference_text(text) and _reference_author(text,candidate['authors'][0]) and re.search(r'(?<!\d)'+str(candidate['year'])+r'(?!\d)',text))
            if structured or unstructured:matches.append(candidate['id'])
        if len(matches)==1:target=matches[0];basis='exact_reference_title_author_year'
    return target,doi,arxiv,basis,alias


@lru_cache(maxsize=64)
def _pdf_reference_entries(path,sha256):
    """Parse only a numbered reference section of a file whose hash was checked by the caller."""
    from .pdf import open_pdf
    pages=[]
    with open_pdf(path) as doc:
        for index in range(max(0,len(doc)-12),len(doc)):
            pages.append((index,doc[index].get_text()[:60000]))
    text='\n'.join(value for _,value in pages)
    headings=list(re.finditer(r'(?im)^\s*(?:references|bibliography|参考文献)\s*$',text))
    if not headings:return ()
    start=headings[-1].end();section=text[start:start+200000]
    markers=list(re.finditer(r'(?m)^\s*(?:\[\d{1,4}\]|\d{1,4}[.)])\s+',section))
    entries=[]
    for index,marker in enumerate(markers[:400]):
        end=markers[index+1].start() if index+1<len(markers) else len(section)
        entry=section[marker.end():end].strip()
        if not entry or len(entry)>4000:continue
        offset=start+marker.start();page_index=pages[0][0];position=0
        for page,value in pages:
            if offset<position+len(value)+1:page_index=page;break
            position+=len(value)+1
        entries.append({'unstructured':re.sub(r'(?<=\w)-\s*\n\s*(?=\w)','',entry),'pdf_page_index':page_index})
    return tuple(entries)


def verified_pdf_references(store,graph,records):
    """Supplement relationships from already verified same-instance PDFs; no network or writes."""
    from .graph_fulltext import verified_resources
    from .research_enrich import matching
    result={}
    for node in graph['nodes']:
        record=matching(node,records,store,max_age=None)
        for resource in verified_resources(store,node,record)[:1]:
            metadata=resource.get('metadata') or {};version=metadata.get('pdf_version_basis') or {}
            url=version.get('url') or metadata.get('source_url') or (record or {}).get('publisher_url')
            retrieved=version.get('retrieved_at') or metadata.get('acquired_at') or (record or {}).get('latest_checked_at')
            try:
                source({'url':url,'retrieved_at':retrieved})
                refs=_pdf_reference_entries(str(store.snapshot(resource)),resource['sha256'])
            except (DomainError,OSError,ValueError,KeyError):continue
            if refs:result.setdefault(node['id'],[]).append({'provider':'Verified PDF','references':refs,'attempt':{},
                'url':url,'retrieved_at':retrieved,'resource_id':resource['id'],'resource_sha256':resource['sha256']})
    return result


def verified_record_identifiers(graph,records,project):
    """Only hash-checked, same-instance publication evidence grants aliases."""
    nodes={canonical_doi(node.get('doi')):node for node in graph['nodes'] if node.get('doi')};aliases=[]
    for record in records or []:
        node=nodes.get(canonical_doi(record.get('doi')))
        if not node or record.get('alias_of') or record.get('metadata_status')!='verified' or not record.get('latest_verified'):continue
        if _title(record.get('title'))!=_title(node['title']) or [_title(_name(a)) for a in record.get('authors',[])]!=[_title(_name(a)) for a in node['authors']]:continue
        try:
            path=contained(project,record['evidence_path'])
            if digest(path)!=record['evidence_sha256'] or path.stat().st_size>2*1024*1024:continue
            proof=json.loads(path.read_text('utf-8-sig'))
        except (KeyError,OSError,ValueError,DomainError):continue
        proofs=[(proof,record['evidence_path'],record['evidence_sha256'])]
        # A metadata refresh may move repository identity into an immutable
        # bridge proof. Follow only the record's named, hash-addressed proofs.
        for bridge in proof.get('bridge_evidence_paths',[])[:20]:
            try:
                bridge_path=contained(project,bridge)
                match=re.fullmatch(r'citation-([0-9a-f]{64})\.json',bridge_path.name)
                if not match or digest(bridge_path)!=match[1] or bridge_path.stat().st_size>2*1024*1024:continue
                proofs.append((json.loads(bridge_path.read_text('utf-8-sig')),bridge,match[1]))
            except (OSError,ValueError,DomainError):continue
        for proof,proof_path,proof_sha in proofs:
            if canonical_doi(proof.get('doi'))!=canonical_doi(node['doi']):continue
            for identity in proof.get('identity_evidence',[]):
                _append_verified_alias(aliases,node,record,proof,identity,proof_path,proof_sha)
    return aliases


def _append_verified_alias(aliases,node,record,proof,identity,proof_path,proof_sha):
    # This proof is already hash-checked by verified_record_identifiers.
    identifier=_arxiv(identity.get('identity_key') or identity.get('url') or '')
    if not identifier or identifier not in record.get('related_identifiers',[]) or identifier not in proof.get('related_identifiers',[]):return
    relationship=identity.get('relationship')
    if relationship not in {'repository_declared_doi','existing_verified_identifier_link','exact_title_all_authors_unique_repository_record'}:return
    if identity.get('formal_doi') and canonical_doi(identity['formal_doi'])!=canonical_doi(node['doi']):return
    if relationship=='exact_title_all_authors_unique_repository_record' and (_title(identity.get('title'))!=_title(node['title']) or [_title(_name(a)) for a in identity.get('authors',[])]!=[_title(_name(a)) for a in node['authors']]):return
    evidence={'url':identity.get('url') or identity.get('source_url'),'retrieved_at':identity.get('retrieved_at'),
        'relationship':relationship,'publication_record_id':record['id'],'evidence_path':proof_path,
        'evidence_sha256':proof_sha,'registered_formal_doi':node['doi']}
    try:source(evidence)
    except DomainError:return
    aliases.append({'node_id':node['id'],'identifier':identifier,'formal_doi':node['doi'],'verified':True,'evidence':[evidence]})


def verified_resource_identifiers(graph,records,resources,project):
    """Reuse an already validated file identity; never wait for a new PDF."""
    nodes={canonical_doi(node.get('doi')):node for node in graph['nodes'] if node.get('doi')}
    by_id={record.get('id'):record for record in records or []};aliases=[]
    for resource in resources or []:
        metadata=resource.get('metadata') or {};record=by_id.get(metadata.get('publication_record_id'))
        node=nodes.get(canonical_doi(metadata.get('doi')));identity=metadata.get('pdf_identity') or {}
        identifier=_arxiv('arxiv:'+str(identity.get('arxiv_id') or ''))
        if not node or not record or not identifier or resource.get('state')!='ready' or resource['id'] not in record.get('resource_ids',[]) or identifier not in record.get('related_identifiers',[]):continue
        if record.get('metadata_status')!='verified' or not record.get('latest_verified') or canonical_doi(record.get('doi'))!=canonical_doi(node['doi']):continue
        if identity.get('basis')!='header_title_authors_identifier' or _title(identity.get('title'))!=_title(node['title']) or [_title(_name(a)) for a in identity.get('authors',[])]!=[_title(_name(a)) for a in node['authors']]:continue
        verification=metadata.get('metadata_verification') or {};version=metadata.get('pdf_version_basis') or {}
        if verification.get('state')!='verified' or verification.get('sha256')!=resource.get('sha256') or _arxiv(version.get('url',''))!=identifier:continue
        try:
            record_path=contained(project,record['evidence_path']);file=contained(project,resource['path'])
            if digest(record_path)!=record['evidence_sha256'] or digest(file)!=resource['sha256']:continue
            proof=json.loads(record_path.read_text('utf-8-sig'))
            if canonical_doi(proof.get('doi'))!=canonical_doi(node['doi']) or _title(proof.get('title'))!=_title(node['title']) or [_title(_name(a)) for a in proof.get('authors',[])]!=[_title(_name(a)) for a in node['authors']]:continue
            evidence={'url':version['url'],'retrieved_at':version.get('retrieved_at') or metadata.get('acquired_at'),
                'relationship':'verified_import_pdf_identity_and_formal_record','publication_record_id':record['id'],
                'resource_id':resource['id'],'resource_sha256':resource['sha256'],'evidence_path':record['evidence_path'],
                'evidence_sha256':record['evidence_sha256'],'registered_formal_doi':node['doi']}
            source(evidence)
        except (KeyError,OSError,ValueError,DomainError):continue
        aliases.append({'node_id':node['id'],'identifier':identifier,'formal_doi':node['doi'],'verified':True,'evidence':[evidence]})
    return aliases


def _edge_key(source_id,target_id,kind):
    if kind!='citation':source_id,target_id=sorted((source_id,target_id))
    return source_id,target_id,kind


def _reference_identifier(reference,aliases):
    ids=reference.get('externalIds') or {}
    doi=canonical_doi(reference.get('DOI') or reference.get('doi') or ids.get('DOI'))
    arxiv=_arxiv('arxiv:'+str(ids['ArXiv'])) if ids.get('ArXiv') else _arxiv(str(reference))
    if doi.startswith('10.48550/arxiv.'):
        arxiv=_arxiv('arxiv:'+doi.split('arxiv.',1)[1])
    if re.fullmatch(r'10\.\d{4,9}/\S+',doi) and not doi.startswith('10.48550/arxiv.'):return 'doi:'+doi
    if arxiv and arxiv in aliases:return 'doi:'+canonical_doi(aliases[arxiv]['formal_doi'])
    if arxiv and (not doi or doi.startswith('10.48550/arxiv.')):return arxiv
    return 'doi:'+doi if re.fullmatch(r'10\.\d{4,9}/\S+',doi) else None


def _shared_relationships(nodes,edges,reference_sets,reference_proofs,citing_targets):
    """Generate co-citation only; shared-reference coupling is disabled."""
    seen={_edge_key(edge['source'],edge['target'],edge['kind']) for edge in edges}
    candidates=[];ids=sorted(nodes);citing_by_node={key:set() for key in nodes}
    for identity,targets in citing_targets.items():
        for target in targets:citing_by_node[target].add(identity)
    for index,left in enumerate(ids):
        for right in ids[index+1:]:
            common=sorted(citing_by_node[left]&citing_by_node[right]);key=(left,right,'co_citation')
            if common and key not in seen:
                evidence=[]
                for citing_id in common[:4]:
                    for target in (left,right):
                        proof=citing_targets[citing_id].get(target)
                        if proof:evidence.append({**proof,'citing_paper_identity':citing_id,'relationship_basis':'same_source_cites_both_selected_papers'})
                if evidence:
                    weight=len(common)/math.sqrt(len(citing_by_node[left])*len(citing_by_node[right]))
                    candidates.append({'id':'cocitation_'+hashlib.sha256(repr(key).encode()).hexdigest()[:16],
                        'source':left,'target':right,'kind':key[2],'directed':False,'weight':min(1,weight),
                        'weight_basis':'observed_common_citing_sources_cosine','shared_paper_ids':common[:100],
                        'common_citing_paper_count':len(common),'shared_identifiers_truncated':max(0,len(common)-100),'evidence':evidence})
    candidates.sort(key=lambda edge:(-edge['weight'],-max(edge.get('shared_reference_count',0),edge.get('common_citing_paper_count',0)),edge['kind'],edge['source'],edge['target']))
    remaining=max(0,10000-len(edges));kept=candidates[:remaining]
    return edges+kept,max(0,len(candidates)-len(kept))


def build_relationship_audit(graph,audit=None,verified_identifiers=None,limit=60,supplemental_records=None):
    """Build only relationships/coverage in memory; no downloads or business writes."""
    if len(graph.get('nodes',[]))>300 or len(graph.get('edges',[]))>10000:raise DomainError('invalid_paper_graph')
    graph=coverage_annotations(graph,audit,supplemental_records);nodes={node['id']:node for node in graph['nodes']}
    by_doi={canonical_doi(node['doi']):node['id'] for node in graph['nodes'] if node.get('doi')}
    aliases={};ambiguous=set()
    entries=list(verified_identifiers or [])
    for node in graph['nodes']:
        entries.extend({**entry,'node_id':node['id']} for entry in node.get('verified_identifiers',[]) if isinstance(entry,dict))
    for entry in entries:
        node=nodes.get(entry.get('node_id'));key=_arxiv(entry.get('identifier') or '')
        if not node or not key or entry.get('verified') is not True or canonical_doi(entry.get('formal_doi'))!=canonical_doi(node.get('doi')):continue
        evidence=entry.get('evidence')
        if not isinstance(evidence,list) or not evidence:continue
        try:
            for item in evidence:source(item)
        except DomainError:continue
        if key in aliases and aliases[key]['node_id']!=node['id']:ambiguous.add(key)
        else:aliases[key]=entry
    for key in ambiguous:aliases.pop(key,None)
    # Old registered graphs remain immutable. Derived views and new results omit
    # the relation type the user removed, without changing nodes or citations.
    edges=[edge for edge in graph['edges'] if edge['kind']!='bibliographic_coupling'];existing_edges=list(edges);seen={_edge_key(edge['source'],edge['target'],edge['kind']) for edge in edges}
    rows={row.get('node_id'):row for row in (audit or {}).get('rows',[]) if isinstance(row,dict)}
    pool={};unresolved=[];matched_without_doi=0;citation_edges_truncated=0
    reference_sets={key:set() for key in nodes};reference_proofs={key:{} for key in nodes};citing_targets={}
    for node in graph['nodes']:
        for record in audit_records(node,rows.get(node['id'],{}))+list((supplemental_records or {}).get(node['id'],[])):
            for raw in record['references']:
                if not isinstance(raw,dict):continue
                ref=raw.get('citedPaper',raw);ids=ref.get('externalIds') or {}
                target,target_doi,arxiv,basis,alias=_match_reference(ref,nodes,by_doi,aliases)
                if not target_doi:
                    if target:matched_without_doi+=1
                    else:unresolved.append({'node_id':node['id'],'provider':record['provider'],'reason':'publication_version_alias_unverified' if arxiv else 'reference_identifier_unresolved','reference':raw})
                evidence={'url':record['url'],'retrieved_at':record['retrieved_at'],'provider':record['provider'],
                    'source_record_doi':node.get('doi'),'target_doi':nodes[target].get('doi') if alias else target_doi or (nodes[target].get('doi') if target else None),
                    'reference':raw,'matched_basis':basis,'direction':'source_cites_target'}
                if alias:evidence['version_alias_evidence']=alias['evidence']
                if record.get('resource_id'):evidence.update(resource_id=record['resource_id'],resource_sha256=record['resource_sha256'],pdf_page_index=ref.get('pdf_page_index'))
                try:source(evidence)
                except DomainError:continue
                identifier=_reference_identifier(ref,aliases)
                if not identifier and target:identifier='doi:'+canonical_doi(nodes[target]['doi']) if nodes[target].get('doi') else 'node:'+target
                if identifier:
                    reference_sets[node['id']].add(identifier)
                    reference_proofs[node['id']].setdefault(identifier,evidence)
                citing_id=(_reference_identifier({'DOI':node['doi']},aliases) or 'doi:'+canonical_doi(node['doi'])) if node.get('doi') else 'node:'+node['id']
                if target and target!=node['id']:citing_targets.setdefault(citing_id,{}).setdefault(target,evidence)
                key=(node['id'],target,'citation')
                if target and target!=node['id'] and key not in seen and len(edges)<10000:
                    seen.add(key);edges.append({'id':'ref_'+hashlib.sha256(repr(key).encode()).hexdigest()[:16],
                        'source':node['id'],'target':target,'kind':'citation','weight':1,'evidence':[evidence]})
                elif target and target!=node['id'] and key not in seen:
                    seen.add(key);citation_edges_truncated+=1
                elif target_doi and not target and node['id']!=graph['origin_id']:
                    item=pool.setdefault(target_doi,{'doi':target_doi,'via_node_ids':[],'reference_evidence':[]})
                    if node['id'] not in item['via_node_ids']:item['via_node_ids'].append(node['id'])
                    if len(item['reference_evidence'])<4:item['reference_evidence'].append(evidence)
    # Exact source records outside the displayed set may prove co-citation,
    # without adding those papers as graph nodes or running another search.
    by_identity={identity:node_id for doi,node_id in by_doi.items() if (identity:=_reference_identifier({'DOI':doi},aliases))}
    for row_id,row in rows.items():
        if row_id in nodes:continue
        source_doi=canonical_doi(row.get('source_doi'))
        if not source_doi:continue
        for record in audit_records({'doi':source_doi},row):
            citing_id=_reference_identifier({'DOI':source_doi},aliases) or 'doi:'+source_doi
            for raw in record['references']:
                if not isinstance(raw,dict):continue
                reference=raw.get('citedPaper',raw);identifier=_reference_identifier(reference,aliases)
                target,_,_,basis,matched_alias=_match_reference(reference,nodes,by_doi,aliases)
                if not target:target=by_identity.get(identifier)
                if not target or identifier==citing_id:continue
                ref_arxiv=_arxiv(str(reference))
                ref_doi=canonical_doi(reference.get('DOI') or reference.get('doi') or (reference.get('externalIds') or {}).get('DOI'))
                if ref_doi.startswith('10.48550/arxiv.'):ref_arxiv=_arxiv('arxiv:'+ref_doi.split('arxiv.',1)[1])
                alias=matched_alias or (aliases.get(ref_arxiv) if not ref_doi or ref_doi.startswith('10.48550/arxiv.') else None)
                proof={'url':record['url'],'retrieved_at':record['retrieved_at'],'provider':record['provider'],
                    'source_record_doi':source_doi,'target_doi':nodes[target].get('doi'),'reference':raw,
                    'matched_basis':'verified_publication_version_alias' if alias else basis,
                    'direction':'source_cites_target'}
                if alias:proof['version_alias_evidence']=alias['evidence']
                try:source(proof)
                except DomainError:continue
                citing_targets.setdefault(citing_id,{}).setdefault(target,proof)
    edges,relations_truncated=_shared_relationships(nodes,edges,reference_sets,reference_proofs,citing_targets)
    adjacent={key:set() for key in nodes}
    for edge in edges:
        if edge['kind']=='citation' and edge['source'] in nodes and edge['target'] in nodes:
            adjacent[edge['source']].add(edge['target']);adjacent[edge['target']].add(edge['source'])
    # Citation acquisition may operate on a subset that excludes the origin.
    # Such a subset still has valid reference evidence; it has no origin hops.
    distance={graph['origin_id']:0} if graph.get('origin_id') in nodes else {};queue=deque(distance)
    while queue:
        origin=queue.popleft()
        for target in sorted(adjacent[origin]):
            if target not in distance:distance[target]=distance[origin]+1;queue.append(target)
    candidates=sorted(pool.values(),key=lambda item:(-len(item['via_node_ids']),item['doi']))[:max(0,min(80,limit))]
    resolution={key:sum(item['node_id']==key for item in unresolved) for key in nodes}
    graph={**graph,'nodes':[{**node,'references_unresolved_count':resolution[node['id']],
        'reference_resolution_status':'partial' if resolution[node['id']] else 'checked' if node['references_checked'] else 'not_checked'} for node in graph['nodes']]}
    coverage=[{**item,'references_unresolved_count':resolution[item['node_id']],
        'reference_resolution_status':'partial' if resolution[item['node_id']] else 'checked' if item['references_checked'] else 'not_checked'} for item in graph['network_audit']['reference_coverage']]
    kinds=('citation','bibliographic_coupling','co_citation','semantic_similarity')
    relation_counts={kind:sum(edge['kind']==kind for edge in edges) for kind in kinds}
    added_by_kind={kind:relation_counts[kind]-sum(edge['kind']==kind for edge in existing_edges) for kind in kinds}
    report={**graph['network_audit'],'policy':'topical-multihop-real-citations-v2','citation_edges':relation_counts['citation'],
        'bibliographic_coupling_edges':relation_counts['bibliographic_coupling'],'co_citation_edges':relation_counts['co_citation'],
        'semantic_similarity_edges':relation_counts['semantic_similarity'],'relationship_counts':relation_counts,
        'total_relationship_edges':len(edges),'added_edges_by_kind':added_by_kind,'relationship_edges_truncated':relations_truncated+citation_edges_truncated,
        'citation_edges_truncated':citation_edges_truncated,
        'relationship_policy':'evidence-citation-cocitation-v2','semantic_edges_preserved_not_generated':True,
        'disabled_relationship_types':['bibliographic_coupling'],'origin_in_selected_nodes':graph.get('origin_id') in nodes,
        'reference_coverage':coverage,
        'added_real_edges':len(edges)-len(existing_edges),'omitted_shared_reference_edges':len(graph['edges'])-len(existing_edges),'matched_references_without_doi':matched_without_doi,
        'unresolved_reference_count':len(unresolved),'unresolved_references':unresolved[:80],
        'indirect_nodes':[{'id':key,'title':nodes[key]['title'],'citation_hops':hops} for key,hops in distance.items() if hops>=2],
        'unconnected_node_ids':[key for key in nodes if key not in distance],'candidate_pool':candidates,'candidate_limit':min(80,max(0,limit)),
        'requires_topical_and_identity_review':True,'no_origin_edge_required':True,'no_new_nodes_automatically_added':True,
        'remaining_references_truncated':max(0,len(pool)-len(candidates)),'unresolved_details_truncated':max(0,len(unresolved)-80)}
    return {**graph,'edges':edges,'network_policy':report['policy'],'network_audit':report},report


def validate(graph, scope):
    if not isinstance(graph,dict) or graph.get('schema_version')!=1:
        raise DomainError('invalid_paper_graph')
    nodes,edges=graph.get('nodes'),graph.get('edges')
    if not isinstance(nodes,list) or not 1<=len(nodes)<=300 or not isinstance(edges,list) or len(edges)>10000:
        raise DomainError('invalid_paper_graph')
    if scope.get('target_count') is not None and len(nodes)>scope['target_count']+1:
        raise DomainError('graph_count_outside_scope')
    if scope.get('network_policy') and graph.get('network_policy')!=scope['network_policy']:
        raise DomainError('graph_network_audit_required')
    ids=set()
    for node in nodes:
        if not isinstance(node,dict) or not isinstance(node.get('id'),str) or not 1<=len(node['id'])<=200 or node['id'] in ids:
            raise DomainError('invalid_paper_graph')
        ids.add(node['id'])
        if not isinstance(node.get('title'),str) or not 1<=len(node['title'])<=1000 or not isinstance(node.get('authors'),list) or not node['authors'] or not isinstance(node.get('venue'),str):
            raise DomainError('graph_metadata_required')
        year=node.get('year')
        if isinstance(year,bool) or not isinstance(year,int) or not 1500<=year<=2200:
            raise DomainError('graph_metadata_required')
        if node['id']!=graph.get('origin_id') and not scope['from_year']<=year<=scope['to_year']:
            raise DomainError('graph_year_outside_scope')
        source(node.get('metadata_source'))
        if node.get('abstract'):
            if not isinstance(node['abstract'],str) or len(node['abstract'])>20000:raise DomainError('graph_metadata_required')
            source(node.get('abstract_source') or node.get('metadata_source'))
        count=node.get('citation_count')
        if count is not None:
            if isinstance(count,bool) or not isinstance(count,int) or not 0<=count<=100000000:
                raise DomainError('invalid_citation_count')
            source(node.get('citation_source'))
        if 'references_checked' in node and not isinstance(node['references_checked'],bool):
            raise DomainError('invalid_graph_coverage')
        if node.get('citation_count_status') not in {None,'verified','unknown','query_incomplete','identity_unverified'}:
            raise DomainError('invalid_graph_coverage')
        if node.get('citation_count_status')=='verified' and count is None:
            raise DomainError('invalid_graph_coverage')
        alternatives=node.get('citation_alternatives',[])
        if not isinstance(alternatives,list) or len(alternatives)>5:raise DomainError('invalid_citation_count')
        for alternative in alternatives:
            if not isinstance(alternative,dict) or isinstance(alternative.get('citation_count'),bool) or not isinstance(alternative.get('citation_count'),int) or not 0<=alternative['citation_count']<=100000000:raise DomainError('invalid_citation_count')
            source(alternative.get('citation_source'))
    if graph.get('origin_id') not in ids:
        raise DomainError('graph_origin_required')
    seen=set()
    for edge in edges:
        if not isinstance(edge,dict) or edge.get('source') not in ids or edge.get('target') not in ids or edge['source']==edge['target']:
            raise DomainError('invalid_graph_edge')
        key=(edge['source'],edge['target'],edge.get('kind'))
        if key in seen:raise DomainError('invalid_graph_edge')
        seen.add(key)
        if edge.get('kind') not in {'citation','bibliographic_coupling','co_citation','semantic_similarity'}:
            raise DomainError('invalid_graph_edge')
        weight=edge.get('weight')
        if isinstance(weight,bool) or not isinstance(weight,(int,float)) or not math.isfinite(weight) or not 0<=weight<=1:
            raise DomainError('invalid_graph_edge')
        evidence=edge.get('evidence')
        if not isinstance(evidence,list) or not evidence:raise DomainError('graph_source_required')
        for item in evidence:source(item)
        if edge['kind'] in {'bibliographic_coupling','co_citation'} and not edge.get('shared_paper_ids'):
            raise DomainError('graph_shared_papers_required')
    return graph


def _normalized(value):
    return re.sub(r'[^a-z0-9]+','',str(value).casefold())


def validate_citation_refresh(data,frozen):
    if not isinstance(data,dict) or data.get('schema_version')!=1 or data.get('graph_job_id')!=frozen['graph_job_id'] or not isinstance(data.get('entries'),list):
        raise DomainError('invalid_citation_refresh')
    expected={node['id']:node for node in frozen['nodes']}
    if {entry.get('node_id') for entry in data['entries'] if isinstance(entry,dict)}!=set(expected) or len(data['entries'])!=len(expected):
        raise DomainError('invalid_citation_refresh')
    for entry in data['entries']:
        original=expected[entry['node_id']]
        count=entry.get('citation_count')
        if count is None:
            if not isinstance(entry.get('reason'),str) or not entry['reason'].strip():raise DomainError('invalid_citation_refresh')
            continue
        if isinstance(count,bool) or not isinstance(count,int) or not 0<=count<=100000000:raise DomainError('invalid_citation_count')
        provenance=entry.get('citation_source')
        source(provenance)
        if not isinstance(provenance.get('provider'),str) or not provenance['provider'].strip():raise DomainError('graph_source_required')
        source_doi=canonical_doi(entry.get('source_doi',''))
        original_doi=canonical_doi(original.get('doi',''))
        title_score=SequenceMatcher(None,_normalized(original['title']),_normalized(entry.get('source_title',''))).ratio()
        original_author=original['authors'][0]
        if isinstance(original_author,dict):original_author=original_author.get('family') or original_author.get('name') or ''
        surname=str(original_author).strip().split()[-1].casefold()
        source_authors=entry.get('source_authors')
        if not isinstance(source_authors,list) or not surname or not any(surname in str(name).casefold() for name in source_authors[:5]):raise DomainError('citation_identity_mismatch')
        if title_score<.55:raise DomainError('citation_identity_mismatch')
        # A fixed DOI is an identity boundary. Title/author fallback cannot
        # replace a different publication's count in a frozen graph.
        if original_doi and original_doi!=source_doi:raise DomainError('citation_identity_mismatch')
    return data


def load(store,job):
    result=job.get('result') or {}
    path=result.get('paper_graph_artifact')
    artifact=next((a for a in result.get('artifacts',[]) if a['path']==path),None)
    if job['task']!='paper_relationships' or job['status'] not in {'completed','partial'} or not artifact:
        raise DomainError('paper_graph_not_ready')
    file=contained(store.project,path)
    if digest(file)!=artifact['sha256']:raise DomainError('artifact_hash_mismatch')
    graph=validate(json.loads(file.read_text('utf-8')),job['context']['literature_search'])
    for candidate in store.rows("SELECT id FROM jobs WHERE task='refresh_graph_citations' AND status='completed' ORDER BY updated_at DESC"):
        refresh=store.job(candidate['id'])
        frozen=refresh['context'].get('citation_refresh',{})
        if frozen.get('graph_job_id')!=job['id'] or frozen.get('graph_sha256')!=artifact['sha256']:continue
        updated=refresh['result'].get('citation_refresh_artifact')
        entry=next((a for a in refresh['result']['artifacts'] if a['path']==updated),None)
        if not entry:continue
        update_file=contained(store.project,updated)
        if digest(update_file)!=entry['sha256']:raise DomainError('artifact_hash_mismatch')
        citations=validate_citation_refresh(json.loads(update_file.read_text('utf-8')),frozen)
        by_id={row['node_id']:row for row in citations['entries']}
        enriched=[]
        for node in graph['nodes']:
            row=by_id[node['id']]
            enriched.append({**node,'citation_count':row.get('citation_count'),'citation_source':row.get('citation_source'),'citation_unknown_reason':row.get('reason')})
        graph={**graph,'nodes':enriched,'citation_refresh':{'job_id':refresh['id'],'updated_at':refresh['updated_at']}}
        graph=validate(graph,job['context']['literature_search'])
        break
    audit_path=result.get('citation_audit_artifact')
    if not audit_path:
        # Older native finalizers registered the audit but omitted its pointer.
        expected=file.parent/'citation-audit.json'
        audit_path=next((item['path'] for item in result.get('artifacts',[]) if contained(store.project,item['path'])==expected),None)
    audit_entry=next((item for item in result.get('artifacts',[]) if item.get('path')==audit_path),None)
    audit=None
    if audit_entry:
        audit_file=contained(store.project,audit_path)
        if digest(audit_file)!=audit_entry['sha256']:raise DomainError('artifact_hash_mismatch')
        if audit_file.stat().st_size<=16*1024*1024:
            audit=json.loads(audit_file.read_text('utf-8-sig'))
    from . import paper_bibliography as bibliography
    records=bibliography.rows(store)
    aliases=verified_record_identifiers(graph,records,store.project)
    aliases+=verified_resource_identifiers(graph,records,store.resources(),store.project)
    graph,_=build_relationship_audit(graph,audit,aliases,supplemental_records=verified_pdf_references(store,graph,records))
    from .research_enrich import display
    return display(store,graph)
