"""Citation acquisition CLI plus the reusable, network-free relationship worker.

The acquisition CLI's primary count provider is Crossref. Semantic Scholar is
only marked checked if its exact-DOI reference response is actually supplied.
The relationship view separately retains citation, bibliographic coupling,
co-citation and existing semantic-inference edges without mixing their counts.
"""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import citation_audit
from backend.paper_graph import build_relationship_audit,verified_record_identifiers,verified_resource_identifiers


def build_audit(graph,records=None,responses=None,project=None,resources=None):
    """Service entry point: merge existing evidence without any requests.

responses is citation-audit JSON (rows with node_id/attempts). records is the
instance's verified publication-record list; project verifies record evidence
paths/hashes before granting a publication-version alias.
Returns (graph_view, relationship_audit); frozen input and citation counts are
preserved. relationship_counts identifies each type rather than treating all
links as direct citations.
"""
    aliases=verified_record_identifiers(graph,records,project) if records and project else []
    if records and resources and project:aliases+=verified_resource_identifiers(graph,records,resources,project)
    return build_relationship_audit(graph,responses or {'rows':[]},aliases)


def main(argv=None):
    report=citation_audit.main(argv,quiet=True)
    path=Path(report['path']);audit=json.loads(path.read_text('utf-8-sig'))
    graph_path=Path((argv or sys.argv[1:])[0])
    graph=json.loads(graph_path.read_text('utf-8-sig'))
    _,network=build_audit(graph,responses=audit)
    coverage={row['node_id']:row for row in network['reference_coverage']}
    audit={**audit,'rows':[{**row,**{key:value for key,value in coverage.get(row['node_id'],{}).items() if key!='node_id'}} for row in audit['rows']],
        'relationship_coverage':network,'count_primary_provider':'Crossref','semantic_scholar_unchecked_unless_actual_response':True}
    path.write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({**report,'references_checked':network['references_checked_nodes']},ensure_ascii=True))
    return report


if __name__=='__main__':main()
