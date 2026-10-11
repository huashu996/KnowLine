"""Validated literature relationships, produced by the current Codex session."""
import json
import math
import re
from difflib import SequenceMatcher
from urllib.parse import urlsplit
from .safety import DomainError, contained, digest


def source(value):
    if not isinstance(value, dict):
        raise DomainError('graph_source_required')
    url=value.get('url', '')
    if not isinstance(url,str) or urlsplit(url).scheme not in {'http','https'} or not urlsplit(url).hostname or not isinstance(value.get('retrieved_at'),str) or len(value['retrieved_at'])<10:
        raise DomainError('graph_source_required')


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
        source_doi=_normalized(entry.get('source_doi','').split('doi.org/')[-1])
        original_doi=_normalized(original.get('doi',''))
        title_score=SequenceMatcher(None,_normalized(original['title']),_normalized(entry.get('source_title',''))).ratio()
        original_author=original['authors'][0]
        if isinstance(original_author,dict):original_author=original_author.get('family') or original_author.get('name') or ''
        surname=str(original_author).strip().split()[-1].casefold()
        source_authors=entry.get('source_authors')
        if not isinstance(source_authors,list) or not surname or not any(surname in str(name).casefold() for name in source_authors[:5]):raise DomainError('citation_identity_mismatch')
        if title_score<.55 or (original_doi and original_doi!=source_doi and title_score<.85):raise DomainError('citation_identity_mismatch')
        if original_doi and original_doi!=source_doi and entry.get('match_basis')!='title_author':raise DomainError('citation_identity_mismatch')
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
    from .research_enrich import display
    return display(store,graph)
