"""Prepare one full-text plan from stable graph nodes without duplicate searches."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.layout import project_root
from backend.safety import atomic_json, contained


def prepare(context_path, graph_path):
    project = project_root(Path(__file__).resolve().parents[1])
    context = json.loads(contained(project, context_path).read_text('utf-8-sig'))
    output = contained(project, context['output_dir'])
    graph_path = contained(output, contained(project, graph_path))
    graph = json.loads(graph_path.read_text('utf-8-sig'))
    if context['task'] != 'paper_relationships' or graph.get('job_id', context['job_id']) != context['job_id']:
        raise ValueError('Graph task identity mismatch')
    papers = []
    for node in graph['nodes']:
        # Keep only sources already located by trusted discovery / identity
        # tools. The service owns authenticated lookup, fallback and file import.
        sources = node.get('download_sources') or []
        if not isinstance(sources, list):
            raise ValueError('Invalid source list')
        papers.append({'node_id': node['id'], 'doi': node.get('doi'),
                       'citation_record_id': node.get('citation_record_id'),
                       'sources': sources[:3], 'acquisition_status': 'pending_shared_service',
                       'query_coverage_status': 'not_checked_by_planner',
                       'actual_pdf_acquired': False})
    plan = {'schema_version': 1, 'job_id': context['job_id'], 'papers': papers,
            'source_lookup_owner': 'shared_service_once', 'duplicate_agent_lookup': False,
            'summary': {'papers': len(papers), 'actual_pdf_acquired_count': 0},
            'warnings': []}
    path = output / 'pdf-source-plan.json'
    atomic_json(path, plan)
    return {'plan': str(path), 'papers': len(papers), 'network_requests': 0,
            'acquisition': 'shared service performs exact-paper-fulltext-v6 once'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('context')
    parser.add_argument('graph')
    args = parser.parse_args()
    print(json.dumps(prepare(args.context, args.graph), ensure_ascii=False))
