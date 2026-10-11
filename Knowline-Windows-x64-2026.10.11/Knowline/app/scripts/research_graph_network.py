"""Bounded, evidence-only citation expansion. Never writes resources or tasks.

Input graph + citation-audit from research_fetch_citations.py. Emits all selected-pair
citations and a bounded pool of referenced papers reachable through non-origin nodes.
Codex still reviews topical relevance/identity and decides which nodes to include.
"""
import hashlib,json,re,sys
from collections import Counter,deque
from pathlib import Path

POLICY='topical-multihop-real-citations-v2'
def doi(value):return re.sub(r'^https?://(?:dx\.)?doi\.org/','',str(value or '').strip(),flags=re.I).casefold()

def prepare(graph,audit,limit=60):
    nodes={n['id']:n for n in graph['nodes']};by_doi={doi(n.get('doi')):n['id'] for n in graph['nodes'] if n.get('doi')}
    edges=list(graph['edges']);seen={(e['source'],e['target'],e['kind']) for e in edges};pool={};coverage=[]
    for row in audit.get('rows',[]):
        node=nodes.get(row.get('node_id'))
        if not node:continue
        expected=doi(row.get('source_doi') or node.get('doi'));works=[]
        for attempt in row.get('attempts',[]):
            for response in [attempt.get('response'),(attempt.get('retry') or {}).get('response')]:
                if not isinstance(response,dict):continue
                message=response.get('message',{});candidates=message.get('items',[]) if 'items' in message else [message]
                works.extend((c,attempt) for c in candidates if expected and doi(c.get('DOI'))==expected)
        covered=False
        for work,attempt in works:
            if not isinstance(work.get('reference'),list):continue
            covered=True
            for ref in work['reference']:
                target_doi=doi(ref.get('DOI') or ref.get('doi'))
                if not target_doi:continue
                evidence={'url':'https://api.crossref.org/works/'+work['DOI'],'retrieved_at':attempt['retrieved_at'],
                          'source_record_doi':work['DOI'],'target_doi':target_doi,'reference':ref}
                target=by_doi.get(target_doi);key=(node['id'],target,'citation')
                if target and target!=node['id'] and key not in seen:
                    seen.add(key);edges.append({'id':'ref_'+hashlib.sha256(repr(key).encode()).hexdigest()[:16],
                                              'source':node['id'],'target':target,'kind':'citation','weight':1,'evidence':[evidence]})
                elif not target and node['id']!=graph['origin_id']:
                    item=pool.setdefault(target_doi,{'doi':target_doi,'via_node_ids':[],'reference_evidence':[]})
                    if node['id'] not in item['via_node_ids']:item['via_node_ids'].append(node['id'])
                    if len(item['reference_evidence'])<4:item['reference_evidence'].append(evidence)
        coverage.append({'node_id':node['id'],'reference_list_available':covered})
    # Distance is only a real-citation reachability diagnostic, never relevance.
    adjacent={id:set() for id in nodes}
    for e in edges:
        if e['kind']=='citation':adjacent[e['source']].add(e['target']);adjacent[e['target']].add(e['source'])
    distance={graph['origin_id']:0};queue=deque(distance)
    while queue:
        source=queue.popleft()
        for target in adjacent[source]:
            if target not in distance:distance[target]=distance[source]+1;queue.append(target)
    candidates=sorted(pool.values(),key=lambda p:(-len(p['via_node_ids']),p['doi']))[:max(0,min(80,limit))]
    revised={**graph,'edges':edges,'network_policy':POLICY}
    report={'policy':POLICY,'selected_nodes':len(nodes),'citation_edges':sum(e['kind']=='citation' for e in edges),
            'added_real_edges':len(edges)-len(graph['edges']),'reference_coverage':coverage,
            'indirect_nodes':[{'id':id,'title':nodes[id]['title'],'citation_hops':hops} for id,hops in distance.items() if hops>=2],
            'unconnected_node_ids':[id for id in nodes if id not in distance],
            'candidate_pool':candidates,'candidate_limit':min(80,limit),
            'requires_topical_and_identity_review':True,'no_origin_edge_required':True,
            'no_new_nodes_automatically_added':True,'remaining_references_truncated':max(0,len(pool)-len(candidates))}
    return revised,report

def main():
    path=Path(sys.argv[1]).resolve(strict=True);audit=json.loads((path.parent/'citation-audit.json').read_text('utf-8-sig'))
    graph=json.loads(path.read_text('utf-8-sig'));revised,report=prepare(graph,audit,int(sys.argv[2]) if len(sys.argv)>2 else 60)
    for name,value in [('paper-network-candidates.json',report),('paper-graph-network-audited.json',revised)]:
        (path.parent/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'candidate_pool','reference_coverage'}},ensure_ascii=False))
if __name__=='__main__':main()
