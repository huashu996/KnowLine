"""Source-faithful local PDF abstracts, returned without changing graph evidence."""
import json
import re
from functools import lru_cache
from urllib.parse import quote
from .pdf import open_pdf
from .safety import DomainError
from .store import now

START = re.compile(r'(?im)^\s*(?:abstract\b|摘\s*要)\s*[.．—–:：-]?\s*')
END = re.compile(r'(?im)^\s*(?:(?:index\s+terms|key\s*words|关键词|关\s*键\s*词)\b\s*[—–:：-]?|(?:[IVX]+[.．]?\s*|\d+[.．]?\s*)?(?:introduction|引言|绪论)\b|[IVX]+[.．]\s*$|arxiv\s*:\s*\d{4}\.\d{4,5}(?:v\d+)?\b)')


def extract_abstract(path):
    with open_pdf(path) as document:
        for page_index in range(min(2, len(document))):
            text = document[page_index].get_text()[:50000]
            start = START.search(text)
            if not start:
                continue
            remaining = text[start.end():]
            end = END.search(remaining)
            if not end:
                # Do not publish a guessed first-page summary or body paragraphs.
                continue
            abstract = remaining[:end.start()].strip()
            abstract = re.sub(r'(?<=\w)-\s*\n\s*(?=\w)', '-', abstract)
            abstract = ' '.join(abstract.split())
            if 80 <= len(abstract) <= 15000:
                return {'abstract': abstract, 'page_index': page_index}
    return None


@lru_cache(maxsize=128)
def _verified(path, sha256, size, modified, identity):
    from .institutional_access import validate_pdf
    try:
        validate_pdf(path, json.loads(identity))
        return extract_abstract(path)
    except (DomainError, OSError, ValueError, KeyError, TypeError):
        return None


def add_local_abstract(store, node, resources, record=None):
    if str(node.get('abstract') or '').strip():
        return node
    doi = str(node.get('doi') or '').lower()
    related = {record['identity_key'], *record.get('related_identifiers', [])} if record else set()
    if doi:
        related.add('doi:' + doi)
    if node.get('arxiv_id'):
        related.add('arxiv:' + str(node['arxiv_id']))
    for resource in resources:
        if resource['type'] != 'paper' or resource['state'] != 'ready':
            continue
        metadata = resource['metadata']
        identifiers = {'doi:' + str(metadata.get('doi') or '').lower(),
                       'arxiv:' + str(metadata.get('arxiv_id') or '')} - {'doi:', 'arxiv:'}
        linked = record and (resource['id'] in record.get('resource_ids', []) or metadata.get('publication_record_id') == record['id'])
        if not linked and not related.intersection(identifiers):
            continue
        try:
            snapshot = store.snapshot(resource)
            stat = snapshot.stat()
            authors = [a if isinstance(a, str) else a.get('name') or a.get('family', '') for a in node.get('authors', [])]
            identity = {'doi': doi or (record or {}).get('doi') or metadata.get('doi') or '', 'title': node['title'], 'authors': authors,
                        'pdf_identity': metadata.get('pdf_identity') or {'doi': metadata.get('doi') or doi, 'title': node['title'], 'authors': authors},
                        'pdf_version': metadata.get('pdf_version', 'unknown'), 'citation_record': record or {}}
            result = _verified(str(snapshot), resource['sha256'], stat.st_size, stat.st_mtime_ns, json.dumps(identity, sort_keys=True))
            if not result:
                continue
            page = result['page_index']
            return {**node, 'abstract': result['abstract'], 'abstract_source': {
                'url': (node.get('metadata_source') or {}).get('url', ''),
                'pdf_url': '/api/v1/resources/' + quote(resource['id'], safe='') + '/file?version=' + quote(resource['version_id'], safe='') + '#page=' + str(page + 1),
                'retrieved_at': now(), 'provider': 'Local PDF abstract',
                'resource_id': resource['id'], 'version_id': resource['version_id'],
                'sha256': resource['sha256'], 'page_index': page}}
        except (DomainError, OSError, ValueError, KeyError, TypeError):
            continue
    return node
