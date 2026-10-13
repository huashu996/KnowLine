"""Graph search preferences, frozen scope and bounded public concurrency.

Runs production source or selected modules from --exe, without network,
credentials, live jobs or a real catalog. All fixture writes use temp folders.
"""
import copy
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.parse
from unittest.mock import patch


APP = Path(__file__).resolve().parents[1]
EXE = None
if '--exe' in sys.argv:
    index = sys.argv.index('--exe')
    EXE = Path(sys.argv[index + 1])
    del sys.argv[index:index + 2]
sys.path.insert(0, str(APP / 'scripts'))
from patch_frozen_modules import module_code

PACKAGE = '_knowline_graph_search_tests'
package = types.ModuleType(PACKAGE)
package.__path__ = [str(APP / 'backend')]
sys.modules[PACKAGE] = package


def code(name):
    return (module_code(EXE, 'backend.' + name) if EXE else
            compile((APP / 'backend' / (name + '.py')).read_bytes(), name, 'exec'))


def load(name):
    module = types.ModuleType(PACKAGE + '.' + name)
    module.__package__ = PACKAGE
    sys.modules[module.__name__] = module
    exec(code(name), module.__dict__)
    return module


def stub(name, **values):
    module = types.ModuleType(PACKAGE + '.' + name)
    module.__dict__.update(values)
    sys.modules[module.__name__] = module
    return module


safety = load('safety')
query = load('research_query')
prepare = load('research_prepare')
policy = load('research_policy')
stub('paper_bibliography', stamp=lambda: '2026-10-13T00:00:00+00:00')
public = load('research_public')
stub('skills', require_task_skill=lambda *args: None, inventory=lambda *args: [])
stub('project_catalog', resolve=lambda *args: {'id': 'g_test', 'name': 'test', 'revision': 1})


def create_output(project, identity, *args):
    output = project / 'outputs' / identity
    output.mkdir(parents=True)
    return output


stub('output_names', create_output=create_output, describe=lambda *args: None,
     output_filenames=lambda *args: {})
store_code = next(value for value in code('store').co_consts
                  if isinstance(value, types.CodeType) and value.co_name == 'Store')
create_job_code = next(value for value in store_code.co_consts
                       if isinstance(value, types.CodeType) and value.co_name == 'create_job')
create_job = types.FunctionType(create_job_code, {
    '__package__': PACKAGE, 'DomainError': safety.DomainError,
    'Path': Path, 'contained': safety.contained, 'digest': safety.digest,
    'SafeZip': safety.SafeZip, 'atomic_json': safety.atomic_json,
    'json_text': safety.json_text, 'now': lambda: '2026-10-13T00:00:00+00:00',
    'uid': lambda prefix: prefix + '_test',
}, 'create_job')


class FrozenStore:
    create_job = create_job

    def __init__(self, root):
        self.project = root
        self.state = root / 'fixture-state'
        (self.state / 'jobs').mkdir(parents=True)
        self.config = {'ui_locale': 'zh'}
        self.saved_context = None
        self.db = types.SimpleNamespace(execute=self.execute)

    def execute(self, sql, parameters):
        self.saved_context = json.loads(parameters[3])

    def event(self, *args):
        pass

    def job(self, identity):
        return {'id': identity, 'context': copy.deepcopy(self.saved_context)}


def graph_scope(title='KISS-ICP', instructions='', target_count=5):
    plan = query.graph_plan(title, instructions, target_count)
    return {'query': plan['origin_query'], 'search_instructions': plan['search_instructions'],
            'search_plan': plan, 'from_year': 2020, 'to_year': 2026,
            'target_count': target_count, 'network_policy': 'topical-multihop-real-citations-v2'}


