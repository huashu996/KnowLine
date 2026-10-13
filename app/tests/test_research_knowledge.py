"""Isolated evidence/retrieval/proposal behavior; fixtures are not research evidence."""
import copy,hashlib,json,sqlite3,sys,tempfile,types,unittest,zipfile
from pathlib import Path
from unittest.mock import patch

APP=Path(__file__).resolve().parents[1];sys.path.insert(0,str(APP))
if '--exe' in sys.argv:
    import importlib.abc,importlib.util,marshal,zlib
    index=sys.argv.index('--exe');target=Path(sys.argv[index+1]);del sys.argv[index:index+2]
    sys.path.insert(0,str(APP/'scripts'));from patch_frozen_modules import modules
    blob,toc=modules(target)
    class FrozenResearch(importlib.abc.MetaPathFinder,importlib.abc.Loader):
        def find_spec(self,name,path=None,target=None):
            if name in {'backend.knowledge_retrieval','backend.knowledge_evidence','backend.research_contracts','backend.research_design','backend.proposal_evidence'}:
                return importlib.util.spec_from_loader(name,self)
        def create_module(self,spec):return None
        def exec_module(self,module):
            _,offset,size=toc[module.__name__];module.__file__=str(APP/Path(*module.__name__.split('.')).with_suffix('.py'))
            exec(marshal.loads(zlib.decompress(blob[offset:offset+size])),module.__dict__)
    sys.meta_path.insert(0,FrozenResearch())
# No PyMuPDF dependency for these code-source fixtures.
sys.modules.setdefault('backend.pdf',types.ModuleType('backend.pdf'))
from backend import knowledge_retrieval as kr
from backend import research_contracts as rc
from backend.knowledge_evidence import raw_parents,units_from_parents,windows,code_sections,stale_dependencies
from backend.safety import DomainError,digest

class Encoder:
    def __init__(self):self.tokenizer='tokenizer-a';self.ranking=False;self.calls=0
    def encode(self,texts,kind='document'):
        self.calls+=1
        return {'model_id':'fixture-learned-model','model_revision':'1','tokenizer_sha256':self.tokenizer,'query_instruction':'fixture instruction',
                'document_instruction':'','pooling':'test','learned_model':True,'dimensions':4,
                'vectors':[[t.lower().count(w)+.1 for w in ('camera','failure','rotation','cache')] for t in texts]}
    def rerank(self,q,texts):
        return {'available':True,'model_id':'fixture-cross-encoder','scores':[float('failure' in t.lower()) for t in texts]} if self.ranking else {'available':False,'reason':'local_model_not_installed'}

class Store:
    def __init__(self,root):
        self.project=root;self.state=root/'resource/.knowledge';self.state.mkdir(parents=True)
        self.config={};self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)')
        path=root/'source.zip'
        self.source='''# Original code fixture: camera coordinates, not world coordinates.\ndef rotate(points):\n    """Rotation requires camera coordinates.\n    Failure condition: invalid calibration breaks the estimate.\n    The cache must have the same timestamp.\n    """\n    return points\n\ndef world_transform(points):\n    """World coordinates require an explicit camera-to-world transform."""\n    return points\n'''
        with zipfile.ZipFile(path,'w') as z:z.writestr('model.py',self.source)
        self.r={'id':'r1','type':'code','title':'Camera rotation method','version_id':'v1','sha256':digest(path),'metadata':{}}
        self.frozen={'resource_id':'r1','version_id':'v1','type':'code','sha256':digest(path),'snapshot_path':'source.zip','allowed_files':['model.py']}
        self.jobs={};self.validations=0
    def one(self,q,args=()):
        r=self.db.execute(q,args).fetchone();return dict(r) if r else None
    def resource(self,id):
        if id!='r1':raise DomainError('scope_violation')
        return self.r
    def snapshot(self,r,version):
        if version!='v1':raise DomainError('version_not_found')
        return self.project/'source.zip'
    def code_file(self,r,name,version):
        if name!='model.py' or version!='v1':raise DomainError('scope_violation')
        return {'text':self.source,'sha256':hashlib.sha256(self.source.encode()).hexdigest()}
    def validate_evidence(self,e,resources):
        self.validations+=1
        if not any(r['resource_id']==e['resource_id'] and r['version_id']==e['version_id'] for r in resources):raise DomainError('scope_violation')
        if e['quote'] not in self.source:raise DomainError('quote_not_found')
    def job(self,id):return self.jobs[id]
    def check(self,job,body):
        if job['revision']!=body['base_revision']:raise DomainError('revision_conflict')

