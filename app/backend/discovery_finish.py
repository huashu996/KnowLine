"""Finish discovery from acquisition receipts; the ingest validator accepts PDFs."""
import json
from pathlib import Path

from .safety import DomainError, atomic_json, contained, digest

RECEIPTS = 'discovery-import-receipts.json'
ROW_FIELDS = ('resource_id', 'version_id', 'sha256', 'new_download', 'new_registration',
              'duplicate', 'unavailable_reason', 'duration_seconds', 'metadata_status')
VERSION_FIELDS = ('publisher_url', 'access_method', 'pdf_version', 'pdf_version_basis',
                  'fallback_reason', 'acquired_at')


def read_receipts(path, context):
    value = json.loads(path.read_text('utf-8-sig'))
    if (not isinstance(value, dict) or value.get('job_id') != context['job_id']
            or value.get('domain_id') != context['scope'].get('domain_id')
            or not isinstance(value.get('rows'), list) or len(value['rows']) > 100):
        raise DomainError('discovery_import_results_required')
    ids = set()
    for row in value['rows']:
        if (not isinstance(row, dict) or not isinstance(row.get('candidate_id'), str)
                or not row['candidate_id'] or row['candidate_id'] in ids
                or not row.get('title') or not row.get('citation_record_id')):
            raise DomainError('discovery_import_results_required')
        ids.add(row['candidate_id'])
        if row.get('resource_id'):
            if not row.get('version_id') or not row.get('sha256'):
                raise DomainError('discovery_import_results_required')
        elif not isinstance(row.get('unavailable_reason'), str) or not row['unavailable_reason'].strip():
            raise DomainError('discovery_import_results_required')
    return value


def record_receipt(store, job, record, response):
    """Called in the service event loop after its single-writer import returns."""
    context = job['context']
    output = contained(store.project, context['output_dir'])
    path = contained(output, RECEIPTS, False)
    value = read_receipts(path, context) if path.is_file() else {
        'schema_version': 1, 'job_id': job['id'],
        'domain_id': context['scope'].get('domain_id'), 'rows': []}
    row = {'candidate_id': response['candidate_id'], 'title': record['title'],
           'citation_record_id': record['id'],
           **{key: record[key] for key in ('doi', 'year', 'venue') if key in record},
           **{key: response[key] for key in ROW_FIELDS if key in response}}
    if response.get('resource_id'):
        metadata = store.resource(response['resource_id'])['metadata']
        acquisition = response.get('acquisition') or {}
        for key in VERSION_FIELDS:
            if key in response or key in acquisition or key in metadata:
                row[key] = response.get(key, acquisition.get(key, metadata.get(key)))
    else:
        row['unavailable_reason'] = response.get('unavailable_reason') or response.get('reason') or 'fulltext_unavailable'
    old = next((r for r in value['rows'] if r['candidate_id'] == row['candidate_id']), None)
    # A failed repeated call must not erase a successful immutable import.
    if old and old.get('resource_id') and not row.get('resource_id'):
        return
    if old:
        value['rows'][value['rows'].index(old)] = row
    else:
        if len(value['rows']) >= 100:
            raise DomainError('discovery_candidate_limit')
        value['rows'].append(row)
    atomic_json(path, value)


def finalize(project, context_path, reason=None):
    project = Path(project).resolve()
    context = json.loads(contained(project, context_path).read_text('utf-8-sig'))
    if context.get('task') != 'discover_papers':
        raise DomainError('scope_violation')
    output = contained(project, context['output_dir'])
    receipt_path = contained(output, RECEIPTS, False)
    value = read_receipts(receipt_path, context) if receipt_path.is_file() else {
        'schema_version': 1, 'job_id': context['job_id'],
        'domain_id': context['scope'].get('domain_id'), 'rows': []}
    rows = value['rows']
    imported = len({row['resource_id'] for row in rows if row.get('resource_id')})
    target = context['literature_search']['target_count']
    if type(target) is not int or target < 1:
        raise DomainError('invalid_request')
    partial = imported < target
    if partial and (not isinstance(reason, str) or not reason.strip()):
        raise DomainError('discovery_incomplete_reason_required')
    if not receipt_path.is_file():
        atomic_json(receipt_path, value)
    english = context.get('ui_locale') == 'en'
    summary = (f'Imported {imported}/{target} verified full texts.' if english
               else f'已核实并导入全文 {imported}/{target} 篇。')
    if partial:
        summary += ' ' + reason.strip()
    result = {'schema_version': 2, 'job_id': context['job_id'], 'status': 'completed',
              'partial': partial, 'target_count': target, 'summary': summary,
              'imported_papers': rows, 'claims': [], 'proposed_relations': [],
              'warnings': [reason.strip()] if partial else [],
              'artifacts': [{'path': receipt_path.relative_to(project).as_posix(),
                             'sha256': digest(receipt_path)}]}
    atomic_json(contained(output, 'result.json', False), result)
    return {'job_id': context['job_id'], 'manifest': str(output / 'result.json'),
            'imported_count': imported, 'target_count': target,
            'partial': partial, 'ready_for_bridge': True}