class GraphPlanTests(unittest.TestCase):
    def test_separate_origin_and_venue_preferences(self):
        result = query.graph_plan(' KISS-ICP ', '以 TRO、RAL 为主', 12)
        self.assertEqual(result['origin_query'], 'KISS-ICP')
        self.assertEqual(result['scholar_query'], 'KISS-ICP')
        self.assertEqual(result['target_count'], 12)
        self.assertEqual(result['search_instructions'], '以 TRO、RAL 为主')
        self.assertEqual(set(result['preferred_venues']), {
            'IEEE Transactions on Robotics', 'IEEE Robotics and Automation Letters'})

    def test_single_box_origin_and_preference_are_separated(self):
        result = query.graph_plan('KISS-ICP 以TRO RAL为主')
        self.assertEqual(result['origin_query'], 'KISS-ICP')
        self.assertEqual(result['origin_request'], 'KISS-ICP 以TRO RAL为主')
        self.assertEqual(len(result['preferred_venues']), 2)
        self.assertEqual(result['request'], result['origin_request'])

    def test_freeform_method_intent_is_retained_in_full(self):
        notes = '侧重退化场景与鲁棒数据关联；区分连续时间方法，说明与 KISS-ICP 的真实引用关系。'
        result = query.graph_plan('KISS-ICP', notes)
        self.assertEqual(result['search_instructions'], notes)
        self.assertEqual(result['request'], 'KISS-ICP\n' + notes)
        self.assertEqual(result['topic_query'], 'KISS-ICP')
        self.assertFalse(result['preferred_venues'])

    def test_plain_origin_is_not_rewritten(self):
        title = 'KISS-ICP: In Defense of Point-to-Point ICP — Simple, Accurate, and Robust Registration'
        result = query.graph_plan(title)
        self.assertEqual(result['origin_query'], title)
        self.assertEqual(result['request'], title)
        self.assertFalse(result['preferred_venues'])

    def test_ral_and_ra_l_are_one_preference(self):
        result = query.graph_plan('KISS-ICP', 'RAL / RA-L / TRO 为主')
        self.assertEqual(result['preferred_venues'].count('IEEE Robotics and Automation Letters'), 1)
        self.assertEqual(len(result['preferred_venues']), 2)

    def test_seed_wins_even_outside_preferred_journals(self):
        plan = query.graph_plan('KISS-ICP', '以TRO RAL为主')
        seed = {'title': 'KISS-ICP: In Defense of Point-to-Point ICP', 'venue': 'ICRA'}
        other = {'title': 'Another LiDAR Method', 'venue': 'IEEE Transactions on Robotics'}
        ordered = sorted([other, seed], key=lambda paper: query.graph_candidate_rank(paper, plan))
        self.assertIs(ordered[0], seed)
        self.assertEqual(len(ordered), 2)

    def test_preferred_venues_are_soft_rank_not_filter(self):
        plan = query.graph_plan('KISS-ICP', 'TRO / RA-L 为主')
        rows = [{'title': 'Conference method', 'venue': 'IROS'},
                {'title': 'TRO method', 'venue': 'TRO'},
                {'title': 'RA-L method', 'venue': 'IEEE RA-L'},
                {'title': 'RAL long name', 'venue': 'IEEE Robotics and Automation Letters'}]
        ordered = sorted(rows, key=lambda paper: query.graph_candidate_rank(paper, plan))
        self.assertEqual({row['title'] for row in ordered[:3]},
                         {'TRO method', 'RA-L method', 'RAL long name'})
        self.assertEqual(ordered[-1]['title'], 'Conference method')
        self.assertEqual(len(ordered), len(rows))

    def test_graph_plan_ends_missing_fulltext_after_bounded_sources(self):
        result = query.graph_plan('KISS-ICP')
        self.assertEqual(result['unavailable_fulltext'], 'skip_after_bounded_sources')
        self.assertIn('continue_next', policy.fulltext_policy()['unavailable_fulltext'])


class FrozenScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = FrozenStore(Path(self.temp.name))

    def body(self, **extra):
        return {'task': 'paper_relationships', 'query': 'KISS-ICP',
                'from_year': 2020, 'to_year': 2026, **extra}

    def test_store_freezes_instructions_and_separate_seed(self):
        body = self.body(search_instructions='以 TRO RA-L 为主；关注鲁棒性', target_count=7)
        job = self.store.create_job(body)
        scope = job['context']['literature_search']
        self.assertEqual(scope['query'], 'KISS-ICP')
        self.assertEqual(scope['search_instructions'], body['search_instructions'])
        self.assertEqual(scope['search_plan']['preferred_venues'],
                         ['IEEE Transactions on Robotics', 'IEEE Robotics and Automation Letters'])
        self.assertEqual(scope['target_count'], 7)
        self.assertEqual(scope['unavailable_fulltext_policy'], 'skip_after_bounded_sources')
        self.assertIsNone(scope['time_budget_seconds'])
        body['search_instructions'] = 'changed after creation'
        frozen = json.loads((self.store.state / 'jobs/j_test/context.json').read_text('utf-8'))
        self.assertEqual(frozen['literature_search']['search_instructions'], '以 TRO RA-L 为主；关注鲁棒性')

    def test_instruction_size_and_type_are_validated_before_job_write(self):
        for value in ['x' * 2001, None, 1, {}, True]:
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaisesRegex(safety.DomainError, 'invalid_request'):
                    self.store.create_job(self.body(search_instructions=value))
                self.assertFalse(list((self.store.state / 'jobs').iterdir()))

    def test_maximum_instruction_length_is_kept(self):
        notes = '方法' * 1000
        job = self.store.create_job(self.body(search_instructions=notes, target_count=5))
        self.assertEqual(job['context']['literature_search']['search_instructions'], notes)

    def test_default_count_is_frozen_consistently(self):
        job = self.store.create_job(self.body(search_instructions='TRO 为主'))
        scope = job['context']['literature_search']
        self.assertEqual(scope['target_count'], scope['search_plan']['target_count'])
        self.assertEqual(scope['target_count'], 10)

    def test_cache_key_changes_with_method_and_venue_preferences(self):
        contexts = [{'task': 'paper_relationships', 'literature_search': graph_scope(instructions=notes)}
                    for notes in ['', 'TRO 为主', 'RA-L 为主', '关注退化场景', '关注长时间漂移']]
        self.assertEqual(len({prepare.key(context) for context in contexts}), len(contexts))
        self.assertEqual(prepare.key(contexts[1]), prepare.key(copy.deepcopy(contexts[1])))
        names = [query.revised_names(context['literature_search']['search_plan'])['discovery']
                 for context in contexts]
        self.assertEqual(len(set(names)), len(contexts))


class RelatedGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'outputs/new'
        self.output.mkdir(parents=True)
        old = self.root / 'outputs/old/paper-graph.json'
        old.parent.mkdir()
        nodes = [{'id': 'seed', 'title': 'KISS-ICP', 'authors': ['Fixture Author'], 'year': 2023, 'doi': '10.1000/seed'}]
        nodes += [{'id': 'n' + str(i), 'title': 'LiDAR mapping ' + str(i),
                   'authors': ['Fixture Author'], 'year': 2022 + i % 3,
                   'doi': '10.1000/' + str(i), 'citation_count': i} for i in range(6)]
        graph = {'origin_id': 'seed', 'nodes': nodes,
                 'network_policy': 'topical-multihop-real-citations-v2',
                 'edges': [{'source': 'seed', 'target': node['id'], 'kind': 'citation'} for node in nodes[1:]]}
        safety.atomic_json(old, graph)
        self.previous = {'id': 'old', 'result': {
            'paper_graph_artifact': 'outputs/old/paper-graph.json',
            'artifacts': [{'path': 'outputs/old/paper-graph.json', 'sha256': safety.digest(old)}]},
            'context': {'literature_search': {'query': 'LiDAR SLAM'}}}
        self.store = types.SimpleNamespace(project=self.root, rows=lambda *args: [{'id': 'old'}],
                                           job=lambda *args: copy.deepcopy(self.previous))

    def related(self, notes=''):
        job = {'id': 'new', 'context': {'literature_search': graph_scope(instructions=notes)}}
        return prepare.related_memory(self.store, job, self.output)

    def test_no_preference_can_reuse_verified_neighbour_graph(self):
        result = self.related()
        self.assertEqual(result['cache'], 'field_warm')
        graph = json.loads((self.output / 'paper-graph.json').read_text('utf-8'))
        self.assertEqual(graph['origin_id'], 'seed')
        self.assertEqual(len(graph['nodes']), 6)

    def test_new_venue_preference_does_not_automatically_reroot_old_graph(self):
        result = self.related('以 TRO RA-L 为主')
        self.assertNotIn('cache', result)
        self.assertFalse((self.output / 'paper-graph.json').exists())
        memory = json.loads((self.output / 'field-research-memory.json').read_text('utf-8'))
        self.assertEqual(len(memory['papers']), 7)
        self.assertTrue(all(row['requires_topic_review'] for row in memory['papers']))
        self.assertFalse(memory['new_search_completed'])

    def test_unparsed_freeform_preference_also_requires_reselection(self):
        result = self.related('着重比较稀疏地图在高速运动中的失效条件')
        self.assertNotIn('cache', result)
        self.assertFalse((self.output / 'paper-graph.json').exists())
        self.assertEqual(result['related_graph_count'], 1)


