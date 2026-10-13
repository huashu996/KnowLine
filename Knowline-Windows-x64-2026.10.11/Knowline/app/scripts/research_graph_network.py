"""Evidence-only citation, shared-reference and co-citation relationship audit.

An optional verified-identifiers file binds verified publication-version aliases.
Year filtering belongs to node selection, not checking references between nodes
which have already passed the frozen graph scope validator.
Existing semantic relationships remain typed inferences; none are generated.
Coupling needs at least two identified common references; co-citation needs
an original source which cites both selected papers. No searches are added.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.paper_graph import build_relationship_audit,canonical_doi

POLICY='topical-multihop-real-citations-v2'
RELATIONSHIP_POLICY='evidence-citation-coupling-cocitation-v1'
doi=canonical_doi


def prepare(graph,audit,limit=60,verified_identifiers=None):
    return build_relationship_audit(graph,audit,verified_identifiers,limit)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('graph',type=Path)
    parser.add_argument('limit',type=int,nargs='?',default=60)
    parser.add_argument('--verified-identifiers',type=Path)
    args=parser.parse_args(argv);path=args.graph.resolve(strict=True)
    audit=json.loads((path.parent/'citation-audit.json').read_text('utf-8-sig'))
    aliases=json.loads(args.verified_identifiers.read_text('utf-8-sig')) if args.verified_identifiers else None
    if isinstance(aliases,dict):aliases=aliases.get('entries',[])
    graph=json.loads(path.read_text('utf-8-sig'));revised,report=prepare(graph,audit,args.limit,aliases)
    for name,value in [('paper-network-candidates.json',report),('paper-graph-network-audited.json',revised)]:
        (path.parent/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:value for key,value in report.items() if key not in {'candidate_pool','reference_coverage','unresolved_references'}},ensure_ascii=True))


if __name__=='__main__':main()
