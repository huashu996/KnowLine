"""Exercise real deletion endpoints and file cleanup in isolated temporary projects."""
import asyncio
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch, AsyncMock

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP/'scripts'))
from patch_frozen_modules import module_code
EXE=None
if '--exe' in sys.argv:
    index=sys.argv.index('--exe');EXE=Path(sys.argv[index+1]);del sys.argv[index:index+2]
PACKAGE='_job_delete_tests'
package=types.ModuleType(PACKAGE);package.__path__=[str(APP/'backend')];sys.modules[PACKAGE]=package
def code(name):
    return module_code(EXE,'backend.'+name) if EXE else compile((APP/'backend'/f'{name}.py').read_bytes(),name,'exec')
def load(name):
    module=types.ModuleType(PACKAGE+'.'+name);module.__package__=PACKAGE
    sys.modules[module.__name__]=module;exec(code(name),module.__dict__);return module
safety=load('safety');load('layout');load('output_names');paper_storage=load('paper_storage')
ownership=load('storage_ownership');cleanup=load('storage_delete')
clipboard=types.ModuleType(PACKAGE+'.office_clipboard');clipboard.release_owned_sources=lambda roots:None
sys.modules[clipboard.__name__]=clipboard
create=next(v for v in code('app').co_consts if isinstance(v,types.CodeType) and v.co_name=='create_app')


class Store:
    def __init__(self,root):
        self.project=root;self.root=root/'resource';self.state=self.root/'.knowledge'
        self.state.mkdir(parents=True);(root/'outputs').mkdir()
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.executescript('CREATE TABLE jobs(id TEXT PRIMARY KEY,data TEXT);CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE versions(id TEXT,snapshot_path TEXT);')
        self.sources=[];self.events=[]
    def rows(self,sql,params=()):return [dict(r) for r in self.db.execute(sql,params)]
    def one(self,sql,params=()):return next(iter(self.rows(sql,params)),None)
    def resources(self):return self.sources
    def job(self,id):
        row=self.one('SELECT data FROM jobs WHERE id=?',(id,))
        if not row:raise safety.DomainError('job_not_found',404)
        return json.loads(row['data'])
    def check(self,job,body):
        if job['revision']!=body.get('base_revision'):raise safety.DomainError('revision_conflict',409)
    def event(self,*args):self.events.append(args)
    def file(self,name,data=b'generated'):
        p=self.project/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);return p
    def add(self,id,status='partial'):
        directory='outputs/'+id
        self.file(directory+'/final.docx');self.file(directory+'/previews/page.png')
        self.file(directory+'/unregistered-intermediate.json')
        self.file('resource/.knowledge/jobs/'+id+'/context.json')
        self.file('resource/.knowledge/jobs/'+id+'/agent-execution.json')
        job={'id':id,'revision':2,'status':status,'context':{'job_id':id,'scope':{},'output_dir':directory},'result':{'artifacts':[{'path':directory+'/final.docx'}]}}
        self.save(job);return job
    def save(self,job):
        self.db.execute('INSERT OR REPLACE INTO jobs VALUES(?,?)',(job['id'],json.dumps(job)));self.db.commit()


class DeletionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name));self.addCleanup(self.store.db.close)
        self.calls=[]
        async def cancel(id,wait=False):self.calls.append((id,wait))
        self.codex=types.SimpleNamespace(cancel=cancel)
    def endpoint(self,name):
        endpoint=next(v for v in create.co_consts if isinstance(v,types.CodeType) and v.co_name==name)
        async def write(kind,body,action):
            try:result=action();self.store.db.commit()
            except Exception:self.store.db.rollback();raise
            result['storage_cleanup']=cleanup.drain(self.store);return result
        values={'store':self.store,'codex':self.codex,'write':write,'project':self.store.project}
        return types.FunctionType(endpoint,{'__package__':PACKAGE,'DomainError':safety.DomainError,'contained':safety.contained,'asyncio':asyncio},closure=tuple(types.CellType(values[v]) for v in endpoint.co_freevars))
    async def delete(self,id):return await self.endpoint('delete_job')(id,{'base_revision':2})
    async def test_single_deletes_registered_intermediate_preview_state_and_empty_dirs(self):
        self.store.add('j_a');self.store.add('j_b')
        source=self.store.file('resource/source.pdf',b'original');snapshot=self.store.file('resource/.knowledge/versions/v.pdf',b'original')
        self.store.sources=[{'id':'r_source','path':'resource/source.pdf','versions':[{'snapshot_path':'resource/.knowledge/versions/v.pdf'}]}]
        result=await self.delete('j_a')
        self.assertEqual(result['storage_cleanup']['state'],'complete')
        self.assertFalse((self.store.project/'outputs/j_a').exists());self.assertFalse((self.store.state/'jobs/j_a').exists())
        self.assertTrue((self.store.project/'outputs/j_b/final.docx').exists());self.assertEqual(source.read_bytes(),b'original');self.assertTrue(snapshot.exists())
        self.assertEqual(self.calls,[('j_a',True)])
    async def test_bulk_deletes_cross_references_only_when_both_tasks_selected(self):
        a=self.store.add('j_a');b=self.store.add('j_b');b['context']['previous']={'path':'outputs/j_a/final.docx'};self.store.save(b)
        result=await self.endpoint('delete_jobs')({'jobs':[{'id':'j_a','base_revision':2},{'id':'j_b','base_revision':2}]})
        self.assertEqual(result['deleted'],['j_a','j_b']);self.assertEqual(list((self.store.project/'outputs').iterdir()),[])
    async def test_other_task_reference_does_not_preserve_deleted_task_outputs(self):
        self.store.add('j_a');b=self.store.add('j_b');b['context']['previous']={'path':'outputs/j_a/final.docx'};self.store.save(b)
        result=await self.delete('j_a');self.assertEqual(result['storage_cleanup']['state'],'complete')
        self.assertFalse((self.store.project/'outputs/j_a').exists());self.assertTrue(self.store.job('j_b'))
        await self.delete('j_b');self.assertEqual(list((self.store.project/'outputs').iterdir()),[])
    async def test_only_registered_resource_survives_even_if_knowledge_references_artifact(self):
        self.store.add('j_a');original=self.store.file('outputs/j_a/imported.pdf',b'original')
        self.store.sources=[{'id':'r_imported','path':'outputs/j_a/imported.pdf','versions':[]}]
        self.store.db.execute('INSERT INTO settings VALUES(?,?)',('kb_cards:kb1',json.dumps({'job_id':'j_a','document':{'path':'outputs/j_a/final.docx'}})))
        result=await self.delete('j_a');self.assertEqual(result['storage_cleanup']['state'],'shared_references_retained')
        self.assertEqual(original.read_bytes(),b'original');self.assertFalse((self.store.project/'outputs/j_a/final.docx').exists())
        self.store.sources=[]
        self.assertEqual(cleanup.drain(self.store)['state'],'complete');self.assertFalse((self.store.project/'outputs/j_a').exists())
    async def test_locked_file_is_queued_and_retry_removes_it(self):
        self.store.add('j_a');real=paper_storage.unlink_file
        def locked(store,path):
            if path.name=='final.docx':raise PermissionError('in use')
            return real(store,path)
        with patch.object(paper_storage,'unlink_file',locked):result=await self.delete('j_a')
        self.assertEqual(result['storage_cleanup']['state'],'pending');self.assertTrue(self.store.rows('SELECT * FROM settings'))
        result=cleanup.drain(self.store);self.assertEqual(result['state'],'complete');self.assertFalse((self.store.project/'outputs/j_a').exists());self.assertFalse(self.store.rows('SELECT * FROM settings'))
    async def test_stale_revision_and_cancel_failure_do_not_remove_files_or_records(self):
        self.store.add('j_a','running')
        with self.assertRaises(safety.DomainError):await self.endpoint('delete_job')('j_a',{'base_revision':1})
        self.assertFalse(self.calls)
        self.codex.cancel=AsyncMock(side_effect=safety.DomainError('task_cancel_failed'))
        with self.assertRaises(safety.DomainError):await self.delete('j_a')
        self.assertTrue(self.store.job('j_a'));self.assertTrue((self.store.project/'outputs/j_a/final.docx').exists())
    async def test_legacy_alias_resolves_to_readable_directory(self):
        job=self.store.add('j_a');self.store.file('app/project-layout.json',json.dumps({'path_mapping':{'resource/outputs':'outputs','.knowledge':'resource/.knowledge'}}).encode())
        self.store.file('resource/.knowledge/output-directories.json',json.dumps({'schema_version':1,'jobs':{'j_a':{'directory':'Readable task'}}}).encode())
        (self.store.project/'outputs/j_a').rename(self.store.project/'outputs/Readable task')
        job['context']['output_dir']='resource/outputs/j_a';self.store.save(job)
        await self.delete('j_a');self.assertFalse((self.store.project/'outputs/Readable task').exists())
    async def test_output_root_or_outside_path_rejected_without_deletion(self):
        job=self.store.add('j_a')
        for path in ('outputs','resource','../outside'):
            job['context']['output_dir']=path;self.store.save(job)
            with self.assertRaises(safety.DomainError):await self.delete('j_a')
            self.assertTrue(self.store.job('j_a'));self.assertTrue((self.store.project/'outputs/j_a/final.docx').exists())
    async def test_cleanup_rechecks_new_references_and_never_removes_unplanned_files(self):
        self.store.add('j_a');plan=ownership.plan(self.store,'job',['j_a'])
        self.store.db.execute('DELETE FROM jobs');cleanup.enqueue(self.store,plan)
        new=self.store.file('outputs/j_a/new-unplanned.txt')
        self.store.sources=[{'id':'r_final','path':'outputs/j_a/final.docx','versions':[]}]
        report=cleanup.drain(self.store);self.assertTrue(new.exists());self.assertTrue((self.store.project/'outputs/j_a/final.docx').exists())
    async def test_invalid_bulk_request_is_atomic(self):
        self.store.add('j_a');self.store.add('j_b')
        for entries in ([{'id':'j_a','base_revision':2}]*2,[{'id':'j_a','base_revision':2},{'id':'j_b','base_revision':1}]):
            with self.assertRaises(safety.DomainError):await self.endpoint('delete_jobs')({'jobs':entries})
        self.assertFalse(self.calls);self.assertTrue(self.store.job('j_a'));self.assertTrue((self.store.project/'outputs/j_b/final.docx').exists())


class CancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_deletion_waits_for_authenticated_worker_exit_ack(self):
        cls=next(v for v in code('agent_bridge').co_consts if isinstance(v,types.CodeType) and v.co_name=='AgentBridge')
        globals={'asyncio':asyncio,'time':time,'DomainError':safety.DomainError}
        methods={v.co_name:types.FunctionType(v,globals) for v in cls.co_consts if isinstance(v,types.CodeType) and v.co_name in {'cancel','heartbeat'}}
        bridge=types.SimpleNamespace(recovery=set(),routes={'j_a':{'agent_id':'agent1','lease':'lease1'}},stopping={},selected={'id':'agent1','verified':True,'heartbeat':time.monotonic()},transition=AsyncMock(),info=lambda *a:None,compatibility=types.SimpleNamespace(cancel=AsyncMock()),status=lambda:{'available':True})
        task=asyncio.create_task(methods['cancel'](bridge,'j_a',wait=True));await asyncio.sleep(0)
        self.assertFalse(task.done());self.assertNotIn('j_a',bridge.routes)
        with self.assertRaises(safety.DomainError):await methods['heartbeat'](bridge,{'agent_id':'wrong','finished_lease':'lease1'})
        await methods['heartbeat'](bridge,{'agent_id':'agent1','finished_lease':'wrong'});self.assertFalse(task.done())
        await methods['heartbeat'](bridge,{'agent_id':'agent1','finished_lease':'lease1'});await task
        self.assertFalse(bridge.stopping)


if __name__=='__main__':unittest.main()