def evidence(store):return {'resource_id':'r1','version_id':'v1','file':'model.py','file_sha256':store.code_file(None,'model.py','v1')['sha256'],'line_start':1,'line_end':1,'quote':'camera coordinates, not world coordinates.'}
def card(store,id='method',kind='source_fact'):
    e=evidence(store)
    return {'id':id,'layer_id':'layer_1','layer_ids':['layer_1','layer_2'],'title':'Camera method','content':'## Mechanism\nCamera rotation uses calibration.\n'+'rotation '*35+'\n## Limitations\nFailure occurs with inconsistent timestamps. '+ 'failure '*30,
            'evidence':[e],'links':[],'terms':['camera','failure'],'aliases':[],'claim_type':kind,'card_kind':'concept',
            'claims':[{'id':'c1','text':'camera coordinates, not world coordinates.','claim_type':kind,'verification':'code_present','evidence':[e]}]}

class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.store=Store(self.root);self.model=Encoder()
        self.mock=patch.object(kr,'encoder',return_value=self.model);self.mock.start()
        self.kb={'id':'kb1','build_id':'build1','layers':[{'id':'layer_1','name':'method','focus':'mechanism'},{'id':'layer_2','name':'limits','focus':'failure'}]}
    def tearDown(self):self.mock.stop();self.store.db.close();self.temp.cleanup()
    def build(self,cards=None):return kr.build(self.store,self.kb,cards or [card(self.store)],{'queries':[]},[self.store.frozen])
    def test_dual_index_and_complete_function_context(self):
        info=self.build();self.assertGreater(info['raw_units'],0);self.assertGreater(info['knowledge_units'],0)
        answer=kr.query_batch(self.store,info,['camera failure'])[0]
        raw=next(h for h in answer['hits'] if h['kind']=='raw_evidence' and 'rotate' in h['context'])
        self.assertIn('Failure condition',raw['context']);self.assertIn('return points',raw['context'])
        self.assertTrue(raw['proof_eligible']);self.assertTrue(all(not h['proof_eligible'] for h in answer['hits'] if h['kind']=='knowledge_card'))
        self.assertTrue(kr.expand(self.store,info,raw['id'])['original_context_preserved'])
    def test_same_card_mechanism_and_failure_are_not_early_deduplicated(self):
        info=self.build();answer=kr.query_batch(self.store,info,['camera failure'])[0]
        self.assertGreaterEqual(sum(h['card_id']=='method' for h in answer['hits']),2)
        self.assertEqual(answer['independent_source_count'],1)
    def test_ideas_are_inspiration_only_even_if_they_are_most_similar(self):
        idea=card(self.store,'idea','research_idea');info=self.build([card(self.store),idea])
        self.assertFalse(any(h['card_id']=='idea' for h in kr.query_batch(self.store,info,['camera'])[0]['hits']))
        self.assertTrue(any(h['card_id']=='idea' and not h['proof_eligible'] for h in kr.query_batch(self.store,info,['camera'],purpose='inspiration')[0]['hits']))
    def test_second_layer_retrieval_does_not_require_exclusive_membership(self):
        info=self.build();self.assertTrue(any(h['card_id']=='method' for h in kr.query_batch(self.store,info,['camera'],layer_ids=['layer_2'])[0]['hits']))
    def test_bounded_context_expansion_preserves_original_and_filters_ideas(self):
        method=card(self.store);related=card(self.store,'related');related['links']=['method']
        idea=card(self.store,'idea','research_idea');idea['links']=['method']
        info=self.build([method,related,idea]);answer=kr.query_batch(self.store,info,['camera'],top_k=2)[0]
        self.assertLessEqual(answer['ranked_hit_count'],2);self.assertLessEqual(answer['related_knowledge_count'],8)
        self.assertLessEqual(answer['source_context_count'],24);self.assertFalse(any(h['card_id']=='idea' for h in answer['hits']))
        self.assertTrue(any(h.get('retrieval_via')=='explicit_relation' for h in answer['hits']))
        for h in answer['hits']:
            if h.get('retrieval_via')=='cited_parent_context':self.assertEqual(kr.expand(self.store,info,h['id'])['parent']['content'],h['context'])
    def test_mixed_card_keeps_verified_claims_as_navigation(self):
        c=card(self.store);c['claims'].append({**copy.deepcopy(c['claims'][0]),'id':'hypothesis','claim_type':'inference','text':'camera hypothesis'})
        c=rc.normalize_analysis({'knowledge_cards':[c]})['knowledge_cards'][0]
        self.assertEqual(c['claim_type'],'inference')
        info=self.build([c]);answer=kr.query_batch(self.store,info,['camera'])[0]
        self.assertTrue(any(h['claim_id']=='c1' and not h['proof_eligible'] for h in answer['hits'] if h['kind']=='knowledge_card'))
        self.assertFalse(any(h['claim_type']=='inference' for h in answer['hits']))
    def test_inferred_method_fields_are_not_fact_evidence(self):
        c=card(self.store);c['method_profile']={'mechanism':{'value':'hypothetical camera cache','status':'inferred','claim_ids':['c1']}}
        info=self.build([c]);answers=kr.query_batch(self.store,info,['camera cache'])[0]
        self.assertFalse(any(h['parent_id'].startswith('method:') for h in answers['hits']))
        self.assertTrue(any(h['parent_id'].startswith('method:') and not h['proof_eligible'] for h in kr.query_batch(self.store,info,['camera cache'],purpose='inspiration')[0]['hits']))
    def test_reranker_optional_status_and_real_scores(self):
        info=self.build();self.assertEqual(kr.query_batch(self.store,info,['camera'])[0]['reranker']['status'],'not_available')
        self.model.ranking=True;answer=kr.query_batch(self.store,info,['camera'])[0]
        self.assertEqual(answer['reranker']['status'],'applied');self.assertEqual(answer['hits'][0]['rerank_score'],1)
    def test_tokenizer_change_cannot_reuse_vectors_or_query_with_mismatched_model(self):
        first=self.build();self.model.tokenizer='tokenizer-b';answer=kr.query_batch(self.store,first,['camera'])[0]
        self.assertFalse(answer['learned_model']);second=self.build();self.assertEqual(second['vectors_reused'],0)
        self.assertNotEqual(first['input_fingerprint'],second['input_fingerprint'])
    def test_unchanged_index_reuse_revalidates_every_query(self):
        first=self.build();self.store.db.execute('INSERT INTO settings VALUES(?,?)',('kb_cards:kb1',json.dumps({'retrieval':first})))
        second=kr.build(self.store,self.kb,[card(self.store)],{'queries':[{'query':'camera','expected_card_ids':['method'],'expected_evidence':[evidence(self.store)]}]},[self.store.frozen])
        self.assertTrue(second['index_reused']);self.assertEqual(second['evaluation']['case_count'],1)
    def test_all_critical_evidence_required_not_just_one_card(self):
        info=self.build();missing={**evidence(self.store),'resource_id':'missing'}
        with self.assertRaises(DomainError):kr.evaluate(self.store,info,{'queries':[{'query':'camera','expected_card_ids':['method'],'expected_evidence':[missing]}]})
    def test_design_evaluation_can_recall_inspiration_without_using_it_as_proof(self):
        info=self.build([card(self.store,'idea','research_idea')])
        r=kr.evaluate(self.store,info,{'queries':[{'query':'camera','category':'research_design','expected_card_ids':['idea'],'expected_evidence':[evidence(self.store)]}]})
        self.assertEqual(r['cases'][0]['purpose'],'inspiration');self.assertTrue(r['cases'][0]['retrieval_passed'])
    def test_tampered_index_and_source_are_rejected(self):
        info=self.build();(self.root/info['path']).write_bytes(b'changed')
        with self.assertRaises(DomainError):kr.query_batch(self.store,info,['camera'])
        self.store.frozen['sha256']='bad'
        with self.assertRaises(DomainError):self.build()
    def test_source_windows_keep_every_character_and_parent_definition(self):
        text='Equation x=t.\n\n'+'x=1;'*300+' Only valid for calibrated cameras.'
        covered=set()
        for a,b,_ in windows(text):covered.update(range(a,b))
        self.assertEqual(len(covered),len(text))
        parts=list(code_sections(self.store.source,'model.py'));self.assertEqual(''.join(p[2] for p in parts),self.store.source)
    def test_stale_marks_claims_without_changing_historical_evidence(self):
        c=card(self.store);before=copy.deepcopy(c);affected=stale_dependencies([c],{'r1':'v2'})
        self.assertEqual(affected[0]['claim_ids'],['c1']);self.assertEqual(c,before)
    def test_research_search_budget_scope_and_named_gaps(self):
        from backend.research_design import search
        out=self.root/'outputs/proposal';out.mkdir(parents=True)
        j={'id':'job','task':'proposal_word','status':'running','revision':1,'context':{'output_dir':'outputs/proposal','resources':[self.store.frozen],'proposal':{'knowledge_bases':[]}}};self.store.jobs['job']=j
        body={'base_revision':1,'queries':[{'lane':k,'query':'camera '+k} for k in rc.proposal_policy()['search_lanes']]}
        answer=search(self.store,'job',body);self.assertEqual(answer['remaining_queries'],8)
        with self.assertRaises(DomainError):search(self.store,'job',body)
        with self.assertRaises(DomainError):search(self.store,'job',{'base_revision':1,'queries':[{'lane':'code','query':'different'}]})
        for i in range(2):search(self.store,'job',{'base_revision':1,'queries':[{'lane':'code','query':'camera '+str(i),'gap':'Need the coordinate transform function.'}]})
        with self.assertRaises(DomainError):search(self.store,'job',{'base_revision':1,'queries':[{'lane':'code','query':'last','gap':'gap'}]})

