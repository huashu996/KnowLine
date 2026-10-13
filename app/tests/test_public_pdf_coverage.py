"""Public repository ID routing and independent original-page recovery.

Use --exe to execute the same tests against frozen production modules.
Fixtures never use a catalog, credentials, live jobs, network or PDF imports.
"""
import asyncio
import copy
from html import escape
from io import BytesIO
import json
import sys
import tempfile
import types
import unittest
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import AsyncMock, patch

APP = Path(__file__).resolve().parents[1]
EXE = None
if '--exe' in sys.argv:
    index = sys.argv.index('--exe')
    EXE = Path(sys.argv[index + 1])
    del sys.argv[index:index + 2]
sys.path.insert(0, str(APP / 'scripts'))
from patch_frozen_modules import module_code
PACKAGE = '_knowline_public_pdf_coverage'
package = types.ModuleType(PACKAGE)
package.__path__ = [str(APP / 'backend')]
sys.modules[PACKAGE] = package


def load(name):
    module = types.ModuleType(PACKAGE + '.' + name)
    module.__package__ = PACKAGE
    sys.modules[module.__name__] = module
    code = (module_code(EXE, 'backend.' + name) if EXE else
            compile((APP / 'backend' / (name + '.py')).read_bytes(), name, 'exec'))
    exec(code, module.__dict__)
    return module


store = types.ModuleType(PACKAGE + '.store')
store.uid = lambda prefix: prefix + '_fixture'
sys.modules[store.__name__] = store
access = load('institutional_access')
bib = load('paper_bibliography')
download = load('research_download')
official = load('official_copy')
public = load('research_public')
DomainError = access.DomainError


def record():
    return {'id': 'p_fixture', 'doi': '10.1109/lra.2021.3068914',
            'title': 'RaLL: Learning the Radar Localization',
            'authors': ['Alice Example', 'Bob Researcher'], 'year': 2021,
            'venue': 'IEEE Robotics and Automation Letters', 'source_type': 'JournalArticle',
            'publication_status': 'published', 'publisher_url': 'https://ieeexplore.ieee.org/document/fixture',
            'latest_verified': True, 'latest_checked_at': bib.stamp(), 'metadata_status': 'verified',
            'related_identifiers': [], 'evidence': [], 'domain_ids': [], 'resource_ids': []}


def feed(paper=None, key='2009.07061v2', doi=None):
    paper = paper or record()
    namespace = '{http://www.w3.org/2005/Atom}'
    root = ET.Element(namespace + 'feed')
    entry = ET.SubElement(root, namespace + 'entry')
    ET.SubElement(entry, namespace + 'id').text = 'http://arxiv.org/abs/' + key
    ET.SubElement(entry, namespace + 'title').text = paper['title']
    for author in paper['authors']:
        ET.SubElement(ET.SubElement(entry, namespace + 'author'), namespace + 'name').text = author
    if doi is None:
        doi = paper.get('doi')
    if doi:
        ET.SubElement(entry, '{http://arxiv.org/schemas/atom}doi').text = doi
    return ET.tostring(root)


def page(paper=None, key='2009.07061', version=2, history='', doi=None, pdf_version=True):
    paper = paper or record()
    tags = [('citation_title', paper['title']),
            ('citation_arxiv_id', key + ('v' + str(version) if version is not None else ''))]
    tags += [('citation_author', author) for author in paper['authors']]
    if doi is None:
        doi = paper.get('doi')
    if doi:
        tags.append(('citation_doi', doi))
    tags.append(('citation_pdf_url', 'https://arxiv.org/pdf/' + key +
                 ('v' + str(version) if version is not None and pdf_version else '')))
    html = ''.join('<meta name="' + name + '" content="' + escape(str(value), quote=True) + '">' for name, value in tags)
    html += history
    return {'url': 'https://arxiv.org/abs/' + key, 'html': html, 'text': paper['title'],
            'links': [], 'original_links': [], 'response_sha256': 'fixture-page-hash',
            'retrieved_at': '2026-10-13T00:00:00+00:00'}


