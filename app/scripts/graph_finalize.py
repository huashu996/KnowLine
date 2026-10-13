"""Merge graph roles and create the result manifest through existing validators."""
import argparse
from collections import Counter
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.layout import project_root
from backend.paper_graph import build_relationship_audit, canonical_doi, validate
from backend.safety import atomic_json, contained, digest
from graph_pdf_plan import prepare as prepare_pdf_plan
from research_finalize import finalize


def finish(context_path, graph_path, plan_path=None):
    project = project_root(Path(__file__).resolve().parents[1])
    context_path = contained(project, context_path)
    context = json.loads(context_path.read_text('utf-8-sig'))
    zh = context.get('ui_locale') != 'en'
    output = contained(project, context['output_dir'])
    if context['task'] != 'paper_relationships':
        raise ValueError('This finalizer is only for paper relationship tasks')
    if (output / 'result.json').exists():
        raise ValueError('A result already exists; do not overwrite a published result')
    graph_path = contained(output, contained(project, graph_path))
    graph = json.loads(graph_path.read_text('utf-8-sig'))
    if graph.get('job_id', context['job_id']) != context['job_id']:
        raise ValueError('Graph belongs to another task')
    nodes = {node['id']: node for node in graph['nodes']}
    if len(nodes) != len(graph['nodes']) or graph.get('origin_id') not in nodes:
        raise ValueError('The final graph requires unique nodes and the origin')
    audit_path = output / 'citation-audit.json'
    audit = json.loads(audit_path.read_text('utf-8-sig'))
    graph, network = build_relationship_audit(graph, audit)
    graph['job_id'] = context['job_id']
    validate(graph, context['literature_search'])
    if plan_path is None:
        plan_path = output / 'pdf-source-plan.json'
        if not plan_path.exists():
            prepare_pdf_plan(context_path, graph_path)
    plan_path = contained(output, contained(project, plan_path))
    plan = json.loads(plan_path.read_text('utf-8-sig'))
    if plan.get('schema_version') != 1 or plan.get('job_id') != context['job_id']:
        raise ValueError('Invalid PDF plan identity')
    seen = set()
    for paper in plan.get('papers', []):
        node_id = paper.get('node_id') or paper.get('candidate_id')
        node = nodes.get(node_id)
        if node is None or node_id in seen or canonical_doi(paper.get('doi')) != canonical_doi(node.get('doi')):
            raise ValueError('PDF plan does not match the stable graph nodes')
        seen.add(node_id)
        sources = paper.get('sources', [])
        if not isinstance(sources, list) or len(sources) > 3:
            raise ValueError('Invalid PDF sources')
        # Identity, permissions, actual downloads and registration remain with
        # the existing service. A source URL never becomes a saved PDF here.
        next(node for node in graph['nodes'] if node['id'] == node_id)['download_sources'] = sources
    if seen != set(nodes):
        raise ValueError('PDF plan must cover every stable node exactly once')
    network_path = output / 'network-audit.json'
    atomic_json(network_path, network)
    final_path = output / context.get('output_filenames', {}).get('paper-graph.json', 'paper-graph.json')
    final_path = contained(output, final_path)
    atomic_json(final_path, graph)
    counts = Counter(edge['kind'] for edge in graph['edges'])
    unknown = [node['id'] for node in graph['nodes'] if node.get('citation_count') is None]
    unchecked = [node['id'] for node in graph['nodes'] if not node.get('references_checked')]
    warnings = list(dict.fromkeys(graph.get('warnings', []) + plan.get('warnings', [])))
    if unknown:
        warnings.append(f'{len(unknown)} 篇论文的被引次数未知，具体来源与原因已保留。' if zh else f'{len(unknown)} paper citation counts remain unknown; source reasons are retained.')
    if unchecked:
        warnings.append(f'{len(unchecked)} 篇论文的参考列表未核查，关系覆盖仍有缺项。' if zh else f'{len(unchecked)} reference lists remain unchecked; coverage is incomplete.')
    files = {final_path, audit_path, network_path, plan_path}
    # Collect only declared evidence paths within this task, never enumerate
    # the library, other tasks, logins or output directories recursively.
    def evidence(value):
        if isinstance(value, dict):
            for key in ('path', 'response_path', 'evidence_path', 'artifact_path'):
                name = value.get(key)
                if not isinstance(name, str):
                    continue
                try:
                    file = contained(output, contained(project, name))
                except Exception:
                    continue
                if file.is_file():
                    expected = value.get('response_sha256') if key == 'response_path' else value.get('evidence_sha256') if key == 'evidence_path' else value.get('sha256')
                    if expected and digest(file) != expected:
                        raise ValueError('Declared evidence changed: ' + file.name)
                    files.add(file)
            for child in value.values():
                evidence(child)
        elif isinstance(value, list):
            for child in value:
                evidence(child)
    for value in (graph, audit, plan):
        evidence(value)
    for name in ('discovery.json', 'public-citation-responses.json', 'research-preparation.json',
                 'field-research-memory.json', 'role-execution.json', 'pdf-source-artifacts.json'):
        file = output / name
        if file.is_file():
            files.add(file)
            if name in ('role-execution.json', 'pdf-source-artifacts.json'):
                evidence(json.loads(file.read_text('utf-8-sig')))
    summary = (f'{len(nodes)} 篇论文；{counts["citation"]} 条直接引用；{counts["co_citation"]} 条共同被引关系。' if zh else f'{len(nodes)} papers; {counts["citation"]} direct citations; {counts["co_citation"]} co-citations.')
    report_path = contained(output, output / context.get('output_filenames', {}).get('report.md', 'report.md'))
    if not report_path.exists():
        report_path.write_text(summary + '\n\n' + '\n'.join(warnings) + '\n', 'utf-8')
    files.add(report_path)
    analysis = {'schema_version': 2, 'job_id': context['job_id'], 'status': 'completed',
                'partial': bool(unknown or unchecked), 'title': context.get('literature_search', {}).get('query', 'Paper graph'),
                'summary': summary, 'paper_graph_artifact': final_path.relative_to(project).as_posix(),
                'citation_audit_artifact': audit_path.relative_to(project).as_posix(),
                'network_audit_artifact': network_path.relative_to(project).as_posix(),
                'artifacts': [{'path': file.relative_to(project).as_posix()} for file in sorted(files)],
                'claims': [], 'proposed_relations': [], 'warnings': warnings,
                'role_execution_artifact': (output / 'role-execution.json').relative_to(project).as_posix() if (output / 'role-execution.json').is_file() else None,
                'graph_workflow': {'version': 2, 'native_finalize': True, 'review_rounds': 1,
                                   'disabled_relationship_types': ['bibliographic_coupling'],
                                   'fulltext_lookup_owner': 'shared_service_once'}}
    analysis_path = output / 'graph-analysis.json'
    atomic_json(analysis_path, analysis)
    return finalize(context_path, analysis_path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('context')
    parser.add_argument('graph')
    parser.add_argument('--pdf-plan')
    args = parser.parse_args()
    print(json.dumps(finish(args.context, args.graph, args.pdf_plan), ensure_ascii=False))
