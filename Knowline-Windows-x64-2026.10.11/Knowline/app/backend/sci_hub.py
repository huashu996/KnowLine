"""Explicitly requested, exact-DOI full-text hints; never publication/OA proof.

One configured site, one bounded anonymous page request, no mirror discovery,
account data or challenge handling. Actual PDF identity remains mandatory.
"""
import asyncio
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
import re
import time
import urllib.error
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from .institutional_access import public_destination, safe_url
from .paper_bibliography import doi as canonical_doi, norm
from .safety import DomainError

BASE = 'https://sci-hub.ru'
PROVIDER = 'Sci-Hub'
PAGE_TIMEOUT_SECONDS = 10


def access(doi):
    """Expose a lookup plan without claiming that a request or download ran."""
    try:
        identifier = canonical_doi(doi)
    except DomainError:
        identifier = None
    return {'provider': PROVIDER, 'url': BASE + '/' + (quote(identifier, safe='/') if identifier else ''),
            'status': 'not_checked', 'request_sent': False, 'role': 'fulltext_only',
            'open_access_verified': False}


def _site(host):
    root = urlsplit(BASE).hostname
    return bool(host and (host == root or host.endswith('.' + root)))


def _stable_link(page, value):
    # Viewer fragments do not reach the server. Keep all server-side parameters
    # subject to the existing stable-URL gate; never retain signed parameters.
    parsed = urlsplit(urljoin(page, unescape(str(value or '').strip())))
    return safe_url(urlunsplit(parsed._replace(fragment='')))


def valid_source(source, record, resolve=False):
    """Authorize only a paper-scoped embedded URL; supply no identity bridge."""
    try:
        if (not isinstance(source, dict) or not isinstance(record, dict)
                or source.get('source_provider') != PROVIDER or source.get('user_requested') is not True
                or source.get('public_oa') is not False or source.get('open_access_verified') is not False
                or record.get('latest_verified') is not True or record.get('metadata_status') != 'verified'):
            return False
        identifier = canonical_doi(record.get('doi'))
        identity = source.get('pdf_identity') or {}
        if (identity.get('doi') != identifier or norm(identity.get('title', '')) != norm(record.get('title', ''))
                or not record.get('authors') or identity.get('authors') != record['authors']
                or identity.get('arxiv_id') or identity.get('official_pdf_url') or identity.get('publisher_pdf_url')
                or source.get('publisher_url') != record.get('publisher_url')):
            return False
        link = safe_url(source.get('access_url'))
        page = safe_url(source.get('version_source_url'))
        if page != access(identifier)['url'] or not _site(urlsplit(page).hostname):
            return False
        for binding in record.get('public_copy_bindings', []):
            if (binding.get('match_basis') != 'metadata_only_hint' or binding.get('source_provider') != PROVIDER
                    or binding.get('doi') != identifier or binding.get('pdf_url') != link
                    or binding.get('source_url') != page or binding.get('declared_pdf_url') != link
                    or norm(binding.get('title', '')) != norm(record.get('title', ''))
                    or binding.get('authors') != record['authors']
                    or not re.fullmatch(r'[0-9a-f]{64}', str(binding.get('response_sha256', '')))):
                continue
            datetime.fromisoformat(str(binding['retrieved_at']).replace('Z', '+00:00'))
            response_url = safe_url(binding.get('response_url') or page)
            if not _site(urlsplit(response_url).hostname):
                continue
            # An outside CDN is allowed only by this exact fetched declaration,
            # never by a general domain allowlist. All addresses must be public.
            host = urlsplit(link).hostname
            if not resolve or public_destination(link, {host}, allow_translated=True):
                return True
        return False
    except (DomainError, KeyError, TypeError, ValueError, OSError):
        return False


