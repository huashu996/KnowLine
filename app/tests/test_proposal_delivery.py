"""Failed tasks expose only their own Office file; finalization retains evidence."""
from collections import OrderedDict
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
import zipfile

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP));sys.path.insert(0,str(APP/'scripts'))
from backend.safety import contained,digest,DomainError
from research_finalize import normalize_proposal
from patch_frozen_modules import module_code
EXE=None
if '--exe' in sys.argv:
    i=sys.argv.index('--exe');EXE=Path(sys.argv[i+1]);del sys.argv[i:i+2]
code=module_code(EXE,'backend.office_native') if EXE else compile((APP/'backend/office_native.py').read_bytes(),'office_native','exec')
fn=next(c for c in code.co_consts if isinstance(c,types.CodeType) and c.co_name=='figure_drafts')
drafts=types.FunctionType(fn,dict(contained=contained,digest=digest,DomainError=DomainError,
    _draft_hashes=OrderedDict(),_draft_hash_lock=threading.Lock()))


class Delivery(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.output=self.root/'outputs/task';self.output.mkdir(parents=True)
        self.file=self.output/'proposal.docx'
        with zipfile.ZipFile(self.file,'w') as z:
            z.writestr('[Content_Types].xml','fixture');z.writestr('word/document.xml','fixture')
        self.job={'task':'proposal_word','status':'failed','result':None,
            'context':{'output_dir':'outputs/task','proposal':{'target_path':'outputs/task/proposal.docx'}}}
        self.store=types.SimpleNamespace(project=self.root)

    def test_failed_partial_and_interrupted_word_remain_downloadable(self):
        for status in ['failed','partial','interrupted']:
            self.job['status']=status
            row=drafts(self.store,self.job)[0]
            self.assertEqual(row['sha256'],digest(self.file))
            self.assertEqual(row['validation_status'],'not_passed')
            self.assertTrue(row['is_draft'])

    def test_missing_invalid_package_and_other_task_file_are_not_exposed(self):
        self.file.write_bytes(b'not a word document')
        self.assertEqual(drafts(self.store,self.job),[])
        self.file.unlink();self.assertEqual(drafts(self.store,self.job),[])
        self.job['context']['proposal']['target_path']='other.docx'
        self.assertEqual(drafts(self.store,self.job),[])

    def test_registered_and_in_progress_results_do_not_duplicate_drafts(self):
        self.job['result']={'artifacts':[{'path':'outputs/task/proposal.docx','sha256':digest(self.file)}]}
        self.assertEqual(drafts(self.store,self.job),[])
        self.job['result']=None;self.job['status']='running'
        self.assertEqual(drafts(self.store,self.job),[])

    def test_figure_ppt_draft_route_is_preserved(self):
        ppt=self.output/'diagram.working.pptx'
        with zipfile.ZipFile(ppt,'w') as z:
            z.writestr('[Content_Types].xml','fixture');z.writestr('ppt/presentation.xml','fixture')
        self.job.update(task='replicate_paper_figure')
        self.job['context']['figure_selection']={'target_pptx':'outputs/task/diagram.pptx'}
        self.assertEqual(drafts(self.store,self.job)[0]['path'],'outputs/task/diagram.working.pptx')

    def test_field_normalization_keeps_every_evidence_and_does_not_invent_content(self):
        paper={'source_key':'paper','excerpt':'paper excerpt'};code={'source_key':'code','excerpt':'code excerpt'}
        value={'research_design':{'candidates':[{'evidence':[], 'novelty':{'nearest':[{'source_key':'paper','evidence':[paper,code]}]},
            'experiment':{'comparison_contract':{'same_data':'data','same_split':'split','same_budget':'budget',
                'same_reporting':'include failures','threshold_status':'proposed'}}}]}}
        original=copy.deepcopy(value);fixed=normalize_proposal(value);candidate=fixed['research_design']['candidates'][0]
        self.assertEqual(value,original)
        self.assertEqual(candidate['novelty']['nearest'][0]['evidence'],[paper])
        self.assertEqual(candidate['evidence'],[code])
        self.assertEqual(candidate['experiment']['comparison_contract']['identical'],['data','split','budget'])
        self.assertEqual(candidate['experiment']['comparison_contract']['failure_accounting'],'include failures')
        self.assertEqual(normalize_proposal(fixed),fixed)

    def test_missing_fields_and_unmatched_identity_are_not_filled_or_relabeled(self):
        value={'research_design':{'candidates':[{'evidence':[], 'novelty':{'nearest':[{'source_key':'fake','evidence':[{'source_key':'actual'}]}]},
            'experiment':{'comparison_contract':{'same_data':'data'}}}]}}
        self.assertEqual(normalize_proposal(value),value)


if __name__=='__main__':unittest.main()
