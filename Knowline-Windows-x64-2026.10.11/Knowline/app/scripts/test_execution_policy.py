"""Regression checks against both source and the staged frozen runtime."""
from pathlib import Path
import sys
import types
import unittest

APP = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(APP), str(APP / '.build-tools')]
from backend import research_policy, institutional_access
from backend.safety import DomainError
from PyInstaller.archive.readers import CArchiveReader


def frozen_module(name):
    runtime = APP / 'Knowline/Knowline.updated.exe'
    if not runtime.exists():
        runtime = APP / 'Knowline/Knowline.exe'
    archive = CArchiveReader(str(runtime))
    code = archive.open_embedded_archive('PYZ.pyz').extract(name)
    module = types.ModuleType(name)
    module.__package__ = 'backend'
    exec(code, module.__dict__)
    return module


class ExecutionRegression(unittest.TestCase):
    def test_source_and_packaged_tasks_ignore_legacy_deadlines(self):
        for policy in (research_policy, frozen_module('backend.research_policy')):
            for task in ('replicate_paper_figure', 'proposal_word', 'proposal_ppt',
                         'copy_office_selection', 'paper_relationships', 'read_resources',
                         'build_knowledge', 'verify_paper_metadata', 'future_task'):
                for budget in (None, 0, 1, 300, 600, 3600):
                    with self.subTest(module=policy, task=task, budget=budget):
                        self.assertIsNone(policy.total_budget({'task': task, 'context': {
                            'literature_search': {'time_budget_seconds': budget}}}))

    def test_sparse_pdf_identity_uses_verified_citation_fields(self):
        for module in (institutional_access, frozen_module('backend.institutional_access')):
            target = {'doi': '10.1234/test', 'title': 'Verified paper title',
                      'authors': ['Alice Researcher'], 'pdf_identity': {'arxiv_id': '2601.12345'}}
            identity = module.normalized_pdf_identity(target)
            self.assertEqual(identity['title'], target['title'])
            self.assertEqual(identity['authors'], target['authors'])
            self.assertEqual(identity['doi'], target['doi'])
            self.assertEqual(target['pdf_identity'], {'arxiv_id': '2601.12345'})

    def test_malformed_identity_remains_rejected(self):
        for module in (institutional_access, frozen_module('backend.institutional_access')):
            for supplied in ({'title': None}, {'title': ''}, {'authors': []}, 'not-a-mapping'):
                with self.subTest(module=module, supplied=supplied):
                    with self.assertRaises(DomainError) as caught:
                        module.normalized_pdf_identity({'doi': '10.1234/test',
                            'title': 'Verified title', 'authors': ['Alice Researcher'],
                            'pdf_identity': supplied})
                    self.assertEqual(caught.exception.code, 'institution_identity_required')


if __name__ == '__main__':
    unittest.main()
