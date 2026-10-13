import copy,importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('knowledge_finalize',Path(__file__).resolve().parents[1]/'scripts/knowledge_finalize.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class EvidenceReferences(unittest.TestCase):
    def test_compact_and_explicit_inputs_produce_identical_evidence(self):
        e={'resource_id':'r','version_id':'v','page_index':2,'quote':'A source statement.'}
        value={'evidence_catalog':{'p1':e},'knowledge_cards':[{'evidence':['p1'],'claims':[{'evidence':['p1']}]}],
               'knowledge_build_report':{'queries':[{'expected_evidence':['p1']},{'expected_evidence':[]}]}}
        before=copy.deepcopy(value);expanded=module.expand_evidence(value)
        self.assertEqual(expanded['knowledge_cards'][0]['evidence'],[e]);self.assertEqual(expanded['knowledge_cards'][0]['claims'][0]['evidence'],[e])
        self.assertEqual(expanded['knowledge_build_report']['queries'][0]['expected_evidence'],[e]);self.assertEqual(value,before)
        self.assertEqual(module.expand_evidence(expanded),expanded)
    def test_missing_and_malformed_references_fail_before_rendering(self):
        for value in ({'evidence':['missing']},{'evidence_catalog':{'p':{'quote':'no locator'}},'evidence':['p']}):
            with self.assertRaises(ValueError):module.expand_evidence(value)
    def test_omitted_method_fields_expand_only_as_unknown(self):
        value={'knowledge_cards':[{'card_kind':'method','method_profile':{'inputs':{'value':'point cloud','status':'source_reported','claim_ids':['c']}}}]}
        profile=module.expand_evidence(value)['knowledge_cards'][0]['method_profile']
        self.assertEqual(len(profile),15);self.assertEqual(profile['inputs'],value['knowledge_cards'][0]['method_profile']['inputs'])
        self.assertEqual(profile['code'],{'value':None,'status':'unknown','claim_ids':[]})

if __name__=='__main__':unittest.main()
