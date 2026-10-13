"""Regression tests for graph-wide versus per-paper timeouts (stdlib only)."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
EXE = None
if '--exe' in sys.argv:
    index = sys.argv.index('--exe')
    EXE = Path(sys.argv[index + 1])
    del sys.argv[index:index + 2]
sys.path.insert(0, str(APP / 'scripts'))
from patch_frozen_modules import module_code

PACKAGE = '_knowline_timeout_test'
package = types.ModuleType(PACKAGE)
package.__path__ = [str(APP / 'backend')]
sys.modules[PACKAGE] = package


def stub(name, **values):
    module = types.ModuleType(PACKAGE + '.' + name)
    module.__dict__.update(values)
    sys.modules[module.__name__] = module
    return module


stub('store', uid=lambda prefix: prefix + '_test')
stub('paper_bibliography', rows=lambda store: [])
stub('institutional_access', validate_pdf=lambda *args: None)
stub('research_enrich', matching=lambda *args, **kwargs: None)
stub('paper_graph', validate=lambda *args: None)
abstract = stub('paper_abstract', add_local_abstract=lambda store, node, *args: dict(node))


def load(name):
    module = types.ModuleType(PACKAGE + '.' + name)
    module.__package__ = PACKAGE
    sys.modules[module.__name__] = module
    code = module_code(EXE, 'backend.' + name) if EXE else compile((APP / 'backend' / (name + '.py')).read_bytes(), str(APP / 'backend' / (name + '.py')), 'exec')
    exec(code, module.__dict__)
    return module


worker = load('agent_worker')
graph = load('graph_fulltext')


class GraphTimeoutTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'outputs').mkdir()
        self.store = types.SimpleNamespace(project=self.root, resources=lambda: [])
        self.job = {'id': 'job_test', 'context': {'external_network': 'user_requested_search',
                    'literature_search': {}, 'output_dir': 'outputs'}}
        self.broker = types.SimpleNamespace(graph_candidates={})

    async def run_graph(self, nodes):
        return await graph.prepare(self.store, self.job, {'nodes': nodes}, None, self.broker)

    async def test_slow_paper_does_not_fail_graph_or_later_papers(self):
        async def acquire(store, job, node, *args):
            await asyncio.sleep(.6 if node['id'] == 'slow' else .005)
            return {'resource_id': 'r_' + node['id'], 'version_id': 'v1', 'sha256': 'test'}
        nodes = [{'id': name, 'title': name} for name in ['slow', 'one', 'two', 'three', 'four', 'five']]
        nodes[0]['abstract'] = 'Existing verified abstract'
        # Windows filesystem/AV scheduling can exceed 40 ms while writing the
        # progress file; keep a clear separation from the simulated slow paper.
        with patch.object(graph, 'PAPER_ACQUISITION_TIMEOUT_SECONDS', .2), patch.object(graph, 'acquire_node', acquire):
            result, report = await self.run_graph(nodes)
        self.assertEqual(len(result), 6)
        self.assertEqual(report['pdf_saved'], 5)
        self.assertEqual(result[0]['full_text_reason'], 'paper_acquisition_timeout')
        self.assertEqual(result[0]['abstract'], nodes[0]['abstract'])
        self.assertEqual(result[-1]['full_text_status'], 'acquired')
        self.assertFalse(self.broker.graph_candidates)
        self.assertEqual(len(json.loads((self.root / 'outputs/graph-fulltext-progress.json').read_text())['rows']), 6)

    async def test_abstract_timeout_keeps_pdf_and_other_abstracts(self):
        async def acquire(store, job, node, *args):
            return {'resource_id': 'r_' + node['id'], 'version_id': 'v1', 'sha256': 'test'}
        def extract(store, node, *args):
            if node['id'] == 'slow':
                time.sleep(.12)
            return {**node, 'abstract': 'Verified local PDF abstract'}
        with patch.object(graph, 'ABSTRACT_TIMEOUT_SECONDS', .04), patch.object(graph, 'acquire_node', acquire), patch.object(abstract, 'add_local_abstract', extract):
            result, report = await self.run_graph([{'id': name, 'title': name} for name in ['slow', 'fast']])
        self.assertEqual(report['pdf_saved'], 2)
        self.assertEqual(result[0]['full_text_status'], 'acquired')
        self.assertEqual(result[0]['abstract_unavailable_reason'], 'paper_abstract_timeout')
        self.assertEqual(result[1]['abstract_status'], 'available')

    async def test_user_cancellation_propagates_and_stops_all_papers(self):
        active = set()
        async def acquire(store, job, node, *args):
            active.add(node['id'])
            try:
                await asyncio.sleep(60)
            finally:
                active.discard(node['id'])
        with patch.object(graph, 'acquire_node', acquire):
            task = asyncio.create_task(self.run_graph([{'id': str(i), 'title': str(i)} for i in range(6)]))
            await asyncio.sleep(.02)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertFalse(active)
        self.assertFalse(self.broker.graph_candidates)


class WorkerRequestTests(unittest.TestCase):
    def test_ingestion_waits_without_reintroducing_a_total_deadline(self):
        """Exercise the actual worker run/claim/execute/ingest request path."""
        from io import BytesIO
        class Done(BaseException):
            pass
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.knowledge/agent-probe').mkdir(parents=True)
            (root / '.knowledge/agent-local.json').write_text('{"key":"test-only"}')
            (root / 'outputs').mkdir()
            config = root / 'adapter.json'
            config.write_text('{"argv":["test-executor"]}')
            submitted = threading.Event()
            calls = []
            delivered = False
            job = {'id': 'j_test', 'revision': 1, 'context': {'output_dir': 'outputs',
                   'literature_search': {'time_budget_seconds': 600}}}
            def response(value):
                return BytesIO(json.dumps(value).encode())
            def urlopen(request, timeout=None):
                nonlocal delivered
                path = request.full_url.split('/api/v1')[1]
                calls.append((path, timeout))
                if path == '/health': return response({'project_id': worker.identity(root)})
                if path == '/session': return response({'token': 'test-only'})
                if path == '/agent/probe': return response({'prompt': 'test', 'result': str(root / 'proof.json'), 'agent_id': 'test'})
                if path == '/agent/next':
                    if not delivered:
                        delivered = True
                        return response({'job': job, 'lease': 'test', 'prompt': 'test', 'timeout_seconds': 600})
                    submitted.wait(2)
                    raise Done()
                if path.endswith('/ingest'):
                    # Model the old 180-second read timeout without sleeping
                    # three minutes. Only an unbounded request can finish.
                    if timeout is not None:
                        raise TimeoutError('slow full-text enrichment')
                    submitted.set()
                return response({})
            def execute(command, prompt, project, prompt_file, result_file, heartbeat, timeout):
                if result_file.name == 'result.json':
                    self.assertIsNone(timeout)  # legacy frozen budgets are ignored
                    result_file.write_text('{"schema_version":2}')
            args = types.SimpleNamespace(project=str(root), port=12345, action='worker', command_file=str(config))
            with patch.object(worker.urllib.request, 'urlopen', urlopen), patch.object(worker, 'execute', execute):
                with self.assertRaises(Done):
                    worker.run(args)
            self.assertTrue(submitted.is_set())
            self.assertIn(('/jobs/j_test/ingest', None), calls)
            self.assertIn(('/agent/heartbeat', 15), calls)
            self.assertFalse(any(path.endswith('/fail') for path, _ in calls))


if __name__ == '__main__':
    unittest.main()