def index_payload(provider, links, paper=None):
    paper = paper or record()
    if provider == 'OpenAlex':
        response = {'doi': 'https://doi.org/' + paper['doi'], 'title': paper['title'],
                    'authorships': [{'author': {'display_name': author}} for author in paper['authors']],
                    'locations': [{'is_oa': True, 'pdf_url': link, 'version': 'submittedVersion'} for link in links]}
    else:
        response = {'externalIds': {'DOI': paper['doi']}, 'title': paper['title'],
                    'authors': [{'name': author} for author in paper['authors']],
                    'openAccessPdf': {'url': links[0]}}
    return {'status': 'ok', 'request_sent': True, 'response': response,
            'response_sha256': 'fixture-index-hash', 'retrieved_at': bib.stamp()}


class RepositoryIdentifierTests(unittest.TestCase):
    def test_modern_abs_pdf_and_arxiv_doi_ids_are_canonical(self):
        for url in ['https://arxiv.org/abs/2009.07061',
                    'https://arxiv.org/abs/2009.07061v2',
                    'https://arxiv.org/pdf/2009.07061v2.pdf',
                    'https://export.arxiv.org/pdf/2009.07061',
                    'https://doi.org/10.48550/arXiv.2009.07061',
                    'https://doi.org/10.48550/arxiv.2009.07061v2']:
            with self.subTest(url=url):
                self.assertEqual(download.repository_arxiv_id(url), '2009.07061')

    def test_legacy_categories_and_versions_are_supported(self):
        for url, expected in [('https://arxiv.org/abs/cs/0609044v1', 'cs/0609044'),
                              ('https://arxiv.org/pdf/cs/0609044v1.pdf', 'cs/0609044'),
                              ('https://doi.org/10.48550/arXiv.cs/0609044', 'cs/0609044'),
                              ('https://arxiv.org/abs/math.GT/0309136v2', 'math.GT/0309136'),
                              ('https://arxiv.org/pdf/hep-th/9901001v3', 'hep-th/9901001')]:
            with self.subTest(url=url):
                self.assertEqual(download.repository_arxiv_id(url), expected)

    def test_lookalike_hosts_non_arxiv_dois_and_invalid_ids_are_not_repository_hints(self):
        for url in ['https://arxiv.org.evil.example/abs/2009.07061',
                    'https://doi.org/10.1109/lra.2009.07061',
                    'https://example.org/pdf/2009.07061',
                    'https://user:password@arxiv.org/abs/2009.07061',
                    'https://arxiv.org/abs/2009.07061v0',
                    'https://arxiv.org/abs/2009.07061/other',
                    'https://arxiv.org/abs/../2009.07061']:
            with self.subTest(url=url):
                self.assertFalse(download.repository_arxiv_id(url))


class OriginalRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def locate(self, paper=None, key='2009.07061v2', identifier=None):
        with patch.object(bib, 'fetch', AsyncMock(return_value=feed(paper, key))) as fetch:
            result = await download.locate_public(paper or record(), identifier)
        return result, fetch

    async def test_atom_legacy_id_is_validated_and_keeps_actual_version(self):
        (updated, source), fetch = await self.locate(key='cs/0609044v1', identifier='cs/0609044v1')
        self.assertEqual(source['access_url'], 'https://arxiv.org/pdf/cs/0609044v1')
        self.assertEqual(source['pdf_identity']['arxiv_id'], 'cs/0609044')
        self.assertIn('arxiv:cs/0609044', updated['related_identifiers'])
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(fetch.await_args.args[0]).query)
        self.assertEqual(query['id_list'], ['cs/0609044'])

    async def test_saved_versioned_identifier_searches_latest_base_id(self):
        paper = record()
        paper['related_identifiers'] = ['arxiv:2009.07061v1']
        (updated, source), fetch = await self.locate(paper)
        self.assertEqual(source['access_url'], 'https://arxiv.org/pdf/2009.07061v2')
        self.assertEqual(source['pdf_identity']['arxiv_id'], '2009.07061')
        self.assertIn('id_list=2009.07061', fetch.await_args.args[0])

    async def test_explicit_new_index_id_is_not_overridden_by_old_saved_id(self):
        paper = record()
        paper['related_identifiers'] = ['arxiv:1901.00001v1']
        (updated, source), fetch = await self.locate(paper, identifier='2009.07061v1')
        self.assertEqual(source['pdf_identity']['arxiv_id'], '2009.07061')
        self.assertIn('id_list=2009.07061', fetch.await_args.args[0])
        self.assertIn('arxiv:1901.00001v1', updated['related_identifiers'])
        self.assertEqual(updated['doi'], paper['doi'])

    async def test_conflicting_formal_doi_still_rejects_known_id(self):
        paper = record()
        paper['arxiv_id'] = '2009.07061'
        with patch.object(bib, 'fetch', AsyncMock(return_value=feed(paper, doi='10.1000/wrong'))):
            with self.assertRaisesRegex(DomainError, 'public_repository_no_identity_match'):
                await download.locate_public(paper)

    async def test_successful_atom_does_not_request_abs_again(self):
        with patch.object(bib, 'fetch', AsyncMock(return_value=feed())), \
                patch.object(official, 'fetch_page') as fetch_page:
            await download.locate_public(record(), '2009.07061')
        fetch_page.assert_not_called()

    async def test_successful_api_without_matching_identity_keeps_actual_query_trace(self):
        with patch.object(bib, 'fetch', AsyncMock(return_value=feed(doi='10.1000/wrong'))):
            with self.assertRaises(DomainError) as caught:
                await download.locate_public(record())
        trace = caught.exception.params['source_attempts'][0]
        self.assertEqual(trace['provider'], 'arXiv API')
        self.assertEqual(trace['status'], 'no_match')
        self.assertEqual(trace['http_status'], 200)
        self.assertTrue(trace['request_sent'])
        self.assertIn('search_query=', trace['url'])
        self.assertIn('au:', urllib.parse.unquote(trace['url']))


class ExactIndexRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_arxiv_doi_locator_from_both_indexes_uses_original_atom_identity(self):
        link = 'https://doi.org/10.48550/arxiv.2009.07061'
        for provider, locator in [('OpenAlex', download.locate_openalex), ('Semantic Scholar', download.locate_index)]:
            with self.subTest(provider=provider), \
                    patch.object(public, 'fetch', return_value=index_payload(provider, [link])), \
                    patch.object(bib, 'fetch', AsyncMock(return_value=feed())) as fetch:
                updated, source = await locator(record())
                self.assertEqual(source['access_url'], 'https://arxiv.org/pdf/2009.07061v2')
                self.assertEqual(source['pdf_version'], 'preprint')
                self.assertEqual(source['pdf_identity']['arxiv_id'], '2009.07061')
                self.assertEqual(updated['doi'], record()['doi'])
                self.assertFalse(any(binding.get('pdf_url') == link for binding in updated.get('public_copy_bindings', [])))
                fetch.assert_awaited_once()

    async def test_legacy_arxiv_links_from_both_indexes_are_not_ignored(self):
        link = 'https://arxiv.org/pdf/cs/0609044v1.pdf'
        for provider, locator in [('OpenAlex', download.locate_openalex), ('Semantic Scholar', download.locate_index)]:
            with self.subTest(provider=provider), \
                    patch.object(public, 'fetch', return_value=index_payload(provider, [link])), \
                    patch.object(bib, 'fetch', AsyncMock(return_value=feed(key='cs/0609044v1'))):
                updated, source = await locator(record())
                self.assertEqual(source['access_url'], 'https://arxiv.org/pdf/cs/0609044v1')
                self.assertEqual(source['pdf_identity']['arxiv_id'], 'cs/0609044')

    async def test_repeated_openalex_locations_query_one_repository_id_once(self):
        links = ['https://doi.org/10.48550/arxiv.2009.07061', 'https://arxiv.org/pdf/2009.07061v2']
        with patch.object(public, 'fetch', return_value=index_payload('OpenAlex', links)), \
                patch.object(bib, 'fetch', AsyncMock(return_value=feed())) as fetch:
            await download.locate_openalex(record())
        fetch.assert_awaited_once()

    async def test_repository_outage_does_not_hide_other_openalex_open_copy(self):
        links = ['https://doi.org/10.48550/arxiv.2009.07061', 'https://repository.university-example.nl/author-paper.pdf']
        with patch.object(public, 'fetch', return_value=index_payload('OpenAlex', links)), \
                patch.object(download, 'locate_public', AsyncMock(side_effect=DomainError('citation_source_unavailable', http_status=503))):
            updated, source = await download.locate_openalex(record())
        self.assertEqual(source['access_url'], links[1])
        self.assertIn('citation_source_unavailable', updated['public_location_failures'])
        self.assertNotIn('official_pdf_url', source['pdf_identity'])

    async def test_index_identity_conflict_stops_before_original_repository_request(self):
        paper = record()
        paper['doi'] = '10.1000/wrong'
        for provider, locator in [('OpenAlex', download.locate_openalex), ('Semantic Scholar', download.locate_index)]:
            with self.subTest(provider=provider), \
                    patch.object(public, 'fetch', return_value=index_payload(provider, ['https://doi.org/10.48550/arxiv.2009.07061'], paper)), \
                    patch.object(download, 'locate_public', AsyncMock()) as locate:
                with self.assertRaisesRegex(DomainError, 'public_index_identity_mismatch'):
                    await locator(record())
                locate.assert_not_awaited()


class OriginalPageRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def recover(self, response=None, failure=None, paper=None):
        failure = failure or DomainError('citation_source_unavailable', 502, http_status=503, request_sent=True)
        with patch.object(bib, 'fetch', AsyncMock(side_effect=failure)) as fetch, \
                patch.object(official, 'fetch_page', return_value=response or page()) as fetch_page:
            result = await download.locate_public(paper or record(), '2009.07061')
        return result, fetch, fetch_page

    async def test_known_id_api_outage_uses_one_independent_abs_page(self):
        (updated, source), fetch, fetch_page = await self.recover()
        fetch.assert_awaited_once()
        fetch_page.assert_called_once_with('https://arxiv.org/abs/2009.07061')
        self.assertEqual(source['access_url'], 'https://arxiv.org/pdf/2009.07061v2')
        self.assertEqual(updated['doi'], record()['doi'])
        self.assertEqual(updated['evidence'][-1]['response_sha256'], 'fixture-page-hash')
        trace = updated['public_location_attempts']
        self.assertEqual(trace[0]['http_status'], 503)
        self.assertEqual(trace[0]['status'], 'unavailable')
        self.assertEqual(trace[1]['status'], 'located')
        self.assertTrue(all(row['request_sent'] for row in trace))

    async def test_timeout_uses_known_original_page_without_retrying_api(self):
        (updated, source), fetch, fetch_page = await self.recover(failure=asyncio.TimeoutError())
        fetch.assert_awaited_once()
        fetch_page.assert_called_once()
        self.assertEqual(updated['public_location_attempts'][0]['reason'], 'public_locator_timeout')
        self.assertEqual(source['pdf_version'], 'preprint')

    async def test_unversioned_metadata_requires_same_record_submission_version(self):
        history = '<div class="submission-history"><span>[v1]</span><br><span>[v3]</span></div>'
        (updated, source), _, _ = await self.recover(response=page(version=None, history=history))
        self.assertEqual(source['access_url'], 'https://arxiv.org/pdf/2009.07061v3')
        self.assertEqual(updated['evidence'][-1]['preprint_version'], 3)

    async def test_latest_history_text_wins_over_older_version_links(self):
        history = ('<div class="submission-history"><a href="/abs/2009.07061v1">[v1]</a>'
                   '<a href="/abs/2009.07061v2">[v2]</a><span>[v3]</span></div>')
        (updated, source), _, _ = await self.recover(response=page(version=None, history=history))
        self.assertEqual(source['access_url'], 'https://arxiv.org/pdf/2009.07061v3')
        self.assertEqual(updated['evidence'][-1]['preprint_version'], 3)

    async def test_unversioned_metadata_without_actual_version_is_not_guessed(self):
        with self.assertRaisesRegex(DomainError, 'public_repository_version_unverified') as caught:
            await self.recover(response=page(version=None))
        self.assertEqual(len(caught.exception.params['source_attempts']), 2)
        self.assertEqual(caught.exception.params['source_attempts'][0]['http_status'], 503)

    async def test_other_record_versions_cannot_supply_missing_current_version(self):
        history = '<div class="submission-history"><a href="/abs/2401.00001v5">Other article</a></div>'
        with self.assertRaisesRegex(DomainError, 'public_repository_version_unverified'):
            await self.recover(response=page(version=None, history=history))

    async def test_abs_conflicting_doi_or_authors_do_not_create_identity_bridge(self):
        wrong_authors = record()
        wrong_authors['authors'] = ['Unrelated Person']
        for response in [page(doi='10.1000/wrong'), page(wrong_authors)]:
            with self.subTest(response=response), self.assertRaises(DomainError):
                await self.recover(response=response)

    async def test_api_429_does_not_trigger_an_alternate_arxiv_request(self):
        with patch.object(bib, 'fetch', AsyncMock(side_effect=DomainError('citation_source_unavailable', http_status=429, request_sent=True))), \
                patch.object(official, 'fetch_page') as fetch_page:
            with self.assertRaises(DomainError) as caught:
                await download.locate_public(record(), '2009.07061')
        fetch_page.assert_not_called()
        self.assertEqual(caught.exception.params['http_status'], 429)
        self.assertTrue(caught.exception.params['request_sent'])

    async def test_unknown_id_failure_is_not_turned_into_a_guessed_abs_request(self):
        with patch.object(bib, 'fetch', AsyncMock(side_effect=DomainError('citation_source_unavailable', http_status=503, request_sent=True))), \
                patch.object(official, 'fetch_page') as fetch_page:
            with self.assertRaisesRegex(DomainError, 'citation_source_unavailable'):
                await download.locate_public(record())
        fetch_page.assert_not_called()

    async def test_cancellation_does_not_start_another_source(self):
        with patch.object(bib, 'fetch', AsyncMock(side_effect=asyncio.CancelledError())), \
                patch.object(official, 'fetch_page') as fetch_page:
            with self.assertRaises(asyncio.CancelledError):
                await download.locate_public(record(), '2009.07061')
        fetch_page.assert_not_called()


class GitHubRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_verified_pdf_keeps_query_url_and_actual_request_flag(self):
        response = {'status': 'ok', 'http_status': 200, 'request_sent': False, 'response': {'items': []}}
        with patch.object(public, 'fetch', return_value=response):
            with self.assertRaisesRegex(DomainError, 'github_no_verified_pdf') as caught:
                await official.locate_github(record())
        trace = caught.exception.params['source_attempts'][0]
        self.assertEqual(trace['status'], 'no_match')
        self.assertFalse(trace['request_sent'])
        self.assertEqual(trace['http_status'], 200)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(trace['url']).query)
        self.assertEqual(query['q'], ['"RaLL" in:readme fork:false'])

    async def test_rate_limited_github_preserves_cooldown_without_claiming_a_new_request(self):
        response = {'status': 'rate_limited', 'http_status': 429, 'request_sent': False, 'retry_after_seconds': 60}
        with patch.object(public, 'fetch', return_value=response):
            with self.assertRaisesRegex(DomainError, 'github_search_unavailable') as caught:
                await official.locate_github(record())
        trace = caught.exception.params['source_attempts'][0]
        self.assertEqual(trace['status'], 'cooldown')
        self.assertFalse(trace['request_sent'])
        self.assertEqual(trace['http_status'], 429)
        self.assertEqual(trace['retry_after_seconds'], 60)

    async def test_github_doi_and_legacy_links_use_original_repository_verification(self):
        for link, key in [('https://doi.org/10.48550/arxiv.2009.07061', '2009.07061v2'),
                          ('https://arxiv.org/pdf/cs/0609044v1.pdf', 'cs/0609044v1')]:
            paper = record()
            response = {'status': 'ok', 'request_sent': True,
                        'response': {'items': [{'full_name': 'Author/Repository', 'fork': False}]}}
            content = {'html': paper['title'] + ' ' + paper['doi'],
                       'text': paper['title'] + ' ' + ' '.join(paper['authors']),
                       'original_links': [link], 'links': [link],
                       'response_sha256': 'fixture-github-hash', 'retrieved_at': bib.stamp()}
            with self.subTest(link=link), patch.object(public, 'fetch', return_value=response) as search, \
                    patch.object(official, 'fetch_page', return_value=content), \
                    patch.object(bib, 'fetch', AsyncMock(return_value=feed(key=key))) as fetch:
                updated, source = await official.locate_github(paper)
            self.assertEqual(source['access_url'], 'https://arxiv.org/pdf/' + key)
            self.assertEqual(updated['repository_bindings'][0]['repository'], ['Author', 'Repository'])
            search.assert_called_once()
            fetch.assert_awaited_once()


class AnonymousMetadataTransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bib._last.clear()

    async def test_arxiv_uses_tls_public_opener_without_disabling_system_proxy(self):
        response = BytesIO(feed())
        response.status = 200
        opener = types.SimpleNamespace(open=lambda request, timeout: response)
        with patch.object(download, 'public_opener', return_value=opener) as build, \
                patch.object(bib.urllib.request, 'build_opener') as plain_build:
            result = await bib._fetch('https://export.arxiv.org/api/query?id_list=2009.07061')
        self.assertIn(b'2009.07061v2', result)
        build.assert_called_once()
        plain_build.assert_not_called()
        self.assertFalse(any(isinstance(handler, bib.urllib.request.ProxyHandler) for handler in build.call_args.args))
        self.assertFalse(any(isinstance(handler, bib.urllib.request.HTTPCookieProcessor) for handler in build.call_args.args))

    async def test_http_status_and_sent_flag_survive_metadata_failure(self):
        failure = urllib.error.HTTPError('https://export.arxiv.org/api/query', 503, 'Unavailable', {}, BytesIO(b''))
        with patch.object(bib, '_fetch', AsyncMock(side_effect=failure)):
            with self.assertRaises(DomainError) as caught:
                await bib.fetch('https://export.arxiv.org/api/query?id_list=2009.07061')
        self.assertEqual(caught.exception.params['http_status'], 503)
        self.assertTrue(caught.exception.params['request_sent'])


class BridgeSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'fixture-state'
        self.state.mkdir()
        self.saved = []
        def execute(sql, parameters):
            if sql.startswith('INSERT OR REPLACE'):
                value = json.loads(parameters[2])
                self.saved[:] = [value]
        self.store = types.SimpleNamespace(project=self.root, state=self.state,
                    db=types.SimpleNamespace(execute=execute), event=lambda *args: None)
        self.patch_rows = patch.object(bib, 'rows', lambda store: copy.deepcopy(self.saved))
        self.patch_rows.start()
        self.addCleanup(self.patch_rows.stop)

    def formal(self):
        value = record()
        value.update(identity_key='doi:' + value['doi'], source_url='https://api.crossref.org/works/' + value['doi'],
                     evidence=[{'provider': 'Crossref', 'doi': value['doi'], 'retrieved_at': value['latest_checked_at']}])
        return value

    def save_bridge(self):
        initial = bib.save(self.store, self.formal())
        value = self.formal()
        value['related_identifiers'] = ['arxiv:2009.07061']
        value['temporary_model_note'] = 'Do not carry unrelated old fields'
        value['evidence'].append({'provider': 'arXiv', 'identity_key': 'arxiv:2009.07061',
            'arxiv_id': '2009.07061', 'url': 'https://arxiv.org/abs/2009.07061v3',
            'formal_doi': value['doi'], 'title': value['title'], 'authors': value['authors'],
            'preprint_version': 3, 'retrieved_at': value['latest_checked_at'],
            'relationship': 'repository_declared_doi'})
        return initial, bib.save(self.store, value)

    def test_refresh_preserves_actual_bridge_snapshot_when_alias_set_is_unchanged(self):
        initial, bridge = self.save_bridge()
        refreshed = bib.save(self.store, self.formal())
        self.assertIn(bridge['evidence_path'], refreshed['bridge_evidence_paths'])
        self.assertNotIn(initial['evidence_path'], refreshed['bridge_evidence_paths'])
        proof = json.loads((self.root / refreshed['evidence_path']).read_text('utf-8'))
        self.assertEqual(proof['inherited_related_identifiers'], ['arxiv:2009.07061'])
        self.assertEqual([item['provider'] for item in proof['identity_evidence']], ['Crossref'])
        self.assertNotIn('temporary_model_note', refreshed)
        retained = self.root / bridge['evidence_path']
        self.assertEqual(bib.digest(retained), bridge['evidence_sha256'])
        again = bib.save(self.store, self.formal())
        self.assertEqual(again['bridge_evidence_paths'], refreshed['bridge_evidence_paths'])

    def test_changed_identity_does_not_inherit_old_bridge_proof(self):
        initial, bridge = self.save_bridge()
        changed = self.formal()
        changed['title'] = 'A different title using the same catalog DOI'
        refreshed = bib.save(self.store, changed)
        self.assertFalse(refreshed['bridge_evidence_paths'])

    def test_corrupted_or_non_hash_addressed_snapshot_is_not_retained(self):
        initial, bridge = self.save_bridge()
        (self.root / bridge['evidence_path']).write_text('{"tampered":true}', encoding='utf-8')
        refreshed = bib.save(self.store, self.formal())
        self.assertNotIn(bridge['evidence_path'], refreshed['bridge_evidence_paths'])


if __name__ == '__main__':
    unittest.main()
