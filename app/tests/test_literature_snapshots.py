"""Import receipts remain valid when a later annotation creates a new PDF head.

Snapshot ownership/hash checks and receipt loading use the production methods;
PDF parsing and bibliography lookup are isolated from network and the live store.
"""
from contextlib import contextmanager
import copy
import json
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
    i = sys.argv.index('--exe'); EXE = Path(sys.argv[i + 1]); del sys.argv[i:i + 2]
PACKAGE = '_literature_snapshot_tests'
package = types.ModuleType(PACKAGE); package.__path__ = [str(APP / 'backend')]
sys.modules[PACKAGE] = package


def code(name):
    return module_code(EXE, 'backend.' + name) if EXE else compile((APP / 'backend' / (name + '.py')).read_bytes(), name, 'exec')


def load(name):
    module = types.ModuleType(PACKAGE + '.' + name); module.__package__ = PACKAGE
    sys.modules[module.__name__] = module; exec(code(name), module.__dict__)
    return module


def stub(name, **values):
    module = types.ModuleType(PACKAGE + '.' + name); module.__dict__.update(values)
    sys.modules[module.__name__] = module
    return module


safety = load('safety')
literature = load('literature_results')
store_code = next(c for c in code('store').co_consts if isinstance(c, types.CodeType) and c.co_name == 'Store')
store_globals = dict(DomainError=safety.DomainError, contained=safety.contained, digest=safety.digest,
                     json=json, now=lambda: '2026-10-11T15:30:00+00:00')


def store_method(name):
    fn = next(c for c in store_code.co_consts if isinstance(c, types.CodeType) and c.co_name == name)
    return types.FunctionType(fn, store_globals, name)


@contextmanager
def open_pdf(path):
    yield [Path(path).read_bytes()]


stub('pdf', open_pdf=open_pdf)
stub('paper_bibliography', get=lambda store, id: store.records[id])
identity_paths = []
stub('institutional_access', validate_pdf=lambda path, record: identity_paths.append(Path(path)))


