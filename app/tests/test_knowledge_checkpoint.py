import hashlib,json,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
APP=Path(__file__).resolve().parents[1];sys.path.insert(0,str(APP))
sys.modules.setdefault('backend.pdf',types.ModuleType('backend.pdf'))
from backend.knowledge_workflow import checkpoint
from backend.research_contracts import normalize_analysis

class Recovery(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);out=self.root/'outputs/job';out.mkdir(parents=True)
        self.job={'id':'j','task':'build_knowledge','result':None,'context':{'output_dir':'outputs/job'}}
        self.store=types.SimpleNamespace(project=self.root);self.file=out/'analysis.json';self.file.write_text('{"authored":true}')
        self.result={'schema_version':2,'job_id':'j','status':'completed','knowledge_cards':[{'id':'card'}],'knowledge_build_report':{'queries':[]},
                     'artifacts':[{'path':'outputs/job/analysis.json','sha256':hashlib.sha256(self.file.read_bytes()).hexdigest()}]}
        self.manifest=out/'result.json';self.manifest.write_text(json.dumps(self.result))
    def tearDown(self):self.temp.cleanup()
    def test_rolled_back_job_recovers_authored_manifest_and_requires_all_gates(self):
        with patch('backend.knowledge.validate_result') as validate:
            r=checkpoint(self.store,self.job)
            validate.assert_called_once();self.assertEqual(r['knowledge_resume']['checkpoint_origin'],'saved_result_manifest')
            self.assertTrue(r['knowledge_resume']['full_retrieval_revalidation_required'])
    def test_wrong_owner_and_changed_artifact_are_not_reused(self):
        with patch('backend.knowledge.validate_result'):
            self.result['job_id']='other';self.manifest.write_text(json.dumps(self.result));self.assertIsNone(checkpoint(self.store,self.job))
            self.result['job_id']='j';self.manifest.write_text(json.dumps(self.result));self.file.write_text('changed');self.assertIsNone(checkpoint(self.store,self.job))
    def test_shared_retry_has_already_moved_the_manifest(self):
        previous=self.manifest.with_name('result.previous.json');self.manifest.rename(previous)
        original=previous.read_bytes()
        with patch('backend.knowledge.validate_result'):
            self.assertIsNotNone(checkpoint(self.store,self.job))
        self.assertEqual(previous.read_bytes(),original);self.assertTrue(self.manifest.is_file())
    def test_conservative_labels_preserve_claims_sources_and_original_manifest(self):
        claims=[{'id':'fact','claim_type':'source_fact','text':'reported'}, {'id':'check','claim_type':'inference','text':'requires experiment'}]
        self.result['knowledge_cards']=[{'id':'card','claim_type':'source_fact','card_kind':'failure','claims':claims,'evidence':[{'resource_id':'r','quote':'reported limitation'}]}]
        original=json.dumps(self.result);self.manifest.write_text(original)
        with patch('backend.knowledge.validate_result'):
            value=checkpoint(self.store,self.job)
        card=value['knowledge_cards'][0]
        self.assertEqual(card['claim_type'],'inference');self.assertEqual(card['claims'],claims)
        self.assertEqual(card['evidence'],self.result['knowledge_cards'][0]['evidence'])
        self.assertEqual(self.manifest.with_name('result.previous.json').read_text(),original)
        self.assertEqual(normalize_analysis(value),value)
        renamed=json.loads(original);renamed['knowledge_cards'][0]['id']='renamed'
        self.assertEqual(normalize_analysis(renamed)['knowledge_cards'][0]['failure_signature'],card['failure_signature'])
    def test_structured_failure_is_preserved_without_inventing_an_execution(self):
        details={'observed':'paper reports drift','verification':'paper_claim','trigger':'low geometry'}
        value={'knowledge_cards':[{'id':'failure','card_kind':'failure','failure_signature':details,'evidence':[{'quote':'drift'}]}]}
        fixed=normalize_analysis(value)
        self.assertEqual(fixed['knowledge_cards'][0]['failure_details'],details)
        self.assertIsInstance(fixed['knowledge_cards'][0]['failure_signature'],str)
        self.assertEqual(value['knowledge_cards'][0]['failure_signature'],details)
    def test_old_agent_failure_does_not_cover_new_checkpoint_completion(self):
        from backend.agent_bridge import AgentBridge
        path=self.root/'jobs/j';path.mkdir(parents=True)
        old={'status':'failed','updated_at':'2026-10-12T10:00:00+00:00'}
        (path/'agent-execution.json').write_text(json.dumps(old))
        current={'task':'build_knowledge','status':'completed','execution':{'status':'completed','started_at':'2026-10-12T10:10:00+00:00'}}
        bridge=AgentBridge.__new__(AgentBridge);bridge.store=types.SimpleNamespace(state=self.root)
        bridge.compatibility=types.SimpleNamespace(job=lambda id:json.loads(json.dumps(current)))
        self.assertEqual(bridge.job('j')['execution']['status'],'completed')
        current['execution']['started_at']='2026-10-12T09:50:00+00:00'
        self.assertEqual(bridge.job('j')['execution']['status'],'failed')

if __name__=='__main__':unittest.main()
