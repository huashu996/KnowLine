"""Retired proposals must be rejected before sources, writers or workers run."""
import ast
import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace, ModuleType

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
# These guards never enumerate YAML skills; packaged YAML is outside this runtime.
if importlib.util.find_spec('yaml') is None:
    sys.modules.setdefault('yaml', ModuleType('yaml'))
from backend.skills import require_task_skill
from backend.safety import DomainError


def method(file, name):
    tree = ast.parse((APP / 'backend' / file).read_text('utf-8'))
    node = next(n for cls in tree.body if isinstance(cls, ast.ClassDef)
                for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    namespace = {'__name__': 'backend.' + Path(file).stem, '__package__': 'backend'}
    exec(compile(ast.Module(body=[node], type_ignores=[]), file, 'exec'), namespace)
    return namespace[name]


class WordOnlyTests(unittest.TestCase):
    def assert_retired(self, action):
        with self.assertRaises(DomainError) as caught:
            action()
        self.assertEqual(caught.exception.code, 'task_retired')
        self.assertEqual(caught.exception.status, 409)

    def test_current_tasks_remain_available(self):
        for task in ('proposal_word', 'replicate_paper_figure', 'copy_office_selection'):
            require_task_skill(APP.parent, task)

    def test_create_rejects_before_reading_idea_or_creating_outputs(self):
        store = SimpleNamespace(project=APP.parent)
        self.assert_retired(lambda: method('store.py', 'create_job')(store, {'task': 'proposal_ppt'}))

    def test_agent_rejects_old_ppt_before_queueing_even_when_disconnected(self):
        store = SimpleNamespace(project=APP.parent, job=lambda _: {'task': 'proposal_ppt'})
        bridge = SimpleNamespace(store=store)
        self.assert_retired(lambda: asyncio.run(method('agent_bridge.py', 'start')(bridge, 'old', {})))

    def test_legacy_start_and_claim_reject_old_tasks(self):
        async def write(_, body, action): return action()
        store = SimpleNamespace(project=APP.parent, job=lambda _: {'task': 'proposal_ppt'})
        runner = SimpleNamespace(store=store, write=write)
        for name in ('start', 'claim'):
            with self.subTest(name=name):
                self.assert_retired(lambda: asyncio.run(method('codex_runner.py', name)(runner, 'old', {})))

    def test_agent_capabilities_keep_word_and_figures(self):
        tree = ast.parse((APP / 'backend/agent_bridge.py').read_text('utf-8'))
        tasks = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == 'TASKS' for t in n.targets))
        self.assertNotIn('proposal_ppt', tasks)
        self.assertIn('proposal_word', tasks)
        self.assertIn('replicate_paper_figure', tasks)


if __name__ == '__main__': unittest.main()
