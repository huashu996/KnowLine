"""Check draft reuse without network calls or production state writes."""
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

APP = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(APP), str(APP / '.build-tools')]
from backend import research_prepare
from backend.safety import atomic_json, digest
from PyInstaller.archive.readers import CArchiveReader


def packaged_module():
    runtime = APP / 'Knowline/Knowline.updated.exe'
    if not runtime.exists():
        runtime = APP / 'Knowline/Knowline.exe'
    code = CArchiveReader(str(runtime)).open_embedded_archive('PYZ.pyz').extract('backend.research_prepare')
    module = types.ModuleType('backend.research_prepare')
    module.__package__ = 'backend'
    exec(code, module.__dict__)
    return module


class GraphRetry(unittest.TestCase):
    def exercise(self, change=None):
        for module in (research_prepare, packaged_module()):
            with self.subTest(module=module, change=change), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                output = project / 'outputs/test'
                output.mkdir(parents=True)
                source = {'url': 'https://example.com/paper', 'retrieved_at': '2026-10-11'}
                graph = {'schema_version': 1, 'origin_id': 'p1', 'edges': [], 'nodes': [
                    {'id': 'p1', 'title': 'Starting paper', 'authors': ['Author'],
                     'year': 2021, 'venue': 'Journal', 'metadata_source': source},
                    {'id': 'p2', 'title': 'Related paper', 'authors': ['Author'],
                     'year': 2023, 'venue': 'Journal', 'metadata_source': source}]}
                graph_file = output / '论文星图.json'
                if change == 'scope':
                    graph['nodes'][1]['year'] = 2020
                atomic_json(graph_file, graph)
                manifest = {'job_id': 'j_test', 'paper_graph_artifact': 'outputs/test/论文星图.json',
                            'artifacts': [{'path': 'outputs/test/论文星图.json', 'sha256': digest(graph_file)}]}
                if change == 'owner':
                    manifest['job_id'] = 'j_other'
                atomic_json(output / 'result.previous.json', manifest)
                if change == 'hash':
                    graph['nodes'][0]['title'] = 'Changed after manifest'
                    atomic_json(graph_file, graph)
                job = {'id': 'j_test', 'task': 'paper_relationships', 'context': {
                    'output_dir': 'outputs/test', 'literature_search': {
                        'from_year': 2021, 'to_year': 2026, 'target_count': 20}}}
                store = types.SimpleNamespace(project=project)
                before = graph_file.read_bytes()
                result = module.retry_graph(store, job)
                self.assertEqual(graph_file.read_bytes(), before)
                if change:
                    self.assertIsNone(result)
                else:
                    self.assertEqual(result['path'], manifest['paper_graph_artifact'])
                    self.assertEqual(result['node_count'], 2)
                    self.assertTrue(result['requires_agent_review'])
                    self.assertFalse(result['new_search_completed'])
                    prepared = module.prepare(store, job)
                    self.assertEqual(prepared['cache'], 'retry_draft')

    def test_localized_filename_is_resumed(self):
        self.exercise()

    def test_changed_graph_is_not_reused(self):
        self.exercise('hash')

    def test_other_job_manifest_is_not_reused(self):
        self.exercise('owner')

    def test_out_of_scope_graph_is_not_reused(self):
        self.exercise('scope')


if __name__ == '__main__':
    unittest.main()