def public_payload(provider, rows):
    if provider == 'Crossref':
        data = {'message': {'items': [{'DOI': row['doi'], 'title': [row['title']],
                                      'author': [{'given': 'Fixture', 'family': 'Author'}],
                                      'published': {'date-parts': [[2023]]},
                                      'container-title': [row['venue']]} for row in rows]}}
    else:
        data = {'data': [{'paperId': row['doi'], 'title': row['title'], 'year': 2023,
                          'authors': [{'name': 'Fixture Author'}], 'externalIds': {'DOI': row['doi']},
                          'venue': row['venue'], 'citationCount': 3} for row in rows]}
    return {'status': 'ok', 'retrieved_at': '2026-10-13T00:00:00+00:00', 'response': data}


class PublicDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'outputs').mkdir()
        self.store = types.SimpleNamespace(project=self.root)
        self.job = {'task': 'paper_relationships', 'context': {
            'output_dir': 'outputs', 'literature_search': graph_scope(instructions='TRO / RA-L 为主')}}

    def test_discovery_keeps_seed_query_and_ranks_without_excluding_other_venues(self):
        urls = []
        def fetch(url):
            urls.append(url)
            provider = 'Crossref' if 'crossref' in url else 'Semantic Scholar'
            rows = ([{'doi': '10.1000/other', 'title': 'Conference mapping', 'venue': 'IROS'},
                     {'doi': '10.1000/tro', 'title': 'Preferred mapping', 'venue': 'TRO'}]
                    if provider == 'Crossref' else
                    [{'doi': '10.1000/seed', 'title': 'KISS-ICP: In Defense of Point-to-Point ICP', 'venue': 'ICRA'}])
            return {**public_payload(provider, rows), 'url': url}
        with patch.object(public, 'fetch', fetch):
            result = public.discover(self.store, self.job, {'status': 'browser_only'})
        report = json.loads((self.root / 'outputs/discovery.json').read_text('utf-8'))
        self.assertEqual([row['doi'] for row in report['papers']], ['10.1000/seed', '10.1000/tro', '10.1000/other'])
        self.assertEqual(result['candidate_count'], 3)
        for url in urls:
            args = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            self.assertEqual((args.get('query.bibliographic') or args.get('query'))[0], 'KISS-ICP')
            self.assertNotIn('query.container-title', args)

    def test_discovery_fetches_providers_in_parallel_but_saves_stable_order(self):
        both_started = threading.Barrier(2, timeout=3)
        semantic_finished = threading.Event()
        def fetch(url):
            provider = 'Crossref' if 'crossref' in url else 'Semantic Scholar'
            both_started.wait()
            if provider == 'Crossref':
                if not semantic_finished.wait(3):
                    raise AssertionError('Independent provider did not finish')
            else:
                semantic_finished.set()
            return {**public_payload(provider, []), 'url': url}
        with patch.object(public, 'fetch', fetch):
            public.discover(self.store, self.job, {'status': 'browser_only'})
        report = json.loads((self.root / 'outputs/public-citation-responses.json').read_text('utf-8'))
        self.assertEqual([row['provider'] for row in report['responses']], ['Crossref', 'Semantic Scholar'])


