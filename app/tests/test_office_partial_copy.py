"""Exercise the actual copy-office endpoint without opening user documents."""
import asyncio
import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / 'scripts'))
from patch_frozen_modules import module_code

EXE = None
if '--exe' in sys.argv:
    index = sys.argv.index('--exe')
    EXE = Path(sys.argv[index + 1])
    del sys.argv[index:index + 2]

package = types.ModuleType('_office_copy_tests')
package.__path__ = [str(APP / 'backend')]
sys.modules[package.__name__] = package
from _office_copy_tests.safety import DomainError, contained, digest

code = module_code(EXE, 'backend.app') if EXE else compile((APP / 'backend/app.py').read_bytes(), 'backend/app.py', 'exec')
create = next(value for value in code.co_consts if isinstance(value, types.CodeType) and value.co_name == 'create_app')
endpoint = next(value for value in create.co_consts if isinstance(value, types.CodeType) and value.co_name == 'copy_office')


class CopyEndpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'accepted.docx'
        self.path.write_bytes(b'test artifact; native copy is mocked')
        self.job = {'id': 'j_test', 'revision': 4, 'task': 'copy_office_selection', 'status': 'partial',
                    'context': {'office_selection': {'target': 'word'}},
                    'result': {'partial': True, 'warnings': ['Clipped source edge'],
                               'office_fragment': {'path': 'accepted.docx', 'target': 'word'},
                               'artifacts': [{'path': 'accepted.docx', 'sha256': digest(self.path)}]}}
        self.calls = []
        def check(job, body):
            if body['base_revision'] != job['revision']:
                raise DomainError('revision_conflict')
        store = types.SimpleNamespace(job=lambda _: self.job, check=check)
        def copy(path, target):
            self.calls.append((path, target))
            return {'copied': True, 'target': target}
        clipboard = types.ModuleType('_office_copy_tests.office_clipboard')
        clipboard.copy = copy
        sys.modules[clipboard.__name__] = clipboard
        values = {'project': self.root, 'store': store}
        closure = tuple(types.CellType(values[name]) for name in endpoint.co_freevars)
        self.invoke = types.FunctionType(endpoint, {'__package__': '_office_copy_tests', 'DomainError': DomainError,
                                        'contained': contained, 'digest': digest, 'asyncio': asyncio}, closure=closure)

    async def test_partial_and_complete_accepted_artifacts_can_copy(self):
        for status in ('partial', 'completed'):
            self.job['status'] = status
            self.assertTrue((await self.invoke('j_test', {'base_revision': 4}))['copied'])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.job['result']['warnings'], ['Clipped source edge'])

    async def test_incomplete_or_failed_jobs_remain_blocked(self):
        for status in ('running', 'queued', 'failed', 'interrupted', 'waiting_user'):
            self.job['status'] = status
            with self.assertRaises(DomainError) as caught:
                await self.invoke('j_test', {'base_revision': 4})
            self.assertEqual(caught.exception.code, 'office_fragment_not_ready')
        self.assertFalse(self.calls)

    async def test_modified_artifact_remains_blocked(self):
        self.path.write_bytes(b'modified')
        with self.assertRaises(DomainError) as caught:
            await self.invoke('j_test', {'base_revision': 4})
        self.assertEqual(caught.exception.code, 'artifact_hash_mismatch')
        self.assertFalse(self.calls)

    async def test_missing_artifact_and_wrong_target_remain_blocked(self):
        self.job['result']['artifacts'] = []
        with self.assertRaises(DomainError):
            await self.invoke('j_test', {'base_revision': 4})
        self.job['result']['artifacts'] = [{'path': 'accepted.docx', 'sha256': digest(self.path)}]
        self.job['result']['office_fragment']['target'] = 'powerpoint'
        with self.assertRaises(DomainError):
            await self.invoke('j_test', {'base_revision': 4})
        self.assertFalse(self.calls)

    async def test_stale_revision_remains_blocked(self):
        with self.assertRaises(DomainError) as caught:
            await self.invoke('j_test', {'base_revision': 3})
        self.assertEqual(caught.exception.code, 'revision_conflict')
        self.assertFalse(self.calls)


if __name__ == '__main__':
    unittest.main()
