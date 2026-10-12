"""Exercise source and packaged ingest callbacks without touching project data."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(APP), str(APP / '.build-tools')]
from backend.safety import DomainError, atomic_json, contained, digest
from PyInstaller.archive.readers import CArchiveReader


def find_code(code, name):
    if code.co_name == name:
        return code
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            found = find_code(value, name)
            if found is not None:
                return found


def module_code(name, packaged):
    if not packaged:
        return compile((APP / (name.replace('.', '/') + '.py')).read_bytes(), name, 'exec')
    runtime = APP / 'Knowline/Knowline.updated.exe'
    if not runtime.exists():
        runtime = APP / 'Knowline/Knowline.exe'
    return CArchiveReader(str(runtime)).open_embedded_archive('PYZ.pyz').extract(name)


def callback(code, values):
    globals_ = dict(__package__='backend', DomainError=DomainError,
                    contained=contained, digest=digest, atomic_json=atomic_json)
    closure = tuple(types.CellType(values[name]) for name in code.co_freevars)
    return types.FunctionType(code, globals_, closure=closure or None)


class GraphIngestHashes(unittest.TestCase):
    def exercise(self, packaged, tamper=None):
        with tempfile.TemporaryDirectory(prefix='knowline-ingest-test-') as directory:
            root = Path(directory)
            output = root / 'outputs/test'
            output.mkdir(parents=True)
            names = ['paper-graph.json', 'graph-fulltext-progress.json',
                     'publication-prefetch.json', 'evidence.json']
            for name in names:
                atomic_json(output / name, {'before': name})
            manifest = {'paper_graph_artifact': 'outputs/test/paper-graph.json',
                        'artifacts': [{'path': 'outputs/test/' + name,
                                       'sha256': digest(output / name)} for name in names]}
            job = {'task': 'paper_relationships', 'status': 'running',
                   'context': {'output_dir': 'outputs/test'}}
            state = {'enriched': False, 'accepted': False}
            store = types.SimpleNamespace(project=root, job=lambda _: job,
                                          check=lambda *args: None)

            async def enrich(*args, **kwargs):
                state['enriched'] = True
                for name in names[:3]:
                    atomic_json(output / name, {'after': name})

            async def write(kind, body, action):
                return action()

            def validate(id, body, request):
                for item in body['manifest']['artifacts']:
                    self.assertEqual(digest(root / item['path']), item['sha256'])
                return {'status': 'partial'}

            async def accepted(id):
                state['accepted'] = True

            codex = types.SimpleNamespace(guard=lambda *args: None,
                                          ingest_result=validate, accepted=accepted)
            helper = callback(find_code(module_code('backend.research_enrich', packaged),
                                        'enrichment_artifacts'), {})
            fake_enrich = types.ModuleType('backend.research_enrich')
            fake_enrich.enrichment_artifacts = helper
            fake_enrich.artifact = enrich
            ingest = callback(find_code(module_code('backend.app', packaged), 'ingest'),
                              dict(codex=codex, store=store, write=write,
                                   institutional_broker=None))
            if tamper:
                atomic_json(output / tamper, {'unexpected': 'changed after submission'})
            with patch.dict(sys.modules, {'backend.research_enrich': fake_enrich}):
                if tamper:
                    with self.assertRaises(DomainError) as caught:
                        asyncio.run(ingest('test', {'manifest': manifest}, None))
                    self.assertEqual(caught.exception.code, 'artifact_hash_mismatch')
                    self.assertFalse(state['enriched'])
                    self.assertFalse(state['accepted'])
                else:
                    result = asyncio.run(ingest('test', {'manifest': manifest}, None))
                    self.assertEqual(result['status'], 'partial')
                    self.assertTrue(state['accepted'])
                    self.assertEqual(json.loads((output / 'result.json').read_text()), manifest)

    def test_service_generated_hashes_updated(self):
        for packaged in (False, True):
            with self.subTest(packaged=packaged):
                self.exercise(packaged)

    def test_changed_evidence_rejected_before_enrichment(self):
        for packaged in (False, True):
            with self.subTest(packaged=packaged):
                self.exercise(packaged, 'evidence.json')

    def test_changed_progress_rejected_before_enrichment(self):
        for packaged in (False, True):
            with self.subTest(packaged=packaged):
                self.exercise(packaged, 'graph-fulltext-progress.json')


if __name__ == '__main__':
    unittest.main()
