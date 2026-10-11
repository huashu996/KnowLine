"""Count actual registered full texts separately from discovered candidates."""
from .safety import DomainError


def incomplete(job):
    if job['task'] == 'paper_relationships':
        return bool((job.get('result') or {}).get('partial')) or (job.get('result') or {}).get('citation_summary', {}).get('unknown_count', 0) > 0
    if job['task'] != 'discover_papers':
        return False
    result = job.get('result') or {}
    rows = result.get('imported_papers')
    target=job['context'].get('literature_search',{}).get('target_count')
    if isinstance(target,int):return len({r['resource_id'] for r in rows or [] if r.get('resource_id')})<target or bool(result.get('partial'))
    return not rows or any(not row.get('resource_id') for row in rows) or bool(result.get('partial'))


def summary(job):
    result = job.get('result') or {}
    rows = result.get('imported_papers') or []
    imported = len({row['resource_id'] for row in rows if row.get('resource_id')})
    return {'candidate_count': len(rows), 'imported_count': imported, 'unavailable_count': len(rows)-imported,
            'citation_record_count':len({r['citation_record_id'] for r in rows if r.get('citation_record_id')}),
            'metadata_only_count':sum(bool(r.get('citation_record_id')) and not r.get('resource_id') for r in rows),
            'new_download_count': sum(row.get('new_download') is True for row in rows),
            'new_registration_count': sum(row.get('new_registration') is True for row in rows),
            'registration_report_missing': not bool(rows)}


def failure_diagnostic(job):
    if job['task']!='discover_papers' or job['status']!='failed':return {}
    result=job.get('result') or {};stats=result.get('literature_summary') or summary(job)
    if stats['imported_count']:return {}
    reasons=[row.get('unavailable_reason','') for row in result.get('imported_papers',[]) if row.get('unavailable_reason')]
    return {'error_code':'discovery_no_usable_fulltext',
            'failure_detail':(('已定位候选 '+str(stats['candidate_count'])+' 条，实际导入全文 0 篇。\n')+'\n'.join(reasons))[:3000]}


def validate(store, job, result):
    rows = result.get('imported_papers')
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise DomainError('discovery_import_results_required')
    ids = [row.get('candidate_id') for row in rows]
    if any(not isinstance(id, str) or not id for id in ids) or len(set(ids)) != len(ids):
        raise DomainError('discovery_import_results_required')
    domain = next((g for g in store.groups() if g['id'] == job['context']['scope'].get('domain_id')), None)
    if not domain:
        raise DomainError('scope_violation')
    from . import pdf
    for row in rows:
        if row.get('citation_record_id'):
            from .paper_bibliography import get
            record=get(store,row['citation_record_id'])
            if domain['id'] not in record['domain_ids']:raise DomainError('discovery_import_scope_mismatch')
            row['citation_status']=record['metadata_status'];row['citation_publication_status']=record['publication_status']
        if row.get('resource_id'):
            resource = store.resource(row['resource_id'])
            if resource['metadata'].get('metadata_status')!='verified' or not row.get('citation_record_id') or record.get('metadata_status')!='verified' or not record.get('latest_verified'):
                raise DomainError('public_citation_verification_required',409)
            if resource['type'] != 'paper' or resource['state'] != 'ready' or resource['id'] not in domain['resource_ids'] or row.get('version_id') != resource['version_id'] or row.get('sha256') != resource['sha256']:
                raise DomainError('discovery_import_scope_mismatch')
            with pdf.open_pdf(store.snapshot(resource)) as document:
                if not len(document):raise DomainError('pdf_invalid')
            if row.get('citation_record_id'):
                from .institutional_access import validate_pdf
                validate_pdf(store.snapshot(resource),{**record,'citation_record':record,'pdf_version':resource['metadata'].get('pdf_version','unknown'),**({'pdf_identity':resource['metadata']['pdf_identity']} if resource['metadata'].get('pdf_identity') else {})})
            # Old manifests remain valid; any new version claim must be explicit and sourced.
            if 'pdf_version' in row:
                from .institutional_access import VERSIONS,safe_url
                if row['pdf_version'] not in VERSIONS:raise DomainError('institution_version_basis_required')
                if row['pdf_version']!='unknown' and not row.get('pdf_version_basis'):raise DomainError('institution_version_basis_required')
                if row.get('publisher_url'):row['publisher_url']=safe_url(row['publisher_url'])
                if row['pdf_version'] in {'accepted_manuscript','preprint'} and not row.get('fallback_reason'):raise DomainError('institution_fallback_reason_required')
        elif not isinstance(row.get('unavailable_reason'), str) or not row['unavailable_reason'].strip():
            raise DomainError('discovery_import_results_required')
    result['literature_summary'] = summary({**job, 'result': result})
    if not result['literature_summary']['imported_count']:return 'partial' if result['literature_summary']['citation_record_count'] else 'failed'
    expected = job['context'].get('literature_search', {}).get('target_count') or result.get('target_count')
    return 'partial' if incomplete({**job, 'result': result}) or isinstance(expected, int) and result['literature_summary']['imported_count'] < expected else 'completed'
