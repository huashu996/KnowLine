"""Authenticated manual repair never takes an automatically leased task."""
import sys
import ast
import secrets
from pathlib import Path
from types import SimpleNamespace
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.safety import DomainError
source=Path(__file__).resolve().parents[1]/'backend/agent_bridge.py'
tree=ast.parse(source.read_text('utf-8'))
namespace=dict(DomainError=DomainError,secrets=secrets)
exec(compile(ast.Module(body=[node for node in tree.body if isinstance(node,ast.ClassDef)],type_ignores=[]),str(source),'exec'),namespace)
AgentBridge=namespace['AgentBridge']


class Recovery(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.job=dict(id='j_test',task='replicate_paper_figure',status='failed',revision=4)
        self.manual=False
        async def claim(id,body):
            self.manual=True
            return dict(self.job,status='running',revision=5)
        self.bridge=object.__new__(AgentBridge)
        self.bridge.key='local-test-key'
        self.bridge.selected={'id':'agent_test'}
        self.bridge.routes={}
        self.bridge.store=SimpleNamespace(job=lambda id:self.job)
        self.bridge.compatibility=SimpleNamespace(claim=claim,describe=lambda id:dict(mode='manual') if self.manual else None)
        self.request=SimpleNamespace(headers={'x-kw-agent-key':self.bridge.key})

    async def test_authenticated_terminal_recovery_and_ingest(self):
        body=dict(manual_recovery=True,base_revision=4)
        result=await self.bridge.claim('j_test',body,self.request)
        self.assertEqual(result['status'],'running')
        self.bridge.guard('j_test',body,self.request)
        await self.bridge.accepted('j_test')

    async def test_default_manual_claim_still_blocked(self):
        with self.assertRaisesRegex(DomainError,'agent_worker_required'):
            await self.bridge.claim('j_test',{},self.request)
        self.assertFalse(self.manual)

    async def test_missing_local_credential_rejected(self):
        bad=SimpleNamespace(headers={})
        with self.assertRaisesRegex(DomainError,'agent_local_credential_required'):
            await self.bridge.claim('j_test',dict(manual_recovery=True),bad)
        self.assertFalse(self.manual)

    async def test_running_or_other_task_cannot_be_taken(self):
        for patch in [dict(status='running'),dict(task='read_resources')]:
            original=dict(self.job);self.job.update(patch)
            with self.assertRaisesRegex(DomainError,'agent_lease_invalid'):
                await self.bridge.claim('j_test',dict(manual_recovery=True),self.request)
            self.job.clear();self.job.update(original)
        self.assertFalse(self.manual)

    async def test_automatic_lease_cannot_be_bypassed(self):
        self.bridge.routes['j_test']=dict(agent_id='agent_test',lease='lease_test')
        with self.assertRaisesRegex(DomainError,'agent_lease_invalid'):
            await self.bridge.claim('j_test',dict(manual_recovery=True),self.request)
        self.manual=True
        self.bridge.check_agent=lambda body:None
        with self.assertRaisesRegex(DomainError,'agent_lease_invalid'):
            self.bridge.guard('j_test',dict(manual_recovery=True),self.request)


if __name__=='__main__':unittest.main()
