"""Receipt finalization keeps the existing immutable-PDF acceptance gate."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from test_literature_snapshots import Store, load, literature, safety, code

finish = load('discovery_finish')


class FinishTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.project = Path(directory.name)
        self.store = Store(self.project)
        self.job = self.store.job_value
        self.job['context'].update(task='discover_papers', job_id='j1')
        self.context = self.job['context']
        self.context_path = self.project / 'context.json'
        self.output = self.project / self.context['output_dir']
        self.record = self.store.records['pr1']
        self.record.update(id='pr1', title='Paper', doi='10.1/paper', year=2022, venue='Journal')
        self.row = dict(candidate_id='c1', resource_id='r1', version_id='v1',
                        sha256=safety.digest(self.store.original), new_download=True)
        safety.atomic_json(self.context_path, self.context)

    def save(self, row=None):
        finish.record_receipt(self.store, self.job, self.record, row or self.row)

    def result(self, reason=None):
        finish.finalize(self.project, self.context_path, reason)
        return json.loads((self.output / 'result.json').read_text('utf-8'))

    def test_finish_accepts_original_import_after_annotation_without_reports(self):
        self.save()
        result = self.result()
        self.assertEqual(literature.validate(self.store, self.job, result), 'completed')
        self.assertEqual(result['imported_papers'][0]['version_id'], 'v1')
        self.assertEqual(result['claims'], [])
        self.assertEqual(result['proposed_relations'], [])
        self.assertEqual({p.name for p in self.output.iterdir()}, {finish.RECEIPTS, 'result.json'})
        artifact = result['artifacts'][0]
        self.assertEqual(artifact['sha256'], safety.digest(self.project / artifact['path']))

    def test_replaced_failure_does_not_prevent_met_target(self):
        self.save({'candidate_id':'missing', 'unavailable_reason':'publisher_timeout'})
        self.save()
        result = self.result()
        self.assertFalse(result['partial'])
        self.assertEqual(literature.validate(self.store, self.job, result), 'completed')
        self.assertEqual(result['imported_papers'][0]['unavailable_reason'], 'publisher_timeout')

    def test_duplicates_cannot_fill_quota_and_shortfall_needs_reason(self):
        self.context['literature_search']['target_count'] = 2
        safety.atomic_json(self.context_path, self.context)
        self.save(); self.save({**self.row, 'candidate_id':'same_paper'})
        with self.assertRaisesRegex(safety.DomainError, 'discovery_incomplete_reason_required'):
            self.result()
        self.assertFalse((self.output / 'result.json').exists())
        result = self.result('No more relevant candidates in the bounded sources')
        self.assertTrue(result['partial'])
        self.assertEqual(literature.validate(self.store, self.job, result), 'partial')
        self.assertEqual(result['literature_summary']['imported_count'], 1)

    def test_zero_candidates_is_honest_failed_result(self):
        result = self.result('No candidates matched the requested topic and year')
        self.assertEqual(result['imported_papers'], [])
        self.assertEqual(literature.validate(self.store, self.job, result), 'failed')
        self.assertTrue(result['warnings'])

    def test_metadata_without_pdf_is_partial(self):
        self.save({'candidate_id':'c1', 'unavailable_reason':'no_public_pdf'})
        result = self.result('Public sources exhausted for this run')
        self.assertEqual(literature.validate(self.store, self.job, result), 'partial')

    def test_repeated_failed_call_does_not_erase_success(self):
        self.save(); self.save({'candidate_id':'c1', 'unavailable_reason':'timeout'})
        self.assertEqual(literature.validate(self.store, self.job, self.result()), 'completed')

    def test_other_job_domain_or_malformed_receipt_cannot_finalize(self):
        self.save(); path = self.output / finish.RECEIPTS
        original = json.loads(path.read_text('utf-8'))
        for key, value in [('job_id','other'), ('domain_id','other'), ('rows',[None])]:
            safety.atomic_json(path, {**original, key:value})
            with self.subTest(key=key), self.assertRaises(safety.DomainError): self.result()
        safety.atomic_json(path, original)
        original['rows'][0].pop('version_id')
        safety.atomic_json(path, original)
        with self.assertRaises(safety.DomainError): self.result()

    def test_changed_pdf_or_wrong_membership_still_rejected_by_acceptance(self):
        self.save(); result = self.result()
        self.store.domain['resource_ids'] = []
        with self.assertRaises(safety.DomainError): literature.validate(self.store, self.job, result)
        self.store.domain['resource_ids'] = ['r1']
        self.store.original.write_bytes(b'corrupt')
        with self.assertRaises(safety.DomainError): literature.validate(self.store, self.job, result)

    def test_other_task_and_output_escape_are_rejected(self):
        for change in [{'task':'proposal_word'}, {'output_dir':'../outside'}]:
            safety.atomic_json(self.context_path, {**self.context, **change})
            with self.subTest(change=change), self.assertRaises(safety.DomainError): self.result('none')

    def test_new_cli_collects_old_service_receipts_without_reimport_or_restart(self):
        import types
        fn_code = next(c for c in code('cli').co_consts
                       if isinstance(c, types.CodeType) and c.co_name == 'acquire_manifest')
        fn = types.FunctionType(fn_code, {'__package__':finish.__package__}, 'acquire_manifest')
        calls = []
        def request(path, body=None):
            calls.append((path, body is not None))
            if path == '/jobs/j1': return self.job
            if path == '/institutional/acquire': return {**self.row, 'status':'imported', 'citation_record_id':'pr1'}
            if path == '/paper-records/pr1': return self.record
            if path == '/resources/r1': return self.store.resource_value
            self.fail('Unexpected API: '+path)
        response = fn(request, 'j1', [{'candidate_id':'c1'}], self.project)
        self.assertTrue(response['results'][0]['receipt_saved'])
        self.assertEqual([p for p, mutation in calls if mutation], ['/institutional/acquire'])
        self.assertEqual(literature.validate(self.store, self.job, self.result()), 'completed')

        def current_request(path, body=None):
            if path == '/jobs/j1': return self.job
            if path == '/institutional/acquire': return response['results'][0]
            self.fail('A current service receipt must not be collected twice')
        fn(current_request, 'j1', [{'candidate_id':'c1'}], self.project)
        self.assertEqual(len(self.result()['imported_papers']), 1)

    def test_instruction_uses_one_finish_and_excludes_generic_finalizer(self):
        # Inspect the actual instruction function without importing the server stack.
        import types
        instructions_code = next(c for c in code('codex_runner').co_consts
                                 if isinstance(c, types.CodeType) and c.co_name == 'instructions')
        fn = types.FunctionType(instructions_code, {'__package__':finish.__package__, 'contained':safety.contained,
            'app_dir':lambda project: project/'app', 'Path':Path,
            'public_fallback_allowed':lambda job:False}, 'instructions')
        job = copy.deepcopy(self.job)
        job['context_path'] = str(self.context_path)
        job['context']['literature_search'].update(query='visual SLAM',from_year=2020,to_year=2026)
        text = fn(self.store, job, automatic=True)
        self.assertIn('app/scripts/discovery_finish.py', text)
        self.assertNotIn('app/scripts/research_finalize.py', text)
        self.assertIn('不另外生成资料解读', text)
        self.assertIn('完成 result.json 后退出', text)


if __name__ == '__main__': unittest.main()