class ContractTests(RetrievalTests):
    def knowledge_result(self):
        c=card(self.store);c['card_kind']='method';c['method_profile']={k:{'value':None,'status':'unknown','claim_ids':[]} for k in rc.METHOD_FIELDS}
        c['method_profile']['coordinate_frame']={'value':'camera','status':'source_reported','claim_ids':['c1']}
        categories=sorted(rc.CATEGORIES)
        cases=[]
        for i in range(30):
            category=categories[i%len(categories)];negative=category=='unanswerable'
            cases.append({'query':f'Fixture research question {i}: camera condition?', 'language':'en' if i%2 else 'zh','category':category,
                          'expected_card_ids':[] if negative else ['method'],'expected_evidence':[] if negative else [evidence(self.store)],
                          'answer_checks':['Do not mix coordinate frames.'],'missing_evidence_reason':'Not in source.'})
        return {'knowledge_cards':[c],'knowledge_build_report':{'queries':cases}}
    def job(self):return {'context':{'resources':[self.store.frozen],'knowledge_layers':self.kb['layers'],'knowledge_build':{'research_contract':rc.CONTRACT}}}
    def test_unknown_method_fields_and_thirty_evaluation_cases(self):rc.knowledge(self.store,self.job(),self.knowledge_result())
    def test_known_method_without_claim_and_fabricated_execution_fail(self):
        r=self.knowledge_result();r['knowledge_cards'][0]['method_profile']['coordinate_frame']['claim_ids']=[]
        with self.assertRaises(DomainError):rc.knowledge(self.store,self.job(),r)
        r=self.knowledge_result();r['knowledge_cards'][0]['claims'][0]['verification']='execution_reported'
        with self.assertRaises(DomainError):rc.knowledge(self.store,self.job(),r)
    def test_three_smoke_questions_cannot_pass_v4(self):
        r=self.knowledge_result();r['knowledge_build_report']['queries']=r['knowledge_build_report']['queries'][:3]
        with self.assertRaises(DomainError):rc.knowledge(self.store,self.job(),r)
    def test_untraceable_claim_and_idea_as_fact_rejected(self):
        r=self.knowledge_result();r['knowledge_cards'][0]['claims'][0]['evidence'][0]['quote']='imaginary quotation'
        with self.assertRaises(DomainError):rc.knowledge(self.store,self.job(),r)
        r=self.knowledge_result();r['knowledge_cards'][0]['card_kind']='research_idea'
        with self.assertRaises(DomainError):rc.knowledge(self.store,self.job(),r)

