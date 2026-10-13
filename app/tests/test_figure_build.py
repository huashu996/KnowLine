"""Exercise actual PPTX construction, scope, source geometry and prompt routing."""
import copy
import ast
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
spec = importlib.util.spec_from_file_location('figure_build', APP / 'scripts/figure_build.py')
fb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fb)
# Prompt generation needs only paths; isolate it from the unrelated PDF/database
# imports so the test uses the production function bodies without loading a store.
prompt_ast = ast.parse((APP / 'backend/codex_runner.py').read_text('utf-8-sig'))
prompt_globals = dict(Path=Path, contained=fb.Workflow.owned.__globals__['contained'],
                      app_dir=lambda project: project / 'app')
exec(compile(ast.Module(body=[n for n in prompt_ast.body if isinstance(n, ast.FunctionDef)
                             and n.name in {'figure_instructions', 'office_instructions', 'instructions'}], type_ignores=[]),
             'codex_runner.py', 'exec'), prompt_globals)
instructions = prompt_globals['instructions']


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root / '.knowledge').mkdir()
        fb.atomic_json(self.root / '.knowledge/config.json', {'port': 21588})
        self.output = self.root / 'outputs/test'
        self.output.mkdir(parents=True)
        fb.Image.new('RGB', (800, 400), 'white').save(self.output / 'source.png')
        self.context = dict(task='replicate_paper_figure', job_id='j_test', output_dir='outputs/test',
          figure_selection=dict(target_pptx='outputs/test/figure.pptx', page_size='wide',
            source_size_pt=[400, 200], formula_mode='office', allow_uniform_scale=False,
            image=dict(path='outputs/test/source.png', sha256=fb.digest(self.output / 'source.png'),
                       width=800, height=400)))
        self.context_path = self.root / 'context.json'
        fb.atomic_json(self.context_path, self.context)
        self.plan = dict(source_image_sha256=self.context['figure_selection']['image']['sha256'],
          defaults=dict(font_size_pt=12, stroke='000000', fill='E8F0FA'), objects=[
            dict(name='flow', kind='connector', start=[220, 100], end=[420, 100],
                 source=dict(name='input', site=3), target=dict(name='output', site=1), end_arrow='triangle'),
            dict(name='input', kind='rect', bbox=[20, 40, 200, 120], text='中文 input'),
            dict(name='output', kind='rounded_rect', bbox=[420, 40, 200, 120], text='Output')],
          axis_constraints=[dict(source='input', target='output', axis='horizontal')])
        self.plan_path = self.output / 'figure-plan.json'

    def tearDown(self):
        self.temp.cleanup()

    def build(self):
        fb.atomic_json(self.plan_path, self.plan)
        return fb.build(fb.Workflow(self.root, self.context_path), self.plan_path)

    def test_native_text_geometry_and_true_connector_bindings(self):
        result = self.build()
        prs = fb.Presentation(self.root / result['working_path'])
        shapes = {s.name: s for s in prs.slides[0].shapes}
        self.assertEqual(shapes['input'].text, '中文 input')
        self.assertAlmostEqual(shapes['input'].left.pt, 290)
        self.assertAlmostEqual(shapes['input'].width.pt, 100)
        flow = shapes['flow']
        self.assertEqual(flow._element.xpath('.//a:stCxn')[0].get('id'), str(shapes['input'].shape_id))
        self.assertEqual(flow._element.xpath('.//a:endCxn')[0].get('id'), str(shapes['output'].shape_id))
        self.assertEqual(flow._element.xpath('.//a:tailEnd')[0].get('type'), 'triangle')
        self.assertEqual(flow.end_x.pt, 490)
        self.assertEqual(prs.slides[0].shapes[0].name, 'flow')
        manifest = fb.read(self.root / result['manifest_path'])
        self.assertEqual(manifest['expected_shape_count'], 3)
        self.assertEqual(manifest['expected_connector_count'], 1)
        self.assertEqual(manifest['expected_text'][0]['text'], '中文 input')
        from figure_workflow import structure
        self.assertTrue(structure(self.root / result['working_path'])['ok'])

    def test_source_bezier_is_one_freeform_not_a_custom_connector(self):
        self.plan['objects'][0]['native_bezier']=[['M',220,100],['C',270,20,370,20,420,100]]
        result=self.build();prs=fb.Presentation(self.root/result['working_path'])
        shape=next(s for s in prs.slides[0].shapes if s.name=='flow')
        self.assertEqual(shape._element.tag,'{http://schemas.openxmlformats.org/presentationml/2006/main}sp')
        self.assertEqual(len(shape._element.xpath('.//a:cubicBezTo')),1)
        self.assertFalse(shape._element.xpath('.//a:stCxn'))
        self.assertEqual(fb.read(self.root/result['manifest_path'])['expected_connector_count'],0)
        from figure_workflow import structure
        self.assertTrue(structure(self.root/result['working_path'])['ok'])

    def test_native_elbow_join_precedes_arrow_properties(self):
        self.plan['objects'][0].update(routing='elbow',end=[420,160],route_points=[[220,100],[300,100],[300,160],[420,160]])
        result=self.build();prs=fb.Presentation(self.root/result['working_path'])
        shape=next(s for s in prs.slides[0].shapes if s.name=='flow')
        tags=[n.tag.rsplit('}',1)[-1] for n in shape._element.spPr.ln]
        self.assertLess(tags.index('round'),tags.index('tailEnd'))
        self.assertEqual(shape._element.spPr.prstGeom.get('prst'),'bentConnector3')

    def test_rotation_adjustments_and_closed_fill_are_built_without_postprocessing(self):
        self.plan['objects'] += [
            dict(name='beam',kind='bezier',commands=[['M',10,200],['C',60,240,100,240,140,200]],closed_fill=True,fill='008899'),
            dict(name='arrow',kind='right_arrow',bbox=[200,240,140,80],rotation=35,adjustments=[.3,.6])]
        result=self.build();shapes={s.name:s for s in fb.Presentation(self.root/result['working_path']).slides[0].shapes}
        self.assertAlmostEqual(shapes['arrow'].rotation,35)
        self.assertEqual(list(shapes['arrow'].adjustments),[.3,.6])
        path=shapes['beam']._element.xpath('.//a:path')[0]
        self.assertEqual(path.get('fill'),'norm')
        self.assertEqual(path[-1].tag.rsplit('}',1)[-1],'close')
        self.assertEqual(str(shapes['beam'].fill.fore_color.rgb),'008899')

    def test_bad_rotation_or_adjustments_cannot_replace_working_file(self):
        result=self.build();path=self.root/result['working_path'];before=fb.digest(path)
        self.plan['objects'][1]['rotation']=float('nan')
        with self.assertRaises(fb.DomainError):self.build()
        self.assertEqual(fb.digest(path),before)
        del self.plan['objects'][1]['rotation']
        self.plan['objects'][1]['adjustments']=[.1,.2,.3,.4]
        with self.assertRaises(fb.DomainError):self.build()
        self.assertEqual(fb.digest(path),before)

    def test_word_screenshot_routes_to_its_own_tools_but_ppt_keeps_fallback(self):
        job=dict(id='j_test',task='copy_office_selection',context_path='context.json',
                 context=dict(output_dir='outputs/test',office_selection=dict(selection_mode='image_region',target='word'),layout_contract={}))
        route=instructions(SimpleNamespace(project=self.root),job,True)
        self.assertIn('office prepare j_test',route)
        self.assertIn('--manifest-only',route)
        self.assertNotIn('knowline-academic-layout/SKILL.md',route)
        self.assertNotIn('result-template.json',route)
        job['context']['office_selection']['target']='powerpoint'
        self.assertIn('result-template.json',instructions(SimpleNamespace(project=self.root),job,True))

    def test_prepare_manifest_and_fixed_source_line_spacing(self):
        result=self.build();manifest=fb.read(self.root/result['preparation_manifest_path'])
        self.assertEqual(manifest['equations'],[])
        self.assertEqual(manifest['text_objects'],[dict(name='input',resize_frame=False),dict(name='output',resize_frame=False)])
        shape=fb.Presentation(self.root/result['working_path']).slides[0].shapes[1]
        self.assertFalse(shape.text_frame.word_wrap)
        self.assertEqual(shape.text_frame.paragraphs[0].line_spacing.pt,12)

    def test_prepare_scope_allows_text_only_working_copy(self):
        from backend.office_native import scope
        result=self.build();job=dict(id='j_test',task='replicate_paper_figure',status='running',context=self.context)
        store=SimpleNamespace(project=self.root,job=lambda jid:job)
        body=dict(operation='prepare',presentation=result['working_path'],manifest=result['preparation_manifest_path'])
        self.assertEqual(scope(store,'j_test',body)[-1],'prepare')
        body['operation']='equations'
        with self.assertRaisesRegex(fb.DomainError,'office_native_manifest_invalid'):scope(store,'j_test',body)

    def test_single_native_polyline_independent_photo_and_formula_plan(self):
        self.plan['objects'] += [
          dict(name='ray', kind='polyline', points=[[10, 190], [100, 230], [200, 170]], fill=None),
          dict(name='scene', kind='image', bbox=[420, 240, 200, 100]),
          dict(name='math', kind='formula', bbox=[30, 270, 200, 60], native_linear='x^2', fill=None, stroke=None)]
        result = self.build()
        manifest = fb.read(self.root / result['manifest_path'])
        self.assertEqual(manifest['expected_shape_count'], 6)
        self.assertEqual(manifest['expected_image_count'], 1)
        self.assertEqual(manifest['formula_objects'], [dict(name='math', kind='office')])
        equations = fb.read(self.root / result['equation_manifest_path'])['equations']
        self.assertEqual(equations[0]['native_linear'], 'x^2')
        self.assertEqual(equations[0]['font_size'], 12)
        prs = fb.Presentation(self.root / result['working_path'])
        shape = next(s for s in prs.slides[0].shapes if s.name == 'ray')
        self.assertEqual(len(shape._element.xpath('.//a:custGeom')), 1)

    def test_invalid_input_preserves_existing_working_ppt(self):
        result = self.build()
        before = fb.digest(self.root / result['working_path'])
        self.plan['objects'].append(dict(name='backdrop', kind='image', bbox=[0, 0, 800, 400]))
        with self.assertRaisesRegex(fb.DomainError, 'figure_full_source_image_forbidden'):
            self.build()
        self.assertEqual(fb.digest(self.root / result['working_path']), before)

    def test_uniform_scaling_applies_to_geometry_and_font_together(self):
        self.context['figure_selection']['allow_uniform_scale'] = True
        fb.atomic_json(self.context_path, self.context)
        result = self.build()
        shape = next(s for s in fb.Presentation(self.root / result['working_path']).slides[0].shapes if s.name == 'input')
        self.assertAlmostEqual(shape.width.pt, 228, places=3)
        self.assertAlmostEqual(shape.text_frame.paragraphs[0].font.size.pt, 27.36, places=2)

    def test_plan_cannot_change_source_or_target_scope(self):
        self.plan['source_image_sha256'] = 'wrong'
        with self.assertRaisesRegex(fb.DomainError, 'artifact_hash_mismatch'):
            self.build()
        self.context['figure_selection']['target_pptx'] = 'unrelated.pptx'
        fb.atomic_json(self.context_path, self.context)
        with self.assertRaisesRegex(fb.DomainError, 'path_outside_scope'):
            self.build()

    def test_duplicate_objects_and_unknown_endpoints_are_not_published(self):
        self.plan['objects'][0]['source']['name'] = 'missing'
        with self.assertRaisesRegex(fb.DomainError, 'figure_plan_connector_target_missing'):
            self.build()
        self.assertFalse((self.output / 'figure.working.pptx').exists())
        self.plan['objects'][0]['source']['name'] = 'input'
        self.plan['objects'].append(copy.deepcopy(self.plan['objects'][1]))
        with self.assertRaisesRegex(fb.DomainError, 'figure_plan_object_name_invalid'):
            self.build()

    def test_does_not_reset_review_or_overwrite_published_result(self):
        workflow = fb.Workflow(self.root, self.context_path)
        workflow.state['rounds'] = [dict(round=1), dict(round=2)]
        fb.atomic_json(workflow.state_path, workflow.state)
        with self.assertRaisesRegex(fb.DomainError, 'figure_review_limit_reached'):
            self.build()
        self.assertEqual(len(fb.read(workflow.state_path)['rounds']), 2)
        fb.atomic_json(self.output / 'result.json', {'already': 'published'})
        with self.assertRaisesRegex(fb.DomainError, 'figure_result_already_published'):
            self.build()

    def test_small_source_font_and_mathtype_selection_are_preserved(self):
        self.plan['defaults']['font_size_pt'] = 8.4
        result = self.build()
        shape = next(s for s in fb.Presentation(self.root / result['working_path']).slides[0].shapes if s.name == 'input')
        self.assertEqual(shape.text_frame.paragraphs[0].font.size.pt, 8.4)
        self.context['figure_selection']['formula_mode'] = 'mathtype'
        fb.atomic_json(self.context_path, self.context)
        self.plan['objects'].append(dict(name='math', kind='formula', bbox=[20, 220, 200, 60], native_linear='x'))
        with self.assertRaisesRegex(fb.DomainError, 'figure_plan_requires_special_formula_pipeline'):
            self.build()

    def test_figure_prompt_has_only_its_own_route_and_correct_handoff(self):
        store = SimpleNamespace(project=self.root)
        job = dict(id='j_test', task='replicate_paper_figure', context_path='context.json', context=self.context)
        automatic = instructions(store, job, automatic=True)
        self.assertIn('figure_build.py', automatic)
        self.assertIn('figure_workflow.py audit/finish', automatic)
        for other_route in ['research_finalize.py', 'knowline-academic-layout/SKILL.md', 'result-template.json', 'jobs claim j_test']:
            self.assertNotIn(other_route, automatic)
        manual = instructions(store, job, automatic=False)
        self.assertIn('jobs claim j_test', manual)
        self.assertIn('jobs ingest j_test', manual)
        job['task'] = 'proposal_word'
        job['context']['layout_contract'] = {'basis': 'paper-agent'}
        self.assertIn('knowline-academic-layout/SKILL.md', instructions(store, job, automatic=True))


if __name__ == '__main__':
    unittest.main(verbosity=2)