class ObservedLock:
    """A real lock with an event proving the second caller reached acquire."""
    def __init__(self):
        self.lock = threading.Lock()
        self.guard = threading.Lock()
        self.call_count = 0
        self.second_attempt = threading.Event()

    def __enter__(self):
        with self.guard:
            self.call_count += 1
            if self.call_count == 2:
                self.second_attempt.set()
        self.lock.acquire()
        return self

    def __exit__(self, *args):
        self.lock.release()


class PublicConcurrencyTests(unittest.TestCase):
    def setUp(self):
        public._next_request.clear()
        public._cooldown.clear()
        public._cache.clear()

    @staticmethod
    def response():
        response = BytesIO(b'{"data": []}')
        response.status = 200
        return response

    def test_independent_provider_network_requests_are_not_globally_serialized(self):
        entered_crossref = threading.Event()
        entered_semantic = threading.Event()
        release = threading.Event()
        def open_request(request, timeout):
            event = entered_crossref if 'crossref' in request.full_url else entered_semantic
            event.set()
            if not release.wait(3):
                raise AssertionError('Fixture request was not released')
            return self.response()
        opener = types.SimpleNamespace(open=open_request)
        with patch.object(public.urllib.request, 'build_opener', return_value=opener), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(public.fetch, 'https://api.crossref.org/works/first')
            try:
                self.assertTrue(entered_crossref.wait(2))
                second = pool.submit(public.fetch, 'https://api.semanticscholar.org/graph/v1/paper/second')
                self.assertTrue(entered_semantic.wait(2), 'Other provider waited behind first network request')
            finally:
                release.set()
            self.assertEqual(first.result(3)['status'], 'ok')
            self.assertEqual(second.result(3)['status'], 'ok')

    def test_same_provider_waits_for_first_request_to_finish(self):
        entered_first = threading.Event()
        entered_second = threading.Event()
        release = threading.Event()
        observed = ObservedLock()
        def open_request(request, timeout):
            if request.full_url.endswith('/first'):
                entered_first.set()
                if not release.wait(3):
                    raise AssertionError('Fixture request was not released')
            else:
                entered_second.set()
            return self.response()
        opener = types.SimpleNamespace(open=open_request)
        with patch.dict(public._provider_locks, {'api.crossref.org': observed}), \
                patch.object(public.urllib.request, 'build_opener', return_value=opener), \
                patch.object(public.time, 'sleep', lambda *args: None), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(public.fetch, 'https://api.crossref.org/works/first')
            try:
                self.assertTrue(entered_first.wait(2))
                second = pool.submit(public.fetch, 'https://api.crossref.org/works/second')
                self.assertTrue(observed.second_attempt.wait(2), 'Second fetch never reached the provider lock')
                self.assertFalse(entered_second.is_set())
            finally:
                release.set()
            self.assertEqual(first.result(3)['status'], 'ok')
            self.assertEqual(second.result(3)['status'], 'ok')
            self.assertTrue(entered_second.is_set())

    def test_429_cooldown_skips_later_request_without_blocking_other_provider(self):
        called = []
        def open_request(request, timeout):
            called.append(request.full_url)
            if 'crossref' in request.full_url:
                raise urllib.error.HTTPError(request.full_url, 429, 'Rate limited',
                                             {'Retry-After': '3600'}, BytesIO(b'{}'))
            return self.response()
        opener = types.SimpleNamespace(open=open_request)
        with patch.object(public.urllib.request, 'build_opener', return_value=opener):
            first = public.fetch('https://api.crossref.org/works/first')
            skipped = public.fetch('https://api.crossref.org/works/second')
            independent = public.fetch('https://api.semanticscholar.org/graph/v1/paper/other')
        self.assertEqual(first['http_status'], 429)
        self.assertTrue(first['request_sent'])
        self.assertEqual(skipped['status'], 'rate_limited')
        self.assertFalse(skipped['request_sent'])
        self.assertGreater(skipped['retry_after_seconds'], 3500)
        self.assertEqual(independent['status'], 'ok')
        self.assertEqual(len(called), 2)


if __name__ == '__main__':
    unittest.main()
