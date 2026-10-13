import json,sqlite3,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP/'scripts'))
from patch_frozen_modules import module_code
EXE=None
if '--exe' in sys.argv:
 i=sys.argv.index('--exe');EXE=Path(sys.argv[i+1]);del sys.argv[i:i+2]
PACKAGE='_reset_tests'
pkg=types.ModuleType(PACKAGE);pkg.__path__=[str(APP/'backend')];sys.modules[PACKAGE]=pkg
stub=types.ModuleType(PACKAGE+'.store');stub.now=lambda:'test';sys.modules[stub.__name__]=stub

def load(name):
 mod=types.ModuleType(PACKAGE+'.'+name);mod.__package__=PACKAGE;sys.modules[mod.__name__]=mod
 exec(module_code(EXE,'backend.'+name) if EXE else compile((APP/'backend'/f'{name}.py').read_bytes(),name,'exec'),mod.__dict__)
 return mod
safety=load('safety');load('layout');load('output_names');paper_storage=load('paper_storage');load('storage_ownership');deletion=load('storage_delete');management=load('management')

class ResetTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  root=Path(self.temp.name);self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close);self.db.row_factory=sqlite3.Row
  self.db.executescript((APP/'backend/schema.sql').read_text());self.db.execute('CREATE TABLE paper_records(id TEXT)')
  self.s=types.SimpleNamespace(project=root,root=root/'resource/incoming',state=root/'resource/.knowledge',db=self.db,zip_cache={})
  self.s.rows=lambda q,args=():[dict(x) for x in self.db.execute(q,args)]
  self.s.one=lambda q,args=():next(iter(self.s.rows(q,args)),None)
  self.s.resources=lambda:self.s.rows("SELECT * FROM resources WHERE state<>'deleted'")
  self.s.event=lambda kind,id,revision:self.db.execute('INSERT INTO events(kind,entity_id,revision) VALUES(?,?,?)',(kind,id,revision))
  self.file('resource/.knowledge/config.json');self.file('resource/.knowledge/agent-worker/adapter.json');self.file('app/keep.txt')
  self.body={'confirm':'clear_deleted_content','operation_id':'op_test'}
 def file(self,rel):
  p=self.s.project/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'keep-or-delete');return p
 def reset(self):return management.clear_deleted_content(self.s,self.body)
 def test_full_cleanup_preserves_program_connection_and_preferences(self):
  deleted=[self.file(p) for p in ['resource/incoming/folder/a.pdf','resource/.knowledge/versions/blobs/a.pdf','resource/.knowledge/knowledge-index/kb_a/index.sqlite','resource/.knowledge/knowledge-source-cache/a.json','resource/.knowledge/knowledge-vector-cache.sqlite','resource/workspace/knowledge/kb_a.json','outputs/task/result.docx']]
  # No alias layout in this temporary legacy project.
  deleted.append(self.file('workspace/knowledge/kb_a.json'))
  self.db.execute("INSERT INTO resources(id,type,title,state) VALUES('r_a','paper','old','deleted')")
  self.db.execute("INSERT INTO versions(id,resource_id,snapshot_path) VALUES('v_a','r_a','resource/.knowledge/versions/blobs/a.pdf')")
  self.db.execute("INSERT INTO chunks(id,resource_id,text) VALUES('c_a','r_a','old evidence')")
  self.db.execute("INSERT INTO paper_records VALUES('p_a')")
  for k in ['kb_cards:kb_a','kb_cards_history:kb_a:b_old','pdf_annotations_synced:r_a','ui_preference']:
   self.db.execute('INSERT INTO settings VALUES(?,?)',(k,'{}'))
  result=self.reset();self.assertEqual(result['state'],'cleared');self.db.commit()
  report=deletion.drain(self.s);self.assertEqual(report['state'],'complete')
  for p in deleted:
   if p.as_posix().endswith('resource/workspace/knowledge/kb_a.json'):continue
   self.assertFalse(p.exists(),str(p))
  for table in ['resources','versions','chunks','paper_records']:self.assertEqual(self.db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
  for p in ['app/keep.txt','resource/.knowledge/config.json','resource/.knowledge/agent-worker/adapter.json']:self.assertTrue((self.s.project/p).exists())
  self.assertIsNotNone(self.s.one("SELECT * FROM settings WHERE key='ui_preference'"))
  self.assertFalse(self.s.rows("SELECT * FROM settings WHERE key LIKE 'kb_%'"))
 def test_nonempty_workspace_refused_before_mutation(self):
  p=self.file('outputs/a.docx');self.db.execute("INSERT INTO jobs(id,status) VALUES('j_a','completed')")
  with self.assertRaises(safety.DomainError):self.reset()
  self.assertTrue(p.exists());self.assertEqual(self.db.execute('SELECT count(*) FROM jobs').fetchone()[0],1)
 def test_live_resource_refused(self):
  self.db.execute("INSERT INTO resources(id,type,title) VALUES('r_a','paper','live')")
  with self.assertRaises(safety.DomainError):self.reset()
 def test_confirmation_required(self):
  self.body.pop('confirm')
  with self.assertRaises(safety.DomainError):self.reset()
 def test_unsafe_root_refused_before_records_changed(self):
  self.s.root=self.s.project.parent
  self.db.execute("INSERT INTO paper_records VALUES('p_a')")
  with self.assertRaises(safety.DomainError):self.reset()
  self.assertEqual(self.db.execute('SELECT count(*) FROM paper_records').fetchone()[0],1)
 def test_locked_output_stays_retryable(self):
  p=self.file('outputs/task/a.docx');self.reset();self.db.commit()
  with patch.object(paper_storage,'unlink_file',side_effect=PermissionError('open')):
   report=deletion.drain(self.s);self.assertEqual(report['state'],'pending');self.assertTrue(p.exists())
  self.assertEqual(deletion.drain(self.s)['state'],'complete');self.assertFalse(p.exists())

if __name__=='__main__':unittest.main()
