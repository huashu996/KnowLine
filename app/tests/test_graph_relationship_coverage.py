"""Relationship-worker regressions: evidence gates and source coverage."""
import copy
import hashlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
if '--exe' in sys.argv:
    index=sys.argv.index('--exe');exe=Path(sys.argv[index+1]);del sys.argv[index:index+2]
    sys.path.insert(0,str(APP/'scripts'))
    from patch_frozen_modules import module_code
    import backend
    frozen=types.ModuleType('backend.paper_graph');frozen.__package__='backend'
    sys.modules[frozen.__name__]=frozen;backend.paper_graph=frozen
    exec(module_code(exe,'backend.paper_graph'),frozen.__dict__)
from backend.paper_graph import (build_relationship_audit,canonical_doi,
    coverage_annotations,verified_record_identifiers,verified_resource_identifiers,source,validate_citation_refresh,load)
from backend.safety import DomainError
from scripts.research_fetch_citations import build_audit

STAMP='2026-10-13T00:00:00+00:00'


def node(identifier,doi,title=None,year=2024,count=0):
    return {'id':identifier,'doi':doi,'title':title or 'Paper '+identifier,
        'authors':['Wei Xu','Yixi Cai'],'year':year,'venue':'IEEE Transactions on Robotics',
        'citation_count':count,'citation_source':{'url':'https://api.crossref.org/works/'+doi,'provider':'Crossref','retrieved_at':STAMP},
        'metadata_source':{'url':'https://doi.org/'+doi,'retrieved_at':STAMP}}


def graph():
    return {'schema_version':1,'origin_id':'origin','nodes':[
        node('origin','10.1234/origin'),node('middle','10.1234/middle'),node('target','10.1234/tar.get')], 'edges':[]}


def row(identifier,doi,references,provider='Crossref'):
    response={'message':{'DOI':doi,'reference':references}} if provider=='Crossref' else {
        'externalIds':{'DOI':doi},'references':references}
    return {'node_id':identifier,'attempts':[{'provider':provider,'url':
        ('https://api.crossref.org/works/' if provider=='Crossref' else 'https://api.semanticscholar.org/graph/v1/paper/DOI:')+doi,
        'retrieved_at':STAMP,'status':200,'response':response}]}


