"""Knowledge-only source acceptance, source integrity and saved-result recovery."""
import copy,json,sys,unittest,types
from unittest.mock import patch
import test_research_knowledge as fixtures
from backend.proposal_evidence import FrozenKnowledge,sha
from backend.research_design import search,previous_failures,audit_saved
from backend.research_contracts import design,proposal_policy
from backend.safety import DomainError,digest

class StandaloneTests(unittest.TestCase):
    setUp=fixtures.RetrievalTests.setUp
    tearDown=fixtures.RetrievalTests.tearDown

    def prepare(self,kind='proposal_word'):
        self.out=self.root/'outputs/proposal';self.out.mkdir(parents=True)
        self.snapshot=self.root/'frozen.json'
        cards=[]
        for n,title in enumerate(['FAST-LIO2 original method','Intensity odometry','Degeneracy-aware fusion']):
            for section in ['mechanism','failure']:
                cards.append({'id':str(n)+section,'title':section,'content':title+' uses camera rotation. Failure under poor calibration. 退化与坐标系转换。',
                              'evidence':[],'claim_type':'synthesis','layer_id':'methods',
                              'imported_sources':[{'document_id':'doc'+str(n),'title':title,'original_path':title+'.md','source_sha256':'original-db',
                                                   'locator':{'source_id':'paper'+str(n),'doi':'10.1234/paper'+str(n)}}]})
        self.snapshot.write_text(json.dumps({'id':'kb1','revision':1,'cards':cards}),encoding='utf-8')
        job={'id':'j','task':kind,'status':'running','revision':1,'context':{'resources':[],'output_dir':'outputs/proposal',
             'proposal':{'knowledge_bases':[{'id':'kb1','revision':1,'snapshot_path':'frozen.json','sha256':digest(self.snapshot)}],
                         'research_policy':proposal_policy()}}}
        self.store.jobs['j']=job;return job,FrozenKnowledge(self.store,job)

    def test_no_paper_search_returns_real_card_evidence_and_full_context(self):
        j,k=self.prepare();answer=search(self.store,'j',{'base_revision':1,'queries':[{'lane':'mechanism','query':'FAST-LIO2 退化'}]})
        hits=answer['results'][0]['hits'];self.assertTrue(hits);self.assertEqual(self.store.validations,0)
        self.assertTrue(all(h['resource_id'] is None and not h['proof_eligible'] for h in hits))
        for h in hits:self.assertTrue(k.validate(h['evidence'][0]));self.assertIn(h['text'],h['context'])
        self.assertLess(answer['results'][0]['independent_source_count'],len(hits))

    def test_snapshot_card_scope_hash_quote_and_source_cannot_be_forged(self):
        j,k=self.prepare();entry=next(iter(k.cards.values()));e=k.citation(entry,'camera rotation')
        for field,value in [('kb_id','other'),('card_id','missing'),('kb_revision',2),('snapshot_path','other.json'),('snapshot_sha256','bad'),
                            ('card_content_sha256','bad'),('source_id','fake-paper'),('source_key','forged'),('excerpt','invented successful run'),
                            ('resource_id','fabricated-pdf'),('primary_source_verified',True)]:
            with self.subTest(field=field),self.assertRaises(DomainError):k.validate({**e,field:value})

    def test_changed_snapshot_rejected_and_unselected_raw_resource_rejected(self):
        j,k=self.prepare()
        with self.assertRaises(DomainError):k.validate_any(fixtures.evidence(self.store))
        self.snapshot.write_text('{}')
        with self.assertRaises(DomainError):FrozenKnowledge(self.store,j)

    def test_saved_authored_knowledge_is_usable_when_original_papers_are_missing(self):
        from backend.proposal_evidence import snapshot
        c=fixtures.card(self.store)
        self.store.db.execute('INSERT INTO settings VALUES(?,?)',('kb_cards:kb1',json.dumps({'cards':[c],'build_id':'old-build'})))
        kb={'id':'kb1','revision':2,'index_state':'stale','knowledge_state':'awaiting_codex','needs_revalidation':[{'source':'missing'}],'resource_ids':['r1']}
        value=snapshot(self.store,kb)
        self.assertEqual(value['cards'],[c]);self.assertEqual(value['resource_ids'],[]);self.assertTrue(value['source_review_required'])
        self.assertFalse(value['primary_sources_required'])

    def test_empty_or_raw_only_knowledge_is_not_misrepresented_as_authored_cards(self):
        from backend.proposal_evidence import snapshot
        with self.assertRaises(DomainError):snapshot(self.store,{'id':'empty'})

    def test_authored_cards_keep_source_identity_without_loading_papers(self):
        j,k=self.prepare();data=json.loads(self.snapshot.read_text())
        data['cards']=[fixtures.card(self.store,'one'),fixtures.card(self.store,'two')]
        self.snapshot.write_text(json.dumps(data));j['context']['proposal']['knowledge_bases'][0]['sha256']=digest(self.snapshot)
        self.store.resource=lambda rid:(_ for _ in ()).throw(AssertionError('Original paper must not be loaded'))
        k=FrozenKnowledge(self.store,j);self.assertEqual(len(k.identities),1)

    def test_cards_from_same_paper_and_reimported_database_are_one_source(self):
        j,k=self.prepare();self.assertEqual(len(k.identities),3)
        data=json.loads(self.snapshot.read_text());second=copy.deepcopy(data);second['id']='kb2'
        for c in second['cards']:c['imported_sources'][0]['source_sha256']='new-db-version'
        p=self.root/'second.json';p.write_text(json.dumps(second))
        j['context']['proposal']['knowledge_bases'].append({'id':'kb2','revision':1,'snapshot_path':'second.json','sha256':digest(p)})
        self.assertEqual(len(FrozenKnowledge(self.store,j).identities),3)

    def make_design(self,kind='proposal_word'):
        job,k=self.prepare(kind)
        base=fixtures.ProposalTests.make(self)[1]
        base['research_design_artifact']='outputs/proposal/design.json';base['artifacts']=[{'path':'outputs/proposal/design.json'}]
        nearest=[]
        for entry in k.identities.values():
            e=k.citation(entry,'camera rotation')
            nearest.append({'source_key':entry['source_key'],'resource_id':None,'evidence':[e],**{f:'Compared knowledge source' for f in ('problem','mechanism','assumptions','implementation','experiment')}})
        for candidate in base['research_design']['candidates']:
            candidate['evidence']=[nearest[0]['evidence'][0]];candidate['interfaces'][0]['evidence']=[nearest[0]['evidence'][0]]
            candidate['counterevidence']['evidence']=[nearest[0]['evidence'][0]]
            candidate['novelty']['nearest']=copy.deepcopy(nearest)
            candidate['experiment']['comparison_contract']={'identical':['data split','compute budget'],'failure_accounting':'Report all failures','threshold_status':'proposed'}
        self.store.db.execute('INSERT INTO settings VALUES(?,?)',('research_search:j',json.dumps({'queries':[{'lane':k} for k in proposal_policy()['search_lanes']]})))
        return job,base,k

    def check(self,j,r):
        path=self.root/r['research_design_artifact'];path.write_text(json.dumps(r['research_design']),encoding='utf-8');design(self.store,j,r)

    def test_word_and_ppt_designs_accept_knowledge_only_without_fake_pdf_ids(self):
        j,r,k=self.make_design();self.check(j,r)
        self.assertTrue(r['research_validation']['knowledge_citations_supported']);self.assertEqual(self.store.validations,0)
        j['task']='proposal_ppt';self.check(j,r)

    def test_duplicate_nearest_cards_do_not_count_as_different_studies(self):
        j,r,k=self.make_design();nearest=r['research_design']['candidates'][0]['novelty']['nearest'];nearest[1]=copy.deepcopy(nearest[0])
        with self.assertRaises(DomainError) as caught:self.check(j,r)
        self.assertEqual(caught.exception.params['reason'],'duplicate_independent_nearest_work')

    def test_fabricated_nearest_identity_and_incomplete_comparison_rejected(self):
        j,r,k=self.make_design();r['research_design']['candidates'][0]['novelty']['nearest'][0]['source_key']='invented'
        with self.assertRaises(DomainError):self.check(j,r)
        r['research_design']['candidates'][0]['novelty']['nearest'][0]['source_key']=next(iter(k.identities))
        r['research_design']['candidates'][0]['experiment']['comparison_contract']={'identical':[]}
        with self.assertRaises(DomainError):self.check(j,r)

    def test_no_model_installed_still_retrieves_knowledge(self):
        j,k=self.prepare()
        with patch.object(fixtures.kr,'encoder',side_effect=DomainError('semantic_unavailable')):
            answers,_=k.search(['FAST-LIO2'],self.out)
        self.assertTrue(answers[0]['hits']);self.assertFalse(answers[0]['learned_model'])

    def test_index_reuse_and_tampered_index_are_rebuilt_from_frozen_cards(self):
        j,k=self.prepare();a,info=k.search(['FAST-LIO2'],self.out);path=self.root/info['path'];mtime=path.stat().st_mtime_ns
        a,again=k.search(['FAST-LIO2'],self.out,info);self.assertEqual(mtime,path.stat().st_mtime_ns)
        path.write_bytes(b'tampered index');a,again=k.search(['FAST-LIO2'],self.out,info)
        self.assertTrue(a[0]['hits']);self.assertEqual(again['sha256'],digest(path))

    def test_search_budget_and_named_gaps_remain_enforced(self):
        j,k=self.prepare();search(self.store,'j',{'base_revision':1,'queries':[{'lane':'mechanism','query':'FAST-LIO2'}]})
        with self.assertRaises(DomainError):search(self.store,'j',{'base_revision':1,'queries':[{'lane':'code','query':'camera'}]})
        for n in range(2):search(self.store,'j',{'base_revision':1,'queries':[{'lane':'code','query':'camera '+str(n),'gap':'missing implementation'}]})
        with self.assertRaises(DomainError):search(self.store,'j',{'base_revision':1,'queries':[{'lane':'code','query':'camera fourth','gap':'missing'}]})

    def test_prior_knowledge_failures_rebind_only_identical_frozen_content(self):
        j,k=self.prepare();j['context']['proposal']['idea_id']='idea';entry=next(iter(k.cards.values()));e=k.citation(entry,'camera rotation');e['snapshot_path']='old-task/frozen.json'
        failure={'signature':'bad-calibration','hypothesis':'rotation','conditions':'bad calibration','observed_failure':'tracking failed','evidence':[e]}
        self.store.rows=lambda *args:[{'id':'prior'}];self.store.jobs['prior']={'result':{'research_design':{'failure_records':[failure]}}}
        self.assertEqual(previous_failures(self.store,j)[0]['evidence'][0]['snapshot_path'],'frozen.json')
        e['snapshot_sha256']='different-version';self.assertEqual(previous_failures(self.store,j),[])

    def test_saved_audit_replays_search_without_rewriting_artifacts(self):
        j,k=self.prepare();j['status']='failed';doc=self.out/'proposal.docx';doc.write_bytes(b'fixture document')
        result={'job_id':'j','schema_version':2,'artifacts':[{'path':'outputs/proposal/proposal.docx','sha256':digest(doc)}]}
        (self.out/'result.json').write_text(json.dumps(result));queries=[{'lane':lane,'query':'FAST-LIO2 '+lane} for lane in proposal_policy()['search_lanes']]
        self.store.db.execute('INSERT INTO settings VALUES(?,?)',('research_search:j',json.dumps({'queries':queries,'rounds':1})))
        self.store.ingest_job=lambda id,body:body['manifest']
        accepted=audit_saved(self.store,'j',{'base_revision':1})
        self.assertTrue(accepted['completion_audit']['generation_reused']);self.assertEqual(doc.read_bytes(),b'fixture document')
        trace=json.loads(self.store.one('SELECT value FROM settings WHERE key=?',('research_search:j',))['value'])
        self.assertTrue(all(q['hit_ids'] for q in trace['queries']))

    def test_saved_audit_refuses_changed_artifact_and_live_job(self):
        j,k=self.prepare()
        with self.assertRaises(DomainError):audit_saved(self.store,'j',{'base_revision':1})
        j['status']='failed';doc=self.out/'proposal.docx';doc.write_bytes(b'changed')
        (self.out/'result.json').write_text(json.dumps({'job_id':'j','schema_version':2,'artifacts':[{'path':'outputs/proposal/proposal.docx','sha256':'old'}]}))
        with self.assertRaises(DomainError):audit_saved(self.store,'j',{'base_revision':1})

if __name__=='__main__':unittest.main()
