"""Connection regressions in temporary state; no model calls or research jobs."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import Mock, patch

APP=Path(__file__).resolve().parents[1]
EXE=None
if '--exe' in sys.argv:
    i=sys.argv.index('--exe');EXE=Path(sys.argv[i+1]);del sys.argv[i:i+2]
sys.path.insert(0,str(APP/'scripts'))
from patch_frozen_modules import module_code
PACKAGE='_connection_checks'
package=types.ModuleType(PACKAGE);package.__path__=[str(APP/'backend')];sys.modules[PACKAGE]=package
store=types.ModuleType(PACKAGE+'.store');store.uid=lambda prefix:prefix+'_new';store.now=lambda:'now';sys.modules[store.__name__]=store
policy=types.ModuleType(PACKAGE+'.research_policy');policy.total_budget=lambda job:None;sys.modules[policy.__name__]=policy
runner=types.ModuleType(PACKAGE+'.codex_runner');runner.instructions=lambda *a:None;runner.executable=lambda:None;sys.modules[runner.__name__]=runner

def load(name):
    module=types.ModuleType(PACKAGE+'.'+name);module.__package__=PACKAGE;sys.modules[module.__name__]=module
    code=module_code(EXE,'backend.'+name) if EXE else compile((APP/'backend'/f'{name}.py').read_bytes(),name,'exec')
    exec(code,module.__dict__)
    return module

safety=load('safety');layout=load('layout');connection=load('agent_connection');worker=load('agent_worker');bridge_module=load('agent_bridge')
DomainError=safety.DomainError

class Response:
    def __init__(self,value):self.value=value
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self):return json.dumps(self.value).encode()

class Checks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.project=Path(self.temp.name);self.folder=self.project/'.knowledge/agent-worker';self.folder.mkdir(parents=True)
        self.config={'builtin':'codex','argv':[sys.executable,'exec','--approve-for-me','-C','{project}','-'],'generation':'binding_old'}
        self.binding=self.folder/'adapter.json';self.binding.write_text(json.dumps(self.config))

    def test_conflicting_flags_fail_before_client_launch(self):
        config={**self.config,'argv':self.config['argv']+['--sandbox','workspace-write']}
        with patch.object(connection.subprocess,'run') as run:
            with self.assertRaisesRegex(DomainError,'agent_command_conflict'):connection.prepare_adapter(config,self.project,True)
            run.assert_not_called()

    def test_stale_explicit_client_is_rediscovered_without_changing_permissions(self):
        config={**self.config,'argv':['C:/old-user/removed/codex.exe',*self.config['argv'][1:]]}
        with patch.object(runner,'executable',return_value=sys.executable):
            fixed=connection.prepare_adapter(config,self.project)
        self.assertEqual(fixed['argv'],[sys.executable,*config['argv'][1:]])

    def test_generic_adapter_never_falls_back_to_codex(self):
        with patch.object(runner,'executable') as find:
            with self.assertRaisesRegex(DomainError,'agent_command_missing'):
                connection.prepare_adapter({'argv':['missing-external-client-xyz']},self.project)
            find.assert_not_called()

    def test_project_relative_executable_placeholder(self):
        candidate=self.project/Path(sys.executable).name
        candidate.write_bytes(b'placeholder')
        result=connection.prepare_adapter({'argv':['{project}/'+candidate.name]},self.project)
        self.assertEqual(Path(result['argv'][0]),candidate)

    def test_invalid_json_and_non_object_are_actionable(self):
        for content in ('{broken','[]','{"argv": [1]}'):
            self.binding.write_text(content)
            with self.assertRaisesRegex(DomainError,'agent_command_invalid'):connection.read_adapter(self.binding)

    def test_login_failure_is_not_a_probe_timeout(self):
        help_result=types.SimpleNamespace(returncode=0,stdout='--approve-for-me',stderr='')
        login_result=types.SimpleNamespace(returncode=1,stdout='',stderr='Not logged in')
        with patch.object(connection.subprocess,'run',side_effect=[help_result,login_result]):
            with self.assertRaisesRegex(DomainError,'agent_login_required'):connection.prepare_adapter(self.config,self.project,True)

    def test_unsupported_client_version_fails_before_login(self):
        with patch.object(connection.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout='--sandbox',stderr='')) as run:
            with self.assertRaisesRegex(DomainError,'agent_client_unsupported'):connection.prepare_adapter(self.config,self.project,True)
            self.assertEqual(run.call_count,1)

    def test_connection_lock_does_not_allow_competing_writers(self):
        with connection.connect_lock(self.folder):
            with self.assertRaisesRegex(DomainError,'agent_connection_in_progress'):
                with connection.connect_lock(self.folder):pass
        with connection.connect_lock(self.folder):pass

    def run_connector(self,status,command_file=None):
        calls=[]
        def open_request(req,timeout=None):
            route=req.full_url.split('/api/v1',1)[1];calls.append((route,timeout))
            if route=='/health':return Response({'project_id':'test_project'})
            if route=='/session':return Response({'token':'not-a-real-token'})
            if route=='/agent/status':return Response(status)
            raise AssertionError('Unexpected mutation '+route)
        args=types.SimpleNamespace(action='connect',project=str(self.project),port=12345,builtin=None,command_file=command_file)
        with patch.object(worker,'identity',return_value='test_project'),patch.object(worker,'data_path',side_effect=lambda p,n:Path(p)/n),patch.object(worker.urllib.request,'build_opener',return_value=types.SimpleNamespace(open=open_request)):
            result=worker.run(args)
        return result,calls

    def test_live_reconnect_is_idempotent_and_does_not_launch_a_probe(self):
        status={'available':True,'state':'connected','binding_id':'binding_old','session_id':'session_old'}
        for config_path in (None,str(self.binding)):
            result,calls=self.run_connector(status,config_path)
            self.assertTrue(result['reused']);self.assertEqual(result['session_id'],'session_old')
            self.assertEqual([r for r,t in calls],['/health','/session','/agent/status'])
        self.assertEqual(connection.read_adapter(self.binding)['generation'],'binding_old')

    def test_invalid_new_adapter_preserves_existing_binding(self):
        candidate=self.project/'bad.json';candidate.write_text(json.dumps({**self.config,'argv':self.config['argv']+['--sandbox','workspace-write']}))
        with self.assertRaisesRegex(DomainError,'agent_command_conflict'):
            self.run_connector({'available':True,'state':'connected'},str(candidate))
        self.assertEqual(connection.read_adapter(self.binding)['generation'],'binding_old')

    def test_only_ingest_is_unbounded(self):
        self.assertIsNone(worker.request_timeout('/jobs/j_test/ingest'))
        for route in ('/health','/session','/agent/status','/agent/next','/agent/heartbeat'):
            self.assertLessEqual(worker.request_timeout(route),5)
        self.assertEqual(connection.CONNECT_SECONDS,180)

    def make_bridge(self):
        bridge=object.__new__(bridge_module.AgentBridge)
        bridge.binding=self.binding;bridge.last_launch=0;bridge.worker=None;bridge.worker_generation=None
        bridge.connection_error=None;bridge.blocked_generation=None;bridge.selected=None
        bridge.store=types.SimpleNamespace(project=self.project,config={'port':12345})
        return bridge

    def test_corrupt_binding_does_not_kill_restore(self):
        bridge=self.make_bridge();self.binding.write_text('{broken')
        bridge.restore()
        self.assertEqual(bridge.status()['error_code'],'agent_command_invalid')
        self.binding.write_text(json.dumps(self.config));bridge.last_launch=0
        process=types.SimpleNamespace(pid=12,poll=lambda:None)
        with patch.object(worker,'launch',return_value=process):bridge.restore()
        self.assertIs(bridge.worker,process)

    def test_hidden_worker_exit_reports_real_failure_and_stops_login_retry(self):
        bridge=self.make_bridge();bridge.worker=types.SimpleNamespace(pid=42,poll=lambda:1);bridge.worker_generation='binding_old'
        (self.folder/'startup.json').write_text(json.dumps({'pid':42,'generation':'binding_old','state':'failed','code':'agent_login_required'}))
        status=bridge.status();self.assertEqual(status['connection_phase'],'failed');self.assertEqual(status['error_code'],'agent_login_required')
        self.assertNotIn('argv',json.dumps(status))
        with patch.object(worker,'launch') as launch:
            bridge.restore();launch.assert_not_called()

    def test_stale_worker_error_cannot_poison_new_generation(self):
        bridge=self.make_bridge();bridge.worker=types.SimpleNamespace(pid=42,poll=lambda:1);bridge.worker_generation='binding_old'
        (self.folder/'startup.json').write_text(json.dumps({'pid':1,'generation':'binding_older','state':'failed','code':'agent_login_required'}))
        self.assertEqual(bridge.startup_error('binding_old'),'agent_worker_start_failed')
        self.assertIsNone(bridge.startup_error('binding_new'))

if __name__=='__main__':unittest.main()