class Store:
    snapshot = store_method('snapshot')
    audit_literature_job = store_method('audit_literature_job')

    def __init__(self, root):
        self.project = root
        self.original = root / 'original.pdf'; self.original.write_bytes(b'original verified paper')
        self.annotated = root / 'annotated.pdf'; self.annotated.write_bytes(b'original verified paper plus highlight')
        self.resource_value = dict(id='r1', type='paper', state='ready', version_id='v2',
                                   sha256=safety.digest(self.annotated), metadata={'metadata_status': 'verified'})
        self.versions = {('v1', 'r1'): dict(snapshot_path='original.pdf', sha256=safety.digest(self.original)),
                         ('v2', 'r1'): dict(snapshot_path='annotated.pdf', sha256=safety.digest(self.annotated))}
        self.domain = dict(id='g1', resource_ids=['r1'])
        self.records = {'pr1': dict(domain_ids=['g1'], metadata_status='verified', latest_verified=True, publication_status='published')}
        (root / 'outputs/task').mkdir(parents=True)
        self.job_value = dict(id='j1', task='discover_papers', status='failed', revision=4, result=None,
            context=dict(scope={'domain_id': 'g1'}, literature_search={'target_count': 1}, output_dir='outputs/task'))
        self.ingested = None

    def one(self, sql, parameters):
        return self.versions.get(tuple(parameters))

    def groups(self): return [self.domain]
    def resource(self, id): return self.resource_value
    def job(self, id): return copy.deepcopy(self.job_value)
    def check(self, job, body):
        if job['revision'] != body.get('base_revision'): raise safety.DomainError('revision_conflict')

    def ingest_job(self, id, body):
        self.ingested = copy.deepcopy(body['manifest'])
        # Represents the mandatory full ingestion gate; it is not a status setter.
        if self.ingested.get('bad_artifact'): raise safety.DomainError('artifact_hash_mismatch')
        status = literature.validate(self, self.job_value, self.ingested)
        return dict(id=id, status=status, result=self.ingested)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name)); identity_paths.clear()
        self.row = dict(candidate_id='c1', title='Paper', resource_id='r1', version_id='v1',
                        sha256=safety.digest(self.store.original), citation_record_id='pr1')
        self.result = dict(schema_version=2, job_id='j1', status='completed', partial=False,
                           imported_papers=[self.row], artifacts=[dict(path='outputs/task/report.md', sha256='fixture')])

    def validate(self): return literature.validate(self.store, self.store.job_value, self.result)

    def test_annotation_head_does_not_invalidate_import_receipt(self):
        before = copy.deepcopy(self.row)
        self.assertEqual(self.validate(), 'completed')
        self.assertEqual(identity_paths, [self.store.original])
        self.assertEqual(self.row['version_id'], before['version_id'])
        self.assertEqual(self.row['sha256'], before['sha256'])
        self.assertEqual(self.store.annotated.read_bytes(), b'original verified paper plus highlight')

    def test_current_version_still_passes(self):
        self.row.update(version_id='v2', sha256=safety.digest(self.store.annotated))
        self.assertEqual(self.validate(), 'completed')
        self.assertEqual(identity_paths, [self.store.annotated])

    def test_missing_version_does_not_fall_back_to_current(self):
        for value in [None, '', 'missing']:
            self.row['version_id'] = value
            with self.subTest(value=value), self.assertRaisesRegex(safety.DomainError, 'discovery_import_scope_mismatch'):
                self.validate()
        self.assertEqual(identity_paths, [])

    def test_another_resources_version_is_rejected(self):
        self.store.versions[('v_foreign', 'r_other')] = self.store.versions[('v1', 'r1')]
        self.row['version_id'] = 'v_foreign'
        with self.assertRaisesRegex(safety.DomainError, 'discovery_import_scope_mismatch'): self.validate()

    def test_receipt_must_match_its_version_hash_not_current_hash(self):
        self.row['sha256'] = safety.digest(self.store.annotated)
        with self.assertRaisesRegex(safety.DomainError, 'discovery_import_scope_mismatch'): self.validate()

    def test_corrupt_original_snapshot_is_rejected(self):
        self.store.original.write_bytes(b'changed')
        with self.assertRaisesRegex(safety.DomainError, 'snapshot_corrupt'): self.validate()

    def test_membership_and_verification_are_not_waived(self):
        self.store.domain['resource_ids'] = []
        with self.assertRaisesRegex(safety.DomainError, 'discovery_import_scope_mismatch'): self.validate()
        self.store.domain['resource_ids'] = ['r1']
        self.store.records['pr1']['latest_verified'] = False
        with self.assertRaisesRegex(safety.DomainError, 'public_citation_verification_required'): self.validate()

    def test_recovery_uses_full_ingestion_without_rewriting_original_receipt(self):
        path = self.store.project / 'outputs/task/result.json'
        path.write_text(json.dumps(self.result), 'utf-8'); before = path.read_bytes()
        result = self.store.audit_literature_job('j1', {'base_revision': 4})
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['result']['completion_audit']['previous_status'], 'failed')
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.store.ingested['imported_papers'][0]['version_id'], 'v1')

    def test_recovery_cannot_skip_artifact_validation(self):
        self.result['bad_artifact'] = True
        path = self.store.project / 'outputs/task/result.json'
        path.write_text(json.dumps(self.result), 'utf-8')
        with self.assertRaisesRegex(safety.DomainError, 'artifact_hash_mismatch'):
            self.store.audit_literature_job('j1', {'base_revision': 4})

    def test_recovery_rejects_active_tasks_and_wrong_revision(self):
        self.store.job_value['status'] = 'running'
        with self.assertRaisesRegex(safety.DomainError, 'job_already_claimed'):
            self.store.audit_literature_job('j1', {'base_revision': 4})
        self.store.job_value['status'] = 'failed'
        with self.assertRaisesRegex(safety.DomainError, 'revision_conflict'):
            self.store.audit_literature_job('j1', {'base_revision': 3})


if __name__ == '__main__': unittest.main(verbosity=2)