async def locate(record):
    """Read one exact-DOI page and return an unverified embedded-PDF hint."""
    supplied = record if isinstance(record, dict) else {}
    plan = access(supplied.get('doi'))
    page = plan['url']
    attempt = {**plan, 'http_status': None}
    try:
        identifier = canonical_doi(supplied.get('doi'))
        if (not isinstance(record, dict) or record.get('latest_verified') is not True
                or record.get('metadata_status') != 'verified' or not record.get('title')
                or not record.get('authors') or not record.get('publisher_url')):
            raise DomainError('public_identity_unverified')
    except (DomainError, TypeError) as exc:
        code = getattr(exc, 'code', 'sci_hub_identifier_required')
        raise DomainError(code, source_attempts=[{**attempt, 'reason': code}]) from exc

    from .official_copy import fetch_page

    def read_page():
        if not public_destination(page, {urlsplit(BASE).hostname}, allow_translated=True):
            raise DomainError('sci_hub_destination_unsafe', request_sent=False)
        attempt['request_sent'] = True
        attempt['status'] = 'requested'
        response = fetch_page(page)
        if not _site(urlsplit(safe_url(response['url'])).hostname):
            raise DomainError('sci_hub_redirect_outside_site')
        # fetch_page enforces bounded bytes, decoding, TLS and redirect scope.
        if len(response.get('html', '').encode('utf-8')) > 2 * 1024 * 1024:
            raise DomainError('official_source_page_size_limit')
        return response

    deadline = time.monotonic() + PAGE_TIMEOUT_SECONDS
    try:
        response = await asyncio.wait_for(asyncio.to_thread(read_page), PAGE_TIMEOUT_SECONDS)
        attempt['http_status'] = response.get('http_status')
        html = response['html']
        if re.search(r'<(?:input|form|iframe)\b[^>]*(?:captcha|recaptcha|challenge|password)', html, re.I):
            raise DomainError('sci_hub_requires_user')

        class Embedded(HTMLParser):
            def __init__(self):
                super().__init__()
                self.links = []

            def handle_starttag(self, tag, attrs):
                values = dict(attrs)
                link = (values.get('src') if tag in {'iframe', 'embed'} else
                        values.get('data') if tag == 'object' else
                        values.get('content') if tag == 'meta' and str(values.get('name', '')).lower() == 'citation_pdf_url' else
                        values.get('href') if tag == 'a' else None)
                if link and (tag != 'a' or re.search(r'\.pdf(?:$|[?#])', link, re.I)):
                    self.links.append(link)

        parsed = Embedded()
        parsed.feed(html)
        identity = {key: record[key] for key in ('title', 'authors')}
        identity['doi'] = identifier
        for value in list(dict.fromkeys(parsed.links))[:6]:
            try:
                link = _stable_link(response['url'], value)
            except (DomainError, TypeError, ValueError):
                continue
            binding = {'source_provider': PROVIDER, 'match_basis': 'metadata_only_hint',
                       'doi': identifier, 'title': record['title'], 'authors': record['authors'],
                       'source_url': page, 'response_url': response['url'], 'pdf_url': link, 'declared_pdf_url': link,
                       'response_sha256': response['response_sha256'], 'retrieved_at': response['retrieved_at']}
            source = {'source_provider': PROVIDER, 'user_requested': True,
                      'publisher_url': record['publisher_url'], 'access_url': link, 'version_source_url': page,
                      'public_oa': False, 'open_access_verified': False, 'download_permitted': True,
                      'pdf_version': 'unknown', 'version_basis': 'Sci-Hub embeds this URL; actual file version is unverified',
                      'fallback_reason': 'User-requested final Sci-Hub lookup for this exact DOI; neither open access nor formal publication is inferred',
                      'pdf_identity': identity}
            updated = {**record, 'public_copy_bindings': [*record.get('public_copy_bindings', []), binding][-10:]}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError()
            if not await asyncio.wait_for(asyncio.to_thread(valid_source, source, updated, True), remaining):
                continue
            located = {**attempt, 'status': 'located', 'request_sent': True}
            updated['public_location_attempts'] = [*record.get('public_location_attempts', []), located][-8:]
            updated['public_download_sources'] = list({item.get('access_url'): item for item in
                [source, *record.get('public_download_sources', [])] if item.get('access_url')}.values())[:3]
            updated['evidence'] = [*record.get('evidence', []), {'provider': PROVIDER, 'role': 'fulltext_only',
                'source_url': page, 'url': link, 'response_sha256': response['response_sha256'],
                'retrieved_at': response['retrieved_at'], 'relationship': 'metadata_only_hint'}]
            return updated, source
        raise DomainError('sci_hub_no_embedded_pdf')
    except (DomainError, OSError, ValueError, asyncio.TimeoutError) as exc:
        code = (getattr(exc, 'code', None) or ('sci_hub_http_' + str(exc.code) if isinstance(exc, urllib.error.HTTPError)
                else 'sci_hub_timeout' if isinstance(exc, asyncio.TimeoutError) else 'sci_hub_source_unavailable'))
        if isinstance(exc, urllib.error.HTTPError):
            code = 'sci_hub_http_' + str(exc.code)
            attempt['http_status'] = exc.code
        params = dict(getattr(exc, 'params', {}))
        attempt.update(status='cooldown' if attempt['http_status'] == 429 else 'no_match' if code == 'sci_hub_no_embedded_pdf' else 'unavailable', reason=code)
        if params.get('request_sent') is False:
            attempt['request_sent'] = False
        raise DomainError(code, 502, source_attempts=[attempt], request_sent=attempt['request_sent'],
                          http_status=attempt['http_status']) from exc