class ProposalTests(unittest.TestCase):
    setUp=RetrievalTests.setUp
    tearDown=RetrievalTests.tearDown
    def make(self):
        e=evidence(self.store)
        candidate={'id':'minimal','strategy':'minimal_change','hypothesis':'Explicit transforms reduce frame mismatch errors.',
                   'falsifier':'Same error under equal data and runtime.','mechanism':'Transform before rotation.','difference':'Explicit frame check.',
                   'most_likely_failure':'Invalid calibration.','reuse':['rotation'],'modify':['input transform'],'add':[],'unknowns':['calibration source'],
                   'evidence':[e],'novelty':{'label':'transfer','scope':'selected_sources','limitations':'Only code in this fixture.','nearest':[]},
                   'counterevidence':{'findings':['World coordinates cannot be used directly.'],'search_result':'Original code inspected.','evidence':[e]},
                   'interfaces':[{'from':'transform','to':'rotation','coordinates':'camera','time':'same timestamp','shape':'Nx3','objective':'reduce geometric error',
                                  'status':'compatible','bridge':None,'unknowns':[],'evidence':[e]}],
                   'experiment':{k:'Concrete fixture specification.' for k in ('baseline','dataset','split','metrics','budget','controls','ablations','failure_conditions','continue_if','stop_if','first_step','comparison_contract')}}
        second=copy.deepcopy(candidate);second.update(id='assumption',strategy='assumption_test',hypothesis='Calibration noise explains failure.')
        value={'problem':{k:None for k in ('failure','inputs','outputs','baseline','metrics','compute','data','latency','time_budget','allowed_changes','frozen_components')},
               'unknowns':[],'candidates':[candidate,second],'selected_candidate_id':'minimal'}
        value['unknowns']=list(value['problem'])
        result={'research_design':value,'research_design_artifact':'outputs/design.json','artifacts':[{'path':'outputs/design.json'}]}
        job={'id':'proposal','context':{'resources':[self.store.frozen],'proposal':{'research_policy':rc.proposal_policy()}}}
        self.store.db.execute('INSERT INTO settings VALUES(?,?)',('research_search:proposal',json.dumps({'queries':[{'lane':k} for k in rc.proposal_policy()['search_lanes']]})))
        return job,result
    def check(self,job,result):
        path=self.root/'outputs/design.json';path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(result['research_design']),encoding='utf-8');rc.design(self.store,job,result)
    def test_valid_design_is_structurally_checked_not_scientifically_certified(self):
        j,r=self.make();self.check(j,r);self.assertEqual(r['research_validation']['semantic_correctness'],'requires_researcher_review')
    def test_unverified_interface_and_missing_controls_rejected(self):
        j,r=self.make();r['research_design']['candidates'][0]['interfaces'][0]['coordinates']=None
        with self.assertRaises(DomainError):self.check(j,r)
        r['research_design']['candidates'][0]['interfaces'][0]['coordinates']='camera';r['research_design']['candidates'][0]['experiment']['controls']=[]
        with self.assertRaises(DomainError):self.check(j,r)
    def test_incompatible_selected_design_and_unscoped_novelty_rejected(self):
        j,r=self.make();c=r['research_design']['candidates'][0];c['interfaces'][0]['status']='incompatible'
        with self.assertRaises(DomainError):self.check(j,r)
        c['interfaces'][0]['status']='compatible';c['novelty']['label']='first_ever'
        with self.assertRaises(DomainError):self.check(j,r)
    def test_fabricated_search_and_mismatched_artifact_rejected(self):
        j,r=self.make();self.check(j,r);(self.root/'outputs/design.json').write_text('{}')
        with self.assertRaises(DomainError):rc.design(self.store,j,r)
        self.store.db.execute('DELETE FROM settings')
        with self.assertRaises(DomainError):self.check(j,r)
    def test_editable_search_manifest_cannot_change_scope(self):
        from backend.research_design import search
        out=self.root/'outputs/search';out.mkdir(parents=True)
        self.store.jobs['job']={'id':'job','task':'proposal_word','status':'running','revision':1,'context':{'output_dir':'outputs/search','resources':[self.store.frozen],'proposal':{'knowledge_bases':[]}}}
        search(self.store,'job',{'base_revision':1,'queries':[{'lane':'code','query':'camera'}]})
        (out/'research-index.json').write_text('{"path":"outside.sqlite"}')
        answer=search(self.store,'job',{'base_revision':1,'queries':[{'lane':'counterevidence','query':'failure','gap':'Need calibration limitations.'}]})
        self.assertTrue(answer['results'][0]['hits']);self.assertTrue(all(h['resource_id']=='r1' for h in answer['results'][0]['hits']))
    def test_same_paper_versions_are_not_independent_nearest_works(self):
        j,r=self.make();j['context']['resources']=[{**self.store.frozen,'type':'paper'},{**self.store.frozen,'type':'paper','resource_id':'r2'}]
        self.store.resource=lambda rid:{'id':rid,'metadata':{'metadata_status':'verified','doi':'10.example/same-paper'}}
        nearest={'resource_id':'r1','problem':'comparison','mechanism':'comparison','assumptions':'comparison','implementation':'comparison','experiment':'comparison','evidence':[evidence(self.store)]}
        r['research_design']['candidates'][0]['novelty']['nearest']=[nearest,{**nearest,'resource_id':'r2','evidence':[{**evidence(self.store),'resource_id':'r2'}]}]
        with self.assertRaises(DomainError) as caught:self.check(j,r)
        self.assertEqual(caught.exception.params['reason'],'duplicate_independent_nearest_work')
    def test_previous_failures_require_current_scoped_evidence(self):
        from backend.research_design import previous_failures
        j,r=self.make();j['context']['proposal']['idea_id']='idea'
        self.store.rows=lambda *args:[{'id':'prior'}]
        f={'signature':'frame mismatch','hypothesis':'transform','conditions':'bad calibration','observed_failure':'wrong frame','evidence':[evidence(self.store)]}
        self.store.jobs['prior']={'result':{'research_design':{'failure_records':[f]}}}
        self.assertEqual(previous_failures(self.store,j)[0]['signature'],'frame mismatch')
        f['evidence'][0]['version_id']='old'
        self.assertEqual(previous_failures(self.store,j),[])

