"""Offline behavior tests: native Office is substituted, structure checks are real."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('figure_workflow', APP / 'scripts/figure_workflow.py')
fw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fw)


def pptx(path, duplicate=False, outside=False, formula='x', bad_arrow=False):
    p = fw.P[1:-1]
    a = 'http://schemas.openxmlformats.org/drawingml/2006/main'
    m = fw.M[1:-1]
    mc = 'http://schemas.openxmlformats.org/markup-compatibility/2006'
    def shape(identifier, text, x='10000'):
        return f'''<p:sp><p:nvSpPr><p:cNvPr id="{identifier}" name="shape{identifier}"/></p:nvSpPr>
          <p:spPr><a:xfrm><a:off x="{x}" y="10000"/><a:ext cx="10000" cy="10000"/></a:xfrm>
          <a:ln><a:headEnd type="{'open' if bad_arrow else 'none'}"/></a:ln></p:spPr>
          <p:txBody><m:oMath><m:r><m:t>{text}</m:t></m:r></m:oMath></p:txBody></p:sp>'''
    second = shape('1' if duplicate else '2', formula, '99999999' if outside else '30000')
    slide = f'''<p:sld xmlns:p="{p}" xmlns:a="{a}" xmlns:m="{m}" xmlns:mc="{mc}"
           xmlns:a14="http://schemas.microsoft.com/office/drawing/2010/main">
      <p:cSld><p:spTree>{shape('1', 'P')}
      <mc:AlternateContent><mc:Choice Requires="a14">{second}</mc:Choice>
      <mc:Fallback>{second}</mc:Fallback></mc:AlternateContent>
      </p:spTree></p:cSld></p:sld>'''
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('ppt/presentation.xml', f'<p:presentation xmlns:p="{p}"><p:sldSz cx="1000000" cy="1000000"/></p:presentation>')
        z.writestr('ppt/slides/slide1.xml', slide)


class SimulatedService(fw.Workflow):
    calls = 0
    page_calls = 0
    fail_native = False
    job_status = 'running'
    registered = []

    def request(self, path, body=None):
        if path == '/jobs/' + self.job_id:
            return dict(id=self.job_id, status=self.job_status, context=self.context,
                        result={'artifacts': self.registered})
        if path.startswith('/resources/'):
            type(self).page_calls += 1
            return dict(text='Figure 2. Multi-view geometry. Kalman ﬁlter.', version_id='v_test')
        if path.endswith('/office-native'):
            type(self).calls += 1
            if self.fail_native:
                raise fw.DomainError('office_native_failed')
            folder = self.output / 'native-working-review'
            folder.mkdir(exist_ok=True)
            (folder / 'slide-1.png').write_bytes(b'\x89PNG\r\n\x1a\nSIMULATED_PREVIEW')
            fw.atomic_json(folder / 'native-audit.json', {'ok': True})
            return dict(presentation=self.relative(self.working), report={'ok': True},
                        preview_path=self.relative(folder / 'slide-1.png'),
                        audit_path=self.relative(folder / 'native-audit.json'))
        raise AssertionError(path)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root / '.knowledge').mkdir()
        fw.atomic_json(self.root / '.knowledge/config.json', {'port': 21588})
        self.output = self.root / 'outputs/task'
        self.output.mkdir(parents=True)
        (self.output / 'source.png').write_bytes(b'source')
        self.context = dict(job_id='j_test', task='replicate_paper_figure', output_dir='outputs/task',
          figure_selection=dict(target_pptx='outputs/task/figure.pptx', page_index=2,
            image=dict(path='outputs/task/source.png', sha256=fw.digest(self.output / 'source.png'))),
          resources=[dict(resource_id='r_test', version_id='v_test')])
        self.context_path = self.root / 'context.json'
        fw.atomic_json(self.context_path, self.context)
        self.manifest = self.output / 'audit.json'
        fw.atomic_json(self.manifest, dict(delivery_gate=True, require_full_registry=True,
          objects=[{'name': 'shape1'}, {'name': 'shape2'}], expected_formula_count=2,
          expected_axis_constraint_count=0))
        pptx(self.output / 'figure.working.pptx')
        SimulatedService.calls = SimulatedService.page_calls = 0
        SimulatedService.fail_native = False
        SimulatedService.job_status = 'running'
        SimulatedService.registered = []

    def tearDown(self):
        self.temp.cleanup()

    def workflow(self):
        return SimulatedService(self.root, self.context_path)

    def review(self, record):
        path = self.output / 'visual-review.json'
        fw.atomic_json(path, dict(presentation_sha256=record['presentation_sha256'],
          preview_sha256=record['preview_sha256'], review_status='passed',
          checks={key: True for key in fw.VISUAL_CHECKS}, blockers=[],
          notes=['Simulated visual approval; unit test only.'], quote='Figure 2. Multi-view geometry.'))
        return path

    def test_alternate_content_counted_once(self):
        report = fw.structure(self.output / 'figure.working.pptx')
        self.assertTrue(report['ok'])
        self.assertEqual((report['editable_objects'], report['native_formula_count']), (2, 2))

    def test_only_public_terminal_retry_starts_a_new_bounded_attempt(self):
        from types import SimpleNamespace
        from backend.storage import prepare_figure_retry
        record=self.workflow().audit(self.manifest)
        original=fw.read(self.output/'figure-workflow-state.json')
        job=dict(id='j_test',task='replicate_paper_figure',status='running',revision=4,context=self.context)
        store=SimpleNamespace(project=self.root)
        prepare_figure_retry(store,job)
        self.assertEqual(fw.read(self.output/'figure-workflow-state.json'),original)
        job['status']='failed';prepare_figure_retry(store,job)
        self.assertEqual(fw.read(self.output/'figure-workflow.previous.json'),original)
        fresh=fw.read(self.output/'figure-workflow-state.json')
        self.assertEqual(fresh['rounds'],[]);self.assertEqual(fresh['retry_from_revision'],4)
        fresh['rounds']=[record];fw.atomic_json(self.output/'figure-workflow-state.json',fresh)
        prepare_figure_retry(store,job)
        self.assertEqual(fw.read(self.output/'figure-workflow-state.json')['rounds'],[record])
        self.assertTrue((self.output/'figure.working.pptx').exists())

    def test_custom_connector_and_invalid_line_order_are_rejected(self):
        path=self.output/'figure.working.pptx'
        with zipfile.ZipFile(path) as package:parts={n:package.read(n) for n in package.namelist()}
        xml=parts['ppt/slides/slide1.xml'].decode()
        xml=xml.replace('<a:ln><a:headEnd','<a:custGeom/><a:ln><a:headEnd').replace('type="none"/></a:ln>','type="none"/><a:round/></a:ln>')
        xml=xml.replace('<p:sp>','<p:cxnSp>').replace('</p:sp>','</p:cxnSp>')
        parts['ppt/slides/slide1.xml']=xml.encode()
        with zipfile.ZipFile(path,'w') as package:
            for name,data in parts.items():package.writestr(name,data)
        issues=self.workflow().audit.__globals__['structure'](path)['issues']
        self.assertIn('custom_geometry_in_connector',issues)
        self.assertIn('line_property_order_invalid',issues)

    def test_real_duplicate_id_is_rejected(self):
        pptx(self.output / 'figure.working.pptx', duplicate=True)
        self.assertIn('duplicate_shape_id', fw.structure(self.output / 'figure.working.pptx')['issues'])

    def test_empty_formula_and_bounds_are_not_waived(self):
        pptx(self.output / 'figure.working.pptx', formula='', outside=True)
        report = fw.structure(self.output / 'figure.working.pptx')
        self.assertIn('empty_formula', report['issues'])
        self.assertIn('object_outside_slide', report['issues'])

    def test_invalid_arrow_is_rejected(self):
        pptx(self.output / 'figure.working.pptx', bad_arrow=True)
        with self.assertRaisesRegex(fw.DomainError, 'office_fragment_invalid'):
            fw.structure(self.output / 'figure.working.pptx')

    def test_unchanged_audit_reuses_native_result_across_process_state(self):
        self.workflow().audit(self.manifest)
        result = self.workflow().audit(self.manifest)
        self.assertTrue(result['reused'])
        self.assertEqual(SimulatedService.calls, 1)
        self.assertEqual(len(fw.read(self.output / 'figure-workflow-state.json')['rounds']), 1)

    def test_finish_preserves_bytes_and_does_not_render_again(self):
        record = self.workflow().audit(self.manifest)
        result = self.workflow().finish(self.review(record))
        self.assertEqual(SimulatedService.calls, 1)
        self.assertFalse(result['repeated_final_render'])
        self.assertEqual(fw.digest(self.output / 'figure.pptx'), record['presentation_sha256'])
        manifest = fw.read(self.output / 'result.json')
        self.assertEqual(manifest['figure_replica']['preview_path'], record['preview_path'])
        for artifact in manifest['artifacts']:
            self.assertEqual(fw.digest(self.root / artifact['path']), artifact['sha256'])
        from backend.document_quality import review, validate
        review(self.root, manifest, manifest['artifacts'])
        self.assertTrue(validate(self.output / 'figure.pptx', 'powerpoint')['passed'])

    def test_third_changed_audit_is_blocked(self):
        self.workflow().audit(self.manifest)
        pptx(self.output / 'figure.working.pptx', formula='y')
        self.workflow().audit(self.manifest)
        pptx(self.output / 'figure.working.pptx', formula='z')
        with self.assertRaisesRegex(fw.DomainError, 'figure_review_limit_reached'):
            self.workflow().audit(self.manifest)
        self.assertEqual(SimulatedService.calls, 2)

    def test_failed_native_is_not_retried_unchanged(self):
        SimulatedService.fail_native = True
        for _ in range(2):
            with self.assertRaisesRegex(fw.DomainError, 'office_native_failed'):
                self.workflow().audit(self.manifest)
        self.assertEqual(SimulatedService.calls, 1)

    def test_modified_ppt_cannot_use_old_visual_review(self):
        record = self.workflow().audit(self.manifest)
        pptx(self.output / 'figure.working.pptx', formula='new')
        with self.assertRaisesRegex(fw.DomainError, 'figure_review_stale'):
            self.workflow().finish(self.review(record))
        self.assertFalse((self.output / 'result.json').exists())

    def test_preview_tamper_invalidates_cache(self):
        record = self.workflow().audit(self.manifest)
        (self.root / record['preview_path']).write_bytes(b'changed')
        with self.assertRaisesRegex(fw.DomainError, 'figure_review_stale'):
            self.workflow().audit(self.manifest)
        self.assertEqual(SimulatedService.calls, 1)

    def test_visual_blockers_cannot_be_published(self):
        record = self.workflow().audit(self.manifest)
        path = self.review(record)
        review = fw.read(path)
        review['blockers'] = ['text_overlap']
        fw.atomic_json(path, review)
        with self.assertRaisesRegex(fw.DomainError, 'figure_visual_blockers_remaining'):
            self.workflow().finish(path)
        self.assertFalse((self.output / 'figure.pptx').exists())

    def test_evidence_exact_unicode_and_cache(self):
        workflow = self.workflow()
        workflow.evidence('Kalman ﬁlter')
        workflow.evidence('Figure 2.\nMulti-view geometry.')
        self.assertEqual(SimulatedService.page_calls, 1)
        with self.assertRaisesRegex(fw.DomainError, 'quote_not_found'):
            workflow.evidence('Kalman filter')

    def test_outside_target_and_cancelled_job_are_rejected(self):
        SimulatedService.job_status = 'interrupted'
        with self.assertRaisesRegex(fw.DomainError, 'figure_job_not_active'):
            self.workflow().audit(self.manifest)
        self.context['figure_selection']['target_pptx'] = 'unrelated.pptx'
        fw.atomic_json(self.context_path, self.context)
        with self.assertRaisesRegex(fw.DomainError, 'path_outside_scope'):
            self.workflow()

    def test_missing_visual_check_is_rejected(self):
        record = self.workflow().audit(self.manifest)
        path = self.review(record)
        review = fw.read(path)
        del review['checks']['colors_and_layers']
        fw.atomic_json(path, review)
        with self.assertRaisesRegex(fw.DomainError, 'figure_visual_review_incomplete'):
            self.workflow().finish(path)

    def test_changed_manifest_requires_new_audit(self):
        first = self.workflow().audit(self.manifest)
        manifest = fw.read(self.manifest)
        manifest['expected_text'] = [{'name': 'shape1', 'text': 'P'}]
        fw.atomic_json(self.manifest, manifest)
        second = self.workflow().audit(self.manifest)
        self.assertNotEqual(first['key'], second['key'])
        self.assertEqual(SimulatedService.calls, 2)

    def test_registered_target_is_preserved(self):
        pptx(self.output / 'figure.pptx', formula='registered')
        before = fw.digest(self.output / 'figure.pptx')
        SimulatedService.registered = [{'path': 'outputs/task/figure.pptx', 'sha256': before}]
        record = self.workflow().audit(self.manifest)
        with self.assertRaisesRegex(fw.DomainError, 'figure_registered_target_changed'):
            self.workflow().finish(self.review(record))
        self.assertEqual(fw.digest(self.output / 'figure.pptx'), before)

    def test_missing_preview_does_not_trigger_unbounded_native_retry(self):
        record = self.workflow().audit(self.manifest)
        (self.root / record['preview_path']).unlink()
        with self.assertRaises(fw.DomainError):
            self.workflow().audit(self.manifest)
        self.assertEqual(SimulatedService.calls, 1)

    def test_wrong_visual_hash_is_rejected(self):
        record = self.workflow().audit(self.manifest)
        path = self.review(record)
        review = fw.read(path)
        review['preview_sha256'] = 'old_review'
        fw.atomic_json(path, review)
        with self.assertRaisesRegex(fw.DomainError, 'figure_review_stale'):
            self.workflow().finish(path)


if __name__ == '__main__':
    unittest.main(verbosity=2)
