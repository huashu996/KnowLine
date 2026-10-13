"""Real failed requests, general refill and honest zero-import result handling."""
import json
from io import BytesIO
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from test_graph_search_options import query, public, policy, load, stub, safety

discovery = load('research_discovery')
results = load('literature_results')
stub('pdf')


class DiscoveryRegression(unittest.TestCase):
    def test_user_requests_preserve_intent_and_separate_controls(self):
        examples = [
            ('查找视觉闭环检测论文，以IEEE期刊和CCF会议为主，10篇', 'visual loop closure detection', 'IEEE', ['CCF']),
            ('关于4D world model 的论文，以CCF会议为主，10篇', '4D world model', None, ['CCF']),
            ('视觉回环检测以IEEE期刊和CCF会议为主，10篇', 'visual loop closure detection', 'IEEE', ['CCF']),
            ('查找视觉SLAM论文，IEEE期刊为主，10篇', 'visual SLAM', 'IEEE', []),
            ('查找蛋白质折叠论文，10篇', '蛋白质折叠', None, []),
        ]
        for request, topic, publisher, groups in examples:
            with self.subTest(request=request):
                plan = query.plan(request)
                self.assertEqual(plan['request'], request)
                self.assertEqual(plan['topic_query'], topic)
                self.assertEqual(plan['preferred_publisher'], publisher)
                self.assertEqual(plan['preferred_venue_groups'], groups)
                self.assertEqual(plan['target_count'], 10)

    def test_topic_ccf_is_not_erased_when_it_is_not_a_venue(self):
        self.assertEqual(query.plan('Credit Card Fraud CCF, 10 papers')['topic_query'], 'Credit Card Fraud CCF')
        self.assertEqual(query.plan('视觉闭环检测')['topic_query'], 'visual loop closure detection')

    def scope(self, request):
        plan = query.plan(request)
        return {'query':request, 'search_plan':plan, 'target_count':10,
                'from_year':2022, 'to_year':2026,
                'source_policy':policy.enable_public_fallback({}),
                'discovery_artifacts':query.revised_names(plan)}

    def test_general_refill_is_not_gated_by_slam_importer(self):
        for request in ['关于4D world model 的论文，以CCF会议为主，10篇', '查找视觉闭环检测论文，10篇', 'protein folding, 10 papers']:
            with self.subTest(request=request), tempfile.TemporaryDirectory() as directory:
                root = Path(directory);output = root/'outputs';output.mkdir()
                scope = self.scope(request)
                job = {'task':'discover_papers','status':'running','context':{'output_dir':'outputs','external_network':'user_requested_search','literature_search':scope}}
                safety.atomic_json(output/query.names(scope)['scholar'], {'status':'browser_only'})
                safety.atomic_json(output/query.public_response_name(scope), {'responses':[{},{}]})
                # Stale failed plan must not poison this normalized retry.
                safety.atomic_json(output/'repository-discovery.json', {'status':'exhausted'})
                store = types.SimpleNamespace(project=root)
                response = {'status':'candidates_found','papers':[{'id':'new'}]}
                with patch.object(public,'discover_repository',return_value=response) as repository:
                    self.assertEqual(discovery.more(store,job),response)
                repository.assert_called_once()
                self.assertGreater(repository.call_args.args[2],0)

    def test_repository_query_works_for_both_topics_and_never_retries(self):
        for request in ['查找视觉闭环检测论文，以IEEE期刊和CCF会议为主，10篇', '关于4D world model 的论文，以CCF会议为主，10篇']:
            with self.subTest(request=request), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);(root/'outputs').mkdir()
                scope=self.scope(request)
                job={'context':{'output_dir':'outputs','literature_search':scope}}
                store=types.SimpleNamespace(project=root)
                calls=[]
                def open_request(request, **kwargs):
                    calls.append(request.full_url)
                    return BytesIO(b'<feed xmlns="http://www.w3.org/2005/Atom"/>')
                import sys
                bibliography=sys.modules[public.__package__+'.paper_bibliography']
                with patch.object(bibliography,'_last',{},create=True), patch.object(public.urllib.request,'build_opener',return_value=types.SimpleNamespace(open=open_request)), patch.object(public.time,'sleep'):
                    self.assertEqual(public.discover_repository(store,job,2)['status'],'no_results')
                    self.assertEqual(public.discover_repository(store,job,2)['status'],'exhausted')
                self.assertEqual(len(calls),1)
                terms=parse_qs(urlsplit(calls[0]).query)['search_query'][0]
                self.assertNotIn('CCF',terms)
                self.assertNotIn('IEEE',terms)
                self.assertNotIn('视觉SLAM',terms)
                self.assertIn('loop closure' if '闭环' in request else 'world',terms)

    def test_generic_journal_query_does_not_force_robotics(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'outputs').mkdir()
            scope=self.scope('protein folding, 10 papers')
            job={'context':{'output_dir':'outputs','literature_search':scope}}
            with patch.object(public,'fetch',return_value={'status':'ok','response':{}}) as fetch:
                public.discover_journals(types.SimpleNamespace(project=root),job,1)
            params=parse_qs(urlsplit(fetch.call_args.args[0]).query)
            self.assertEqual(params['query.bibliographic'],['protein folding'])
            self.assertNotIn('query.container-title',params)


class EmptyResultsRegression(unittest.TestCase):
    def setUp(self):
        self.store=types.SimpleNamespace(groups=lambda:[{'id':'domain','resource_ids':[]}])
        self.job={'task':'discover_papers','context':{'scope':{'domain_id':'domain'},'literature_search':{'target_count':10}}}

    def test_explicit_zero_result_is_failed_not_protocol_error_or_success(self):
        result={'imported_papers':[],'status':'completed','candidate_summary':{'discovered':80},'summary':'All 80 candidates were off topic.'}
        self.assertEqual(results.validate(self.store,self.job,result),'failed')
        self.assertEqual(result['literature_summary']['imported_count'],0)
        self.assertEqual(result['literature_summary']['candidate_count'],80)
        self.assertFalse(result['literature_summary']['registration_report_missing'])
        detail=results.failure_diagnostic({**self.job,'status':'failed','result':result})
        self.assertIn('All 80 candidates',detail['failure_detail'])

    def test_missing_malformed_and_reasonless_receipts_still_fail_validation(self):
        for result in [{},{'imported_papers':{}},{'imported_papers':[None]},{'imported_papers':[{'candidate_id':'one'}]}]:
            with self.subTest(result=result), self.assertRaises(safety.DomainError):
                results.validate(self.store,self.job,result)


if __name__=='__main__':unittest.main()