class RefreshTests(unittest.TestCase):
    setUp=RetrievalTests.setUp
    tearDown=RetrievalTests.tearDown
    def prepare(self):
        c=card(self.store);self.kb.update(revision=1,knowledge_state='organized')
        artifact=self.root/'analysis.json';artifact.write_text('{"authored":true}')
        result={'knowledge_cards':[c],'artifacts':[{'path':'analysis.json','sha256':digest(artifact)}],
                'knowledge_build_report':{'layers':[{'layer_id':l['id'],'status':'covered','card_ids':[c['id']]} for l in self.kb['layers']],
                                          'resources':[{'resource_id':'r1','version_id':'v1'}],
                                          'queries':[{'query':'camera '+str(i),'expected_card_ids':['method'],'expected_evidence':[evidence(self.store)]} for i in range(3)]}}
        job={'id':'j','context':{'knowledge_layers':self.kb['layers'],'resources':[self.store.frozen],
                               'knowledge_build':{'prepared_sources':[{'resource_id':'r1','page_count':None}]}},'result':result}
        self.store.kb=lambda id:self.kb;self.store.job=lambda id:job;self.store.event=lambda *args:None
        self.store.db.execute('CREATE TABLE knowledge_bases(id TEXT PRIMARY KEY, revision INTEGER)');self.store.db.execute('INSERT INTO knowledge_bases VALUES(?,1)',('kb1',))
        self.store.db.execute('INSERT INTO settings VALUES(?,?)',('kb_cards:kb1',json.dumps({'job_id':'j','cards':[c]})))
        return job
    def test_refresh_retrieves_full_sources_without_regenerating_analysis(self):
        from backend.knowledge import refresh_retrieval
        job=self.prepare();original=copy.deepcopy(job['result']);refresh_retrieval(self.store,'kb1',{'base_revision':1})
        saved=json.loads(self.store.one('SELECT value FROM settings WHERE key=?',('kb_cards:kb1',))['value'])
        self.assertGreater(saved['retrieval']['raw_units'],0);self.assertEqual(saved['retrieval']['evaluation']['case_count'],3)
        self.assertEqual(job['result'],original);self.assertEqual(self.store.one('SELECT revision FROM knowledge_bases')['revision'],2)
    def test_stale_knowledge_and_changed_analysis_cannot_be_refreshed(self):
        from backend.knowledge import refresh_retrieval
        self.prepare();self.kb['knowledge_state']='awaiting_codex'
        with self.assertRaises(DomainError):refresh_retrieval(self.store,'kb1',{'base_revision':1})
        self.kb['knowledge_state']='organized';(self.root/'analysis.json').write_text('modified')
        with self.assertRaises(DomainError):refresh_retrieval(self.store,'kb1',{'base_revision':1})

if __name__=='__main__':unittest.main(verbosity=2)
