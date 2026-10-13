"""Finalize authored task manifests; evidence acceptance belongs to the public API."""
import copy
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.layout import project_root
from backend.safety import atomic_json, contained, digest


def normalize_proposal(result):
    """Rearrange supplied evidence/field aliases without inventing research content."""
    result=copy.deepcopy(result)
    for candidate in result.get('research_design',{}).get('candidates',[]):
        for nearest in candidate.get('novelty',{}).get('nearest',[]):
            key=nearest.get('source_key');evidence=nearest.get('evidence',[])
            primary=[e for e in evidence if isinstance(e,dict) and e.get('source_key')==key]
            if key and primary and all(isinstance(e,dict) and e.get('source_key') for e in evidence):
                for e in evidence:
                    if e not in primary and e not in candidate.setdefault('evidence',[]):candidate['evidence'].append(e)
                nearest['evidence']=primary
        comparison=candidate.get('experiment',{}).get('comparison_contract')
        if isinstance(comparison,dict):
            aliases=('same_data','same_split','same_budget')
            if 'identical' not in comparison and all(isinstance(comparison.get(k),str) and comparison[k].strip() for k in aliases):
                comparison['identical']=[comparison[k] for k in aliases]
            if 'failure_accounting' not in comparison and isinstance(comparison.get('same_reporting'),str):
                comparison['failure_accounting']=comparison['same_reporting']
    return result


def finalize(context_path, analysis_path):
    project = project_root(Path(__file__).resolve().parents[1])
    context_path = contained(project, context_path)
    context = json.loads(context_path.read_text('utf-8-sig'))
    output = contained(project, context['output_dir'])
    analysis_path = contained(output, contained(project, analysis_path))
    if context['task'] in {'build_knowledge', 'update_knowledge'}:
        raise ValueError('Use knowledge_finalize.py for knowledge tasks')
    result = json.loads(analysis_path.read_text('utf-8-sig'))
    if not isinstance(result, dict):
        raise ValueError('Analysis must be a manifest object')
    if result.get('status', 'completed') not in {'completed', 'partial'}:
        raise ValueError('Failed work must not be finalized as completed')
    if result.get('job_id', context['job_id']) != context['job_id']:
        raise ValueError('Job identity mismatch')
    result['partial'] = result.get('partial', False) or result.get('status') == 'partial'
    result.update(schema_version=2, job_id=context['job_id'], status='completed')
    for name in ('claims', 'proposed_relations', 'warnings'):
        result.setdefault(name, [])
        if not isinstance(result[name], list):
            raise ValueError(name + ' must be an array')
    artifacts = result.get('artifacts')
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError('At least one authored artifact is required')
    seen = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ValueError('Each artifact must be an object')
        path = contained(project, artifact['path'])
        path.relative_to(output)
        if path.name == 'result.json' or path in seen or not path.is_file() or path.stat().st_size > 32*1024*1024:
            raise ValueError('Invalid or duplicate artifact')
        seen.add(path)
        artifact['path'] = path.relative_to(project).as_posix()
        artifact['sha256'] = digest(path)
    if context['task']=='proposal_word' and isinstance(result.get('research_design'),dict):
        normalized=normalize_proposal(result)
        if normalized!=result:
            target=result.get('research_design_artifact')
            artifact=next((a for a in artifacts if a['path']==target),None)
            if not artifact:raise ValueError('Research design artifact is required')
            path=contained(output,contained(project,target))
            if json.loads(path.read_text('utf-8-sig'))!=result['research_design']:
                raise ValueError('Research design artifact mismatch')
            atomic_json(path,normalized['research_design'])
            result=normalized
            next(a for a in result['artifacts'] if a['path']==target)['sha256']=digest(path)
    if context['task'] in {'discover_papers', 'import_graph_papers'}:
        rows = result.get('imported_papers')
        if not isinstance(rows, list) or not rows:
            raise ValueError('imported_papers is required')
        ids = set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('candidate_id'), str) or not row['candidate_id'] or row['candidate_id'] in ids:
                raise ValueError('Candidate identities must be unique')
            ids.add(row['candidate_id'])
            if row.get('resource_id'):
                if not row.get('version_id') or not row.get('sha256'):
                    raise ValueError('Registered resources need a version and hash')
            elif not isinstance(row.get('unavailable_reason'), str) or not row['unavailable_reason'].strip():
                raise ValueError('Unavailable full text needs a reason')
        if context['task'] == 'import_graph_papers' and ids != {node['id'] for node in context['paper_graph_selection']['candidates']}:
            raise ValueError('Every frozen candidate must be accounted for')
    atomic_json(output / 'result.json', result)
    return {'job_id': context['job_id'], 'manifest': str(output / 'result.json'), 'partial': result['partial'], 'artifacts': len(artifacts)}


if __name__ == '__main__':
    print(json.dumps(finalize(*sys.argv[1:]), ensure_ascii=False))