class RelationshipCoverageTests(unittest.TestCase):
    def test_resolver_doi_labels_case_and_punctuation(self):
        self.assertEqual(canonical_doi(' HTTPS://DX.DOI.ORG/10.1234/TAR.GET?x=1 '),'10.1234/tar.get')
        self.assertEqual(canonical_doi('doi: 10.1234/TAR.GET'),'10.1234/tar.get')
        self.assertNotEqual(canonical_doi('10.1234/tar.get'),canonical_doi('10.1234/tar-get'))

    def test_every_selected_node_checked_without_year_filter(self):
        g=graph();g['nodes'][2]['year']=2022
        audit={'rows':[row('origin','10.1234/origin',[{'DOI':'HTTPS://DOI.ORG/10.1234/MIDDLE'}]),
            row('middle','10.1234/middle',[{'DOI':'doi:10.1234/tar.get'}]),row('target','10.1234/tar.get',[])]}
        revised,report=build_audit(g,responses=audit)
        self.assertEqual({(edge['source'],edge['target']) for edge in revised['edges']},{('origin','middle'),('middle','target')})
        self.assertEqual(report['references_checked_nodes'],3)
        self.assertEqual(report['indirect_nodes'][0]['id'],'target')
        self.assertTrue(all(node['citation_count_status']=='verified' for node in revised['nodes']))
        self.assertEqual(revised['nodes'][0]['citation_count'],0)
        self.assertTrue(all(any(s['provider']=='Semantic Scholar' and s['status']=='not_checked' for s in n['reference_sources']) for n in revised['nodes']))

    def test_repeated_response_not_double_counted(self):
        entry=row('middle','10.1234/middle',[{'DOI':'10.1234/tar.get'},{'article-title':'Other'}])
        entry['attempts'].append(copy.deepcopy(entry['attempts'][0]))
        revised,report=build_relationship_audit(graph(),{'rows':[entry]})
        middle=next(n for n in revised['nodes'] if n['id']=='middle')
        self.assertEqual(middle['reference_count'],2)
        self.assertEqual(report['unresolved_reference_count'],1)
        self.assertEqual(len(revised['edges']),1)

    def test_missing_doi_requires_exact_title_author_year(self):
        g=graph();target=g['nodes'][2]
        good={'article-title':target['title'],'author':'Xu','year':'2024'}
        revised,report=build_relationship_audit(g,{'rows':[row('middle','10.1234/middle',[good])]})
        self.assertEqual(report['matched_references_without_doi'],1)
        self.assertEqual(revised['edges'][0]['evidence'][0]['matched_basis'],'exact_reference_title_author_year')
        for change in ({'year':'2023'},{'author':'Wang'},{'article-title':target['title']+' revised'}):
            bad={**good,**change}
            revised,_=build_relationship_audit(g,{'rows':[row('middle','10.1234/middle',[bad])]})
            self.assertEqual(revised['edges'],[])

    def test_arxiv_reference_is_not_guessed_by_title(self):
        g=graph();target=g['nodes'][2]
        ref={'article-title':target['title'],'author':'Xu','year':'2024','journal-title':'arXiv:2107.06829'}
        revised,report=build_relationship_audit(g,{'rows':[row('middle','10.1234/middle',[ref])]})
        self.assertEqual(revised['edges'],[])
        self.assertEqual(report['unresolved_references'][0]['reason'],'publication_version_alias_unverified')

    def test_verified_alias_links_preprint_to_formal_node(self):
        aliases=[{'node_id':'target','identifier':'arxiv:2107.06829v1','formal_doi':'10.1234/tar.get','verified':True,
            'evidence':[{'url':'https://arxiv.org/abs/2107.06829v1','retrieved_at':STAMP,'relationship':'exact_title_all_authors_unique_repository_record'}]}]
        for ref in ({'journal-title':'arXiv:2107.06829','year':'2021'}, {'DOI':'10.48550/arXiv.2107.06829'}):
            revised,_=build_relationship_audit(graph(),{'rows':[row('middle','10.1234/middle',[ref])]},aliases)
            self.assertEqual(revised['edges'][0]['target'],'target')
            proof=revised['edges'][0]['evidence'][0]
            self.assertEqual(proof['matched_basis'],'verified_publication_version_alias')
            self.assertEqual(proof['target_doi'],'10.1234/tar.get')
            self.assertEqual(proof['version_alias_evidence'][0]['relationship'],'exact_title_all_authors_unique_repository_record')

    def test_wrong_or_unverified_alias_rejected(self):
        base={'node_id':'target','identifier':'arxiv:2107.06829','formal_doi':'10.1234/tar.get','verified':True,
            'evidence':[{'url':'https://arxiv.org/abs/2107.06829','retrieved_at':STAMP}]}
        audit={'rows':[row('middle','10.1234/middle',[{'journal-title':'arXiv:2107.06829'}])]}
        for change in ({'formal_doi':'10.1234/other'},{'verified':False},{'evidence':[]}):
            revised,_=build_relationship_audit(graph(),audit,[{**base,**change}])
            self.assertEqual(revised['edges'],[])

    def test_s2_exact_source_records_are_used(self):
        entry=row('middle','10.1234/middle',[{'externalIds':{'DOI':'10.1234/tar.get'},'title':'Paper target'}],'Semantic Scholar')
        revised,_=build_relationship_audit(graph(),{'rows':[entry]})
        self.assertEqual(len(revised['edges']),1)
        self.assertEqual(revised['edges'][0]['evidence'][0]['provider'],'Semantic Scholar')
        entry['attempts'][0]['response']['externalIds']['DOI']='10.1234/other'
        revised,_=build_relationship_audit(graph(),{'rows':[entry]})
        self.assertEqual(revised['edges'],[])

    def test_rate_limit_is_incomplete_and_does_not_fabricate_zero(self):
        g=graph();g['nodes'][1]['citation_count']=None;g['nodes'][1]['citation_source']=None
        audit={'rows':[{'node_id':'middle','attempts':[{'provider':'Crossref','url':'https://api.crossref.org/works/10.1234/middle',
            'retrieved_at':STAMP,'status':429,'error':'rate limited'}]}]}
        revised,_=build_relationship_audit(g,audit)
        middle=next(n for n in revised['nodes'] if n['id']=='middle')
        self.assertFalse(middle['references_checked'])
        self.assertEqual(middle['references_status'],'query_incomplete')
        self.assertEqual(middle['citation_count_status'],'query_incomplete')
        self.assertIsNone(middle['citation_count'])
        target=next(n for n in revised['nodes'] if n['id']=='target')
        self.assertEqual(target['references_status'],'not_checked')

    def test_inputs_remain_frozen(self):
        g=graph();audit={'rows':[row('middle','10.1234/middle',[{'DOI':'10.1234/tar.get'}])]}
        before=json.dumps([g,audit],sort_keys=True)
        build_audit(g,responses=audit)
        self.assertEqual(json.dumps([g,audit],sort_keys=True),before)

    def test_publication_alias_requires_matching_evidence_hash(self):
        g=graph();target=g['nodes'][2]
        with tempfile.TemporaryDirectory() as directory:
            project=Path(directory);path=project/'proof.json'
            identity={'identity_key':'arxiv:2107.06829','url':'https://arxiv.org/abs/2107.06829v1','retrieved_at':STAMP,
                'title':target['title'],'authors':target['authors'],'formal_doi':'','relationship':'exact_title_all_authors_unique_repository_record'}
            path.write_text(json.dumps({'doi':target['doi'],'related_identifiers':['arxiv:2107.06829'],'identity_evidence':[identity]}),'utf-8')
            record={**target,'id':'pr_verified','metadata_status':'verified','latest_verified':True,'related_identifiers':['arxiv:2107.06829'],
                'evidence_path':'proof.json','evidence_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            aliases=verified_record_identifiers(g,[record],project)
            self.assertEqual(len(aliases),1)
            self.assertEqual(aliases[0]['evidence'][0]['relationship'],'exact_title_all_authors_unique_repository_record')
            record['evidence_sha256']='0'*64
            self.assertEqual(verified_record_identifiers(g,[record],project),[])

    def test_named_immutable_bridge_proof_survives_metadata_refresh(self):
        g=graph();target=g['nodes'][2]
        with tempfile.TemporaryDirectory() as directory:
            project=Path(directory)
            identity={'identity_key':'arxiv:2107.06829','url':'https://arxiv.org/abs/2107.06829v1','retrieved_at':STAMP,
                'title':target['title'],'authors':target['authors'],'formal_doi':'','relationship':'exact_title_all_authors_unique_repository_record'}
            raw=json.dumps({'doi':target['doi'],'related_identifiers':['arxiv:2107.06829'],'identity_evidence':[identity]}).encode()
            sha=hashlib.sha256(raw).hexdigest();bridge='citation-'+sha+'.json';(project/bridge).write_bytes(raw)
            path=project/'current.json';path.write_text(json.dumps({'doi':target['doi'],'identity_evidence':[],
                'related_identifiers':['arxiv:2107.06829'],'bridge_evidence_paths':[bridge]}),'utf-8')
            record={**target,'id':'pr','metadata_status':'verified','latest_verified':True,'related_identifiers':['arxiv:2107.06829'],
                'evidence_path':'current.json','evidence_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            aliases=verified_record_identifiers(g,[record],project)
            self.assertEqual(len(aliases),1)
            self.assertEqual(aliases[0]['evidence'][0]['evidence_path'],bridge)
            (project/bridge).write_text('{}','utf-8')
            self.assertEqual(verified_record_identifiers(g,[record],project),[])

    def test_existing_resource_alias_requires_hash_and_full_author_identity(self):
        g=graph();target=g['nodes'][2]
        with tempfile.TemporaryDirectory() as directory:
            project=Path(directory);path=project/'proof.json';pdf=project/'existing.pdf'
            path.write_text(json.dumps({'doi':target['doi'],'title':target['title'],'authors':target['authors']}),'utf-8')
            pdf.write_bytes(b'actual file identity is supplied only by the previously validated import')
            sha=hashlib.sha256(pdf.read_bytes()).hexdigest()
            record={**target,'id':'pr','metadata_status':'verified','latest_verified':True,'related_identifiers':['arxiv:2107.06829'],
                'resource_ids':['r'],'evidence_path':'proof.json','evidence_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            resource={'id':'r','state':'ready','path':'existing.pdf','sha256':sha,'metadata':{
                'publication_record_id':'pr','doi':target['doi'],
                'pdf_identity':{'basis':'header_title_authors_identifier','title':target['title'],'authors':target['authors'],'arxiv_id':'2107.06829'},
                'metadata_verification':{'state':'verified','sha256':sha},
                'pdf_version_basis':{'url':'https://arxiv.org/abs/2107.06829v1','retrieved_at':STAMP}}}
            aliases=verified_resource_identifiers(g,[record],[resource],project)
            self.assertEqual(len(aliases),1)
            self.assertEqual(aliases[0]['evidence'][0]['relationship'],'verified_import_pdf_identity_and_formal_record')
            resource['metadata']['pdf_identity']['authors']=['Wei Xu']
            self.assertEqual(verified_resource_identifiers(g,[record],[resource],project),[])
            resource['metadata']['pdf_identity']['authors']=target['authors']
            pdf.write_bytes(b'changed externally')
            self.assertEqual(verified_resource_identifiers(g,[record],[resource],project),[])

    def test_source_gate_still_rejects_missing_url(self):
        with self.assertRaises(DomainError):source({'retrieved_at':STAMP})

    def test_refresh_cannot_merge_punctuation_distinct_dois(self):
        original=graph()['nodes'][2]
        entry={'node_id':'target','citation_count':1,'citation_source':{'url':'https://api.crossref.org/works/10.1234/tar-get','retrieved_at':STAMP,'provider':'Crossref'},
            'source_doi':'10.1234/tar-get','source_title':original['title'],'source_authors':['Wei Xu'],'match_basis':'doi'}
        for basis in ('doi','title_author'):
            entry['match_basis']=basis
            with self.assertRaises(DomainError):validate_citation_refresh({'schema_version':1,'graph_job_id':'j','entries':[entry]}, {'graph_job_id':'j','nodes':[original]})

    def test_load_generates_read_only_view_from_registered_audit(self):
        import backend
        with tempfile.TemporaryDirectory() as directory:
            project=Path(directory);g=graph()
            audit={'rows':[row('middle','10.1234/middle',[{'DOI':'10.1234/tar.get'}])]}
            graph_path=project/'graph.json';audit_path=project/'citation-audit.json'
            graph_path.write_text(json.dumps(g),'utf-8');audit_path.write_text(json.dumps(audit),'utf-8')
            artifacts=[{'path':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for path in (graph_path,audit_path)]
            job={'task':'paper_relationships','status':'partial','context':{'literature_search':{'from_year':2022,'to_year':2026}},
                'result':{'paper_graph_artifact':'graph.json','citation_audit_artifact':'citation-audit.json','artifacts':artifacts}}
            store=types.SimpleNamespace(project=project,rows=lambda sql:[],resources=lambda:[])
            bibliography=types.ModuleType('backend.paper_bibliography');bibliography.rows=lambda store:[]
            enrich=types.ModuleType('backend.research_enrich');enrich.display=lambda store,graph:graph
            before=graph_path.read_bytes()
            with patch.dict(sys.modules,{'backend.paper_bibliography':bibliography,'backend.research_enrich':enrich}),patch.object(backend,'paper_bibliography',bibliography,create=True):
                view=load(store,job)
                self.assertEqual(len(view['edges']),1)
                self.assertEqual(view['network_audit']['references_checked_nodes'],1)
                self.assertEqual(graph_path.read_bytes(),before)
                audit_path.write_text('{}','utf-8')
                with self.assertRaises(DomainError) as error:load(store,job)
                self.assertEqual(error.exception.code,'artifact_hash_mismatch')


if __name__=='__main__':unittest.main()
