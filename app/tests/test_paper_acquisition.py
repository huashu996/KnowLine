"""Publisher-first routing and honest missing-PDF states; no live credentials."""
import asyncio
import copy
import ipaddress
import json
import sys
import tempfile
import threading
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import AsyncMock,patch

APP=Path(__file__).resolve().parents[1]
EXE=None
if '--exe' in sys.argv:
    i=sys.argv.index('--exe');EXE=Path(sys.argv[i+1]);del sys.argv[i:i+2]
sys.path.insert(0,str(APP/'scripts'))
from patch_frozen_modules import module_code
PACKAGE='_paper_acquisition_test'
package=types.ModuleType(PACKAGE);package.__path__=[str(APP/'backend')];sys.modules[PACKAGE]=package
def stub(name,**values):
    mod=types.ModuleType(PACKAGE+'.'+name);mod.__dict__.update(values);sys.modules[mod.__name__]=mod;return mod
def load(name):
    mod=types.ModuleType(PACKAGE+'.'+name);mod.__package__=PACKAGE;sys.modules[mod.__name__]=mod
    code=module_code(EXE,'backend.'+name) if EXE else compile((APP/'backend'/f'{name}.py').read_bytes(),name,'exec')
    exec(code,mod.__dict__);return mod
stub('store',uid=lambda p:p+'_test')
access=load('institutional_access')
canonical_doi=load('paper_bibliography').doi
bib=stub('paper_bibliography',doi=canonical_doi,norm=access.normalize,arxiv=lambda value:value,stamp=access.stamp,rows=lambda s:[s.record],fresh=lambda *a:True,
         save=lambda s,r,d=None:r,outcome=lambda s,i,status,**details:s.outcomes.append({'status':status,**details}),
         get=lambda s,i:s.record,attach=lambda s,r,i,*a:next(v for v in s.resources() if v['id']==i))
enrich_stub=stub('research_enrich',matching=lambda n,rows,*a,**k:rows[0])
stub('paper_abstract',add_local_abstract=lambda s,n,*a:n)
download=load('research_download');official=load('official_copy');imports=load('research_import')
graph=load('graph_fulltext');browser=load('institutional_browser');broker_mod=load('institutional_broker')
finish=load('discovery_finish')
public=load('research_public')
sci_hub=load('sci_hub')
quota=load('research_acquire')
enrich=load('research_enrich')
# Restore matching for the isolated catalog used below.
enrich.matching=enrich_stub.matching
DomainError=access.DomainError

def record():
    return {'id':'p_test','doi':'10.1109/lra.2022.3152830','identity_key':'doi:10.1109/lra.2022.3152830',
            'title':'Faster-LIO: Lightweight Tightly Coupled Lidar-Inertial Odometry Using Parallel Sparse Incremental Voxels',
            'authors':['Chunge Bai','Tao Xiao'],'year':2022,'venue':'IEEE RA-L','source_type':'JournalArticle',
            'publication_status':'published','publisher_url':'https://ieeexplore.ieee.org/document/9710483/',
            'latest_verified':True,'latest_checked_at':access.stamp(),'metadata_status':'verified',
            'domain_ids':[],'resource_ids':[],'related_identifiers':[],'evidence':[]}

def feed(title,authors,doi='',key='2302.04031v3'):
    ns='{http://www.w3.org/2005/Atom}'
    root=ET.Element(ns+'feed');entry=ET.SubElement(root,ns+'entry')
    ET.SubElement(entry,ns+'id').text='http://arxiv.org/abs/'+key
    ET.SubElement(entry,ns+'updated').text='2020-05-30T11:18:01Z'
    ET.SubElement(entry,ns+'published').text='2019-04-13T17:50:28Z'
    ET.SubElement(entry,ns+'title').text=title
    for author in authors:ET.SubElement(ET.SubElement(entry,ns+'author'),ns+'name').text=author
    if doi:ET.SubElement(entry,'{http://arxiv.org/schemas/atom}doi').text=doi
    return ET.tostring(root)

class VersionTests(unittest.IsolatedAsyncioTestCase):
    async def test_verified_exact_doi_index_can_locate_unlisted_university_domain(self):
        r=record();url='https://repository.university-example.nl/paper.pdf'
        payload={'status':'ok','retrieved_at':access.stamp(),'response_sha256':'test','response':{
            'doi':'https://doi.org/'+r['doi'],'title':r['title'],
            'authorships':[{'author':{'display_name':a}} for a in r['authors']],
            'locations':[{'is_oa':True,'pdf_url':url,'version':'acceptedVersion'}]}}
        with patch.object(public,'fetch',return_value=payload):updated,source=await download.locate_openalex(r)
        self.assertEqual(source['access_url'],url)
        self.assertTrue(download.permitted_public_host('repository.university-example.nl',updated,url))
        self.assertFalse(download.permitted_public_host('repository.university-example.nl',r,url))
        self.assertNotIn('official_pdf_url',source['pdf_identity'])
        self.assertEqual(updated['public_copy_bindings'][0]['match_basis'],'exact_doi_index_location_candidate_only')
    async def test_index_mismatched_doi_does_not_authorize_unlisted_source(self):
        r=record();payload={'status':'ok','retrieved_at':access.stamp(),'response':{'doi':'https://doi.org/10.1109/wrong','title':r['title'],'authorships':[{'author':{'display_name':a}} for a in r['authors']],'locations':[{'is_oa':True,'pdf_url':'https://repository.example.nl/paper.pdf'}]}}
        with patch.object(public,'fetch',return_value=payload):
            with self.assertRaises(DomainError) as caught:await download.locate_openalex(r)
        self.assertEqual(caught.exception.code,'public_index_identity_mismatch')
    async def locate(self,r,title,authors,doi=''):
        with patch.object(bib,'fetch',AsyncMock(return_value=feed(title,authors,doi)),create=True):
            return await download.locate_public(r)
    async def test_explicit_repository_doi_can_bridge_author_list_change(self):
        r=record();r['authors']=['Chunge Bai','Tao Xiao','New Author']
        updated,source=await self.locate(r,'Older manuscript title',['Chunge Bai','Tao Xiao'],r['doi'])
        self.assertIn('arxiv:2302.04031',updated['related_identifiers'])
        self.assertEqual(updated['title'],r['title'])
        self.assertEqual(source['pdf_identity']['title'],'Older manuscript title')
        self.assertEqual(source['pdf_version'],'preprint')
    async def test_similar_preprint_is_candidate_not_automatic_merge(self):
        r=record()
        with self.assertRaises(DomainError) as caught:
            await self.locate(r,'FR-LIO: '+r['title'].split(':',1)[1],r['authors'][:1])
        self.assertEqual(caught.exception.code,'public_repository_candidate_needs_review')
        self.assertTrue(caught.exception.params['candidates'])
        self.assertFalse(r['related_identifiers'])
    async def test_conflicting_doi_cannot_be_candidate_or_merge(self):
        r=record()
        with self.assertRaises(DomainError) as caught:await self.locate(r,r['title'],r['authors'],'10.1109/wrong')
        self.assertEqual(caught.exception.code,'public_repository_no_identity_match')
        self.assertFalse(caught.exception.params['candidates'])
    async def test_explicit_doi_with_unrelated_authors_rejected(self):
        r=record()
        with self.assertRaises(DomainError):await self.locate(r,r['title'],['Unrelated Person'],r['doi'])
    async def test_declared_doi_accepts_montiel_initials_without_overwriting_citation(self):
        r=record();r['title']='Direct Sparse Mapping';r['doi']='10.1109/tro.2020.2991614'
        r['authors']=['Jon Zubizarreta','Iker Aguinaga','Jose Maria Martinez Montiel']
        updated,source=await self.locate(r,r['title'],['Jon Zubizarreta','Iker Aguinaga','J. M. M. Montiel'],r['doi'])
        self.assertEqual(updated['authors'],r['authors'])
        self.assertEqual(source['pdf_identity']['authors'][-1],'J. M. M. Montiel')
    async def test_initials_without_declared_doi_are_not_automatic_publication_bridge(self):
        r=record();r['authors']=['Chunge Bai','Tao Xiao','Jose Maria Martinez Montiel']
        with self.assertRaises(DomainError) as caught:
            await self.locate(r,r['title'],['Chunge Bai','Tao Xiao','J. M. M. Montiel'])
        self.assertEqual(caught.exception.code,'public_repository_candidate_needs_review')
    async def test_exact_title_and_all_authors_bridge_still_works(self):
        r=record();updated,_=await self.locate(r,r['title'],r['authors'])
        self.assertIn('arxiv:2302.04031',updated['related_identifiers'])
    async def test_index_http_failure_is_preserved(self):
        with patch.object(public,'fetch',return_value={'status':'rate_limited','http_status':429,'retry_after_seconds':60}):
            for locator in (download.locate_openalex,download.locate_index):
                with self.assertRaises(DomainError) as caught:await locator(record())
                self.assertEqual(caught.exception.params['http_status'],429)
                self.assertEqual(caught.exception.params['retry_after_seconds'],60)

class BibliographyInitialsTests(unittest.IsolatedAsyncioTestCase):
    def test_effective_cc_license_marks_publisher_pdf_open(self):
        work={'DOI':'10.1234/test','type':'journal-article','title':['Paper'],'author':[{'given':'Alice','family':'Smith'}],
              'published':{'date-parts':[[2020]]},'container-title':['Journal'],
              'license':[{'URL':'https://creativecommons.org/licenses/by/4.0/','content-version':'vor','start':{'date-time':'2020-01-01T00:00:00Z'}}],
              'link':[{'URL':'https://publisher.example.org/paper.pdf','content-type':'application/pdf','content-version':'vor'}]}
        result=self.real_bibliography().crossref(work,access.stamp())
        self.assertTrue(result['open_access_verified']);self.assertTrue(result['public_download_sources'][0]['public_oa'])
    def test_future_or_non_oa_license_does_not_authorize_anonymous_pdf(self):
        work={'DOI':'10.1234/test','type':'journal-article','title':['Paper'],'author':[{'given':'Alice','family':'Smith'}],
              'published':{'date-parts':[[2020]]},'container-title':['Journal'],
              'license':[{'URL':'https://creativecommons.org/licenses/by/4.0/','content-version':'vor','start':{'date-time':'2200-01-01T00:00:00Z'}},
                         {'URL':'https://publisher.example.org/standard-license','content-version':'vor'}],
              'link':[{'URL':'https://publisher.example.org/paper.pdf','content-type':'application/pdf','content-version':'vor'}]}
        result=self.real_bibliography().crossref(work,access.stamp())
        self.assertFalse(result['open_access_verified']);self.assertFalse(result['public_download_sources'][0]['public_oa'])
    def test_accepted_manuscript_license_does_not_open_published_pdf(self):
        work={'DOI':'10.1234/test','type':'journal-article','title':['Paper'],'author':[{'given':'Alice','family':'Smith'}],
              'published':{'date-parts':[[2020]]},'container-title':['Journal'],
              'license':[{'URL':'https://creativecommons.org/licenses/by/4.0/','content-version':'am'}],
              'link':[{'URL':'https://publisher.example.org/vor.pdf','content-type':'application/pdf','content-version':'vor'},
                      {'URL':'https://publisher.example.org/am.pdf','content-type':'application/pdf','content-version':'am'}]}
        result=self.real_bibliography().crossref(work,access.stamp())
        self.assertFalse(result['open_access_verified'])
        self.assertFalse(result['public_download_sources'][0]['public_oa']);self.assertTrue(result['public_download_sources'][1]['public_oa'])
    def test_exact_doi_registered_pdf_links_are_retained_as_candidates(self):
        module=self.real_bibliography();r=record()
        work={'DOI':r['doi'],'type':'journal-article','title':[r['title']],
              'author':[{'given':'Chunge','family':'Bai'},{'given':'Tao','family':'Xiao'}],
              'published':{'date-parts':[[2022]]},'container-title':['IEEE RA-L'],
              'link':[{'URL':'https://publisher.example.org/paper.pdf','content-type':'application/pdf','content-version':'vor'},
                      {'URL':'https://publisher.example.org/paper.pdf?token=secret','content-type':'application/pdf'}]}
        result=module.crossref(work,access.stamp())
        self.assertEqual(len(result['public_download_sources']),1)
        self.assertEqual(result['public_download_sources'][0]['pdf_version'],'published')
        self.assertEqual(result['public_copy_bindings'][0]['match_basis'],'registered_doi_pdf_link_candidate_only')
        self.assertFalse(result['public_download_sources'][0]['public_oa'])
        self.assertFalse(result['open_access_verified'])
        self.assertNotIn('official_pdf_url',result['public_download_sources'][0]['pdf_identity'])
    def test_metadata_attachment_keeps_successful_acquisition_trace(self):
        module=self.real_bibliography();r=record();r.update(revision=1,pdf_status={'status':'acquired','full_text_attempts':[{'provider':'arXiv','status':'located'}],'full_text_policy':{'version':'v3'}})
        store=types.SimpleNamespace(db=types.SimpleNamespace(execute=lambda *a:None),event=lambda *a:None)
        with patch.object(module,'get',return_value=r):module.outcome(store,r['id'],'acquired',resource_id='r1')
        self.assertEqual(r['pdf_status']['full_text_attempts'][0]['provider'],'arXiv')
        self.assertEqual(r['pdf_status']['full_text_policy']['version'],'v3')
    def test_attachment_clears_old_failed_reason_instead_of_reporting_failure_for_saved_pdf(self):
        module=self.real_bibliography();r=record();r.update(revision=1,pdf_status={'status':'search_incomplete','unavailable_reason':'old_failure','full_text_attempts':[{'reason':'old_failure'}]})
        store=types.SimpleNamespace(db=types.SimpleNamespace(execute=lambda *a:None),event=lambda *a:None)
        with patch.object(module,'get',return_value=r):module.outcome(store,r['id'],'acquired',resource_id='r1')
        self.assertNotIn('unavailable_reason',r['pdf_status']);self.assertNotIn('full_text_attempts',r['pdf_status'])
    def real_bibliography(self):
        module=types.ModuleType(PACKAGE+'.bibliography_initials');module.__package__=PACKAGE
        code=module_code(EXE,'backend.paper_bibliography') if EXE else compile((APP/'backend/paper_bibliography.py').read_bytes(),'paper_bibliography','exec')
        with patch.dict(sys.modules,{'httpx':types.ModuleType('httpx')}):exec(code,module.__dict__)
        return module
    async def test_arxiv_declared_formal_doi_uses_initials_and_preserves_final_author_names(self):
        module=self.real_bibliography();r=record();r.update(title='Direct Sparse Mapping',authors=['Jon Zubizarreta','Iker Aguinaga','Jose Maria Martinez Montiel'])
        work={'DOI':r['doi'],'type':'journal-article','title':[r['title']],
              'author':[{'given':'Jon','family':'Zubizarreta'},{'given':'Iker','family':'Aguinaga'},{'given':'Jose Maria Martinez','family':'Montiel'}],
              'published':{'date-parts':[[2020]]},'container-title':['IEEE Transactions on Robotics']}
        raw=feed(r['title'],['Jon Zubizarreta','Iker Aguinaga','J. M. M. Montiel'],r['doi'])
        async def fetch(url):return raw if 'arxiv.org' in url else json.dumps({'message':work}).encode()
        with patch.object(module,'fetch',fetch):result=await module.resolve(arxiv_id='2302.04031')
        self.assertEqual(result['publication_status'],'published');self.assertEqual(result['authors'],r['authors'])
        self.assertIn('arxiv:2302.04031',result['related_identifiers'])
    def test_initials_do_not_accept_different_given_name_or_surname(self):
        module=self.real_bibliography()
        self.assertFalse(module.declared_author_identity(['Jon Zubizarreta'],['Jane Zubizarreta']))
        self.assertFalse(module.declared_author_identity(['Jose Maria Martinez Montiel'],['J. M. M. Somebody']))

class OfficialTests(unittest.IsolatedAsyncioTestCase):
    async def test_doi_route_is_resolved_before_account_selection(self):
        import io
        r=record();r['publisher_url']='https://doi.org/'+r['doi']
        response=io.BytesIO(b'');response.url='https://ieeexplore.ieee.org/document/9710483/'
        with patch.object(download,'public_destination',return_value=True),patch.object(download,'public_opener',return_value=types.SimpleNamespace(open=lambda *a,**k:response)):
            updated=await official.resolve_publisher_url(r)
        self.assertEqual(updated['publisher_url'],response.url);self.assertEqual(updated['doi'],r['doi'])
    def test_legacy_doi_redirect_uses_https_and_keeps_destination_check(self):
        import urllib.request
        redirect=official.PublisherRedirect();request=urllib.request.Request('https://doi.org/10.1109/example')
        with patch.object(official,'public_destination',return_value=True):
            result=redirect.redirect_request(request,None,302,'Found',{},'http://publisher.example.org/article')
        self.assertEqual(result.full_url,'https://publisher.example.org/article')
        with patch.object(official,'public_destination',return_value=False):
            with self.assertRaises(DomainError):redirect.redirect_request(request,None,302,'Found',{},'http://publisher.example.org/article')
    async def test_publisher_metadata_binds_localized_page_and_pdf_without_printed_doi(self):
        r=record();r['open_access_verified']=True;page_url='https://www.jstage.jst.go.jp/article/example/_article';pdf_url=page_url.replace('_article','_pdf')
        page={'url':page_url,'text':'Localized article title','html':'<meta name="citation_doi" content="'+r['doi']+'"><meta name="citation_pdf_url" content="'+pdf_url+'">',
              'links':[],'original_links':[],'retrieved_at':access.stamp(),'response_sha256':'test'}
        with patch.object(official,'fetch_page',return_value=page):updated,source=await official.locate_publisher(r)
        self.assertEqual(source['pdf_identity']['official_pdf_url'],pdf_url)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);store=types.SimpleNamespace(project=root,state=root/'resource/.knowledge')
            store.state.mkdir(parents=True)
            updated=official.persist_sources(store,updated)
            self.assertNotIn('pending_public_source_proofs',updated)
            self.assertTrue(official.binding_valid(updated['public_copy_bindings'][0],source['pdf_identity'],updated,root/'resource/incoming/paper.pdf'))
            self.assertEqual(source['pdf_version'],'unknown')
    async def test_conflicting_publisher_metadata_doi_does_not_supply_binding(self):
        page={'url':'https://www.jstage.jst.go.jp/article/example','text':record()['title'],'html':'<meta name="citation_doi" content="10.1109/wrong">','links':[]}
        with patch.object(official,'fetch_page',return_value=page):
            with self.assertRaises(DomainError) as caught:await official.locate_publisher({**record(),'open_access_verified':True})
        self.assertEqual(caught.exception.code,'publisher_page_identity_conflict')
    def test_stable_publisher_article_ids_survive_download_and_provenance(self):
        url='https://www.hanspub.org/journal/paperinformation?paperid=61833'
        self.assertEqual(access.safe_url(url),url)
        self.assertEqual(access.safe_url(url.replace('paperid','paperID')),url.replace('paperid','paperID'))
        for invalid in (url+'&token=secret',url.replace('61833','token-secret'),url.replace('61833','x'*80)):
            with self.assertRaises(DomainError):access.safe_url(invalid)
    def test_compressed_publisher_html_is_decoded_before_identity_check(self):
        import gzip,io
        r=record();url='https://www.hanspub.org/journal/article'
        raw=('<html>'+r['title']+' '+r['doi']+'</html>').encode()
        response=io.BytesIO(gzip.compress(raw));response.url=url;response.headers={'Content-Encoding':'gzip'}
        with patch.object(download,'public_destination',return_value=True),patch.object(download,'public_opener',return_value=types.SimpleNamespace(open=lambda *a,**k:response)):
            page=official.fetch_page(url)
        self.assertIn(r['title'],page['text']);self.assertIn(r['doi'],page['html'])
    def test_compressed_source_still_enforces_decoded_size_limit(self):
        import gzip,io
        response=io.BytesIO(gzip.compress(b'a'*(2*1024*1024+1)));response.url='https://www.hanspub.org/article';response.headers={'Content-Encoding':'gzip'}
        with patch.object(download,'public_destination',return_value=True),patch.object(download,'public_opener',return_value=types.SimpleNamespace(open=lambda *a,**k:response)):
            with self.assertRaises(DomainError) as caught:official.fetch_page(response.url)
        self.assertEqual(caught.exception.code,'official_source_page_size_limit')
    async def test_exact_paper_github_search_follows_arxiv_pdf_without_suffix(self):
        r=record();page={'url':'https://github.com/new-author/paper','text':r['title'],'html':r['doi'],
                         'links':['https://arxiv.org/pdf/2302.04031'], 'original_links':['https://arxiv.org/pdf/2302.04031'],
                         'retrieved_at':access.stamp(),'response_sha256':'test'}
        source={'access_url':'https://arxiv.org/pdf/2302.04031v3','public_oa':True}
        with patch.object(public,'fetch',return_value={'status':'ok','response':{'items':[{'full_name':'new-author/paper','fork':False}]}}) as search,patch.object(official,'fetch_page',return_value=page),patch.object(download,'locate_public',AsyncMock(return_value=(r,source))) as locate:
            updated,result=await official.locate_github(r)
        self.assertIn('in%3Areadme',search.call_args.args[0]);self.assertEqual(search.call_count,1)
        locate.assert_awaited_once_with(unittest.mock.ANY,identifier='2302.04031')
        self.assertEqual(result,source)
    async def test_found_repository_scoped_to_paper_and_pdf_still_requires_doi(self):
        r=record();page={'url':'https://github.com/new-author/paper','text':r['title'],'html':r['doi'],
                         'links':['https://github.com/new-author/paper/blob/main/paper.pdf'],
                         'original_links':['https://github.com/new-author/paper/blob/main/paper.pdf'],
                         'retrieved_at':access.stamp(),'response_sha256':'test'}
        with patch.object(public,'fetch',return_value={'status':'ok','response':{'items':[{'full_name':'new-author/paper'}]}}),patch.object(official,'fetch_page',return_value=page):
            updated,source=await official.locate_github(r)
        self.assertTrue(download.permitted_public_host('raw.githubusercontent.com',updated,source['access_url']))
        self.assertFalse(download.permitted_public_host('raw.githubusercontent.com',r,source['access_url']))
        self.assertEqual(source['pdf_identity']['doi'],r['doi']);self.assertNotIn('official_pdf_url',source['pdf_identity'])
    async def test_publisher_pdf_subdomain_without_login_or_index(self):
        r=record();r['open_access_verified']=True;r['publisher_url']='https://doi.org/'+r['doi']
        page={'url':'https://www.hanspub.org/journal/paperinformation?paperid=61833','text':r['title'],
              'html':r['doi']+'<meta name="citation_pdf_url" content="https://pdf.hanspub.org/paper.pdf">',
              'links':[], 'retrieved_at':access.stamp(),'response_sha256':'test'}
        with patch.object(official,'fetch_page',return_value=page):updated,source=await official.locate_publisher(r)
        self.assertEqual(source['access_url'],'https://pdf.hanspub.org/paper.pdf')
        self.assertTrue(download.permitted_public_host('pdf.hanspub.org',updated,source['access_url']))
        self.assertNotIn('official_pdf_url',source['pdf_identity'])
    async def test_github_search_limit_is_not_no_pdf(self):
        with patch.object(public,'fetch',return_value={'status':'rate_limited','http_status':429,'request_sent':False,'retry_after_seconds':60}):
            with self.assertRaises(DomainError) as caught:await official.locate_github(record())
        self.assertEqual(caught.exception.code,'github_search_unavailable');self.assertFalse(caught.exception.params['request_sent'])
    def test_github_transfer_is_labeled_repository_not_publisher(self):
        import io,tempfile
        r=record();url='https://raw.githubusercontent.com/gaoxiang12/faster-lio/main/doc/faster-lio.pdf'
        response=io.BytesIO(b'%PDF-1.4 test author-copy transfer');response.url=url
        source={'publisher_url':'https://github.com/gaoxiang12/faster-lio','access_url':url,'public_oa':True,'pdf_version':'unknown'}
        with tempfile.TemporaryDirectory() as temp,patch.object(download,'public_destination',return_value=True),patch.object(download,'public_opener',return_value=types.SimpleNamespace(open=lambda *a,**k:response)),patch.object(download,'validate_pdf') as validate:
            file,metadata=download.fetch_pdf(types.SimpleNamespace(root=Path(temp)),r,r,source,5)
            self.assertTrue(file.is_file())
            self.assertEqual(metadata['access_method'],'public_repository')
            self.assertEqual(metadata['pdf_version'],'unknown')
            validate.assert_called_once()
    async def test_author_page_discovers_canonical_pdf_but_does_not_prove_identity(self):
        r=record();url='https://raw.githubusercontent.com/gaoxiang12/faster-lio/main/doc/faster-lio.pdf'
        page={'text':r['title'],'html':'','links':[url,url],'retrieved_at':access.stamp(),'response_sha256':'test'}
        with patch.object(official,'fetch_page',return_value=page) as fetch:
            updated,source=await official.discover(r)
        self.assertEqual(fetch.call_count,1)
        self.assertEqual(source['access_url'],url)
        self.assertNotIn('official_pdf_url',source['pdf_identity'])
        self.assertEqual(source['pdf_version'],'unknown')
        self.assertNotIn('public_copy_bindings',updated)
    async def test_external_unapproved_pdf_is_not_discovered(self):
        page={'text':record()['title'],'html':'','links':['https://unapproved.example/wrong.pdf'],'retrieved_at':access.stamp(),'response_sha256':'test'}
        with patch.object(official,'fetch_page',return_value=page):
            with self.assertRaises(DomainError) as caught:await official.discover(record())
        self.assertEqual(caught.exception.code,'official_source_no_pdf')
    def test_canonical_github_blob(self):
        self.assertEqual(official.canonical_link('https://github.com/gaoxiang12/faster-lio/blob/main/doc/faster-lio.pdf'),
                         'https://raw.githubusercontent.com/gaoxiang12/faster-lio/main/doc/faster-lio.pdf')

class PublisherRequestTests(unittest.TestCase):
    def setUp(self):
        self.r=record()
        self.body={**imports.publisher_source(self.r),**{k:self.r[k] for k in ('doi','title','authors')},
                   'citation_record':self.r,'identity_confirmed':True}
        self.config={'method':'publisher','allowed_origins':['https://ieeexplore.ieee.org/']}
    def test_original_publisher_unknown_version_is_not_a_fallback(self):
        target=access.paper_request(self.body,self.config)
        self.assertEqual(target['pdf_version'],'unknown')
        self.assertEqual(target['fallback_reason'],'')
        self.assertEqual(target['access_url'],self.r['publisher_url'])
    def test_original_route_does_not_claim_published_before_page_evidence(self):
        target=access.paper_request(self.body,self.config)
        data={'doi':self.r['doi'],'pdf':'https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=9710483'}
        self.assertTrue(browser.publisher_version(target,data,self.r['publisher_url']))
        self.assertEqual(target['pdf_version'],'published')
        self.assertEqual(target['citation_record']['doi'],self.r['doi'])
    def test_wrong_page_or_doi_cannot_promote_unknown_version(self):
        for url,doi in [('https://ieeexplore.ieee.org/document/1/',self.r['doi']),
                        (self.r['publisher_url'],'10.1109/unrelated')]:
            target=access.paper_request(self.body,self.config)
            self.assertFalse(browser.publisher_version(target,{'doi':doi,'pdf':'https://ieeexplore.ieee.org/a.pdf'},url))
            self.assertEqual(target['pdf_version'],'unknown')
    def test_unverified_and_public_unknown_copies_still_require_fallback_reason(self):
        unverified=copy.deepcopy(self.body);unverified['citation_record']['latest_verified']=False
        public_body={**self.body,'public_oa':True}
        for body,public in [(unverified,False),(public_body,True)]:
            with self.assertRaisesRegex(DomainError,'institution_fallback_reason_required'):
                access.paper_request(body,self.config,public_copy=public)
    def test_preprint_and_accepted_versions_still_require_fallback_reason(self):
        for version in ['preprint','accepted_manuscript']:
            with self.assertRaisesRegex(DomainError,'institution_fallback_reason_required'):
                access.paper_request({**self.body,'pdf_version':version},self.config)
    def test_original_route_does_not_bypass_identity_consent_or_origin_checks(self):
        for patch_value,code in [({'identity_confirmed':False},'institution_confirmation_required'),
                                 ({'download_permitted':False},'institution_confirmation_required'),
                                 ({'access_url':'https://other.example/a.pdf'},'institution_scope_invalid')]:
            with self.assertRaisesRegex(DomainError,code):access.paper_request({**self.body,**patch_value},self.config)

class LoginNetworkTests(unittest.TestCase):
    def dns(self,address):
        return [(2 if ipaddress.ip_address(address).version==4 else 10,1,6,'',(address,443))]
    def allowed(self,host,address,**options):
        with patch.object(access.socket,'getaddrinfo',return_value=self.dns(address)):
            return access.public_destination('https://'+host+'/login',{host},**options)
    def test_confirmed_login_supports_different_institutions_and_non_edu_domains(self):
        # Examples intentionally cover unrelated names and TLDs; no school preset.
        for host in ['idp.example.edu.cn','accounts.example.ac.uk','adfs.example.edu',
                     'federation.example.org','library-proxy.example.net','portal.example.de']:
            for address in ['10.64.93.247','172.20.1.5','192.168.31.9','93.184.215.14']:
                with self.subTest(host=host,address=address):
                    self.assertTrue(self.allowed(host,address,authentication=True))
    def test_private_login_exception_never_applies_to_pdf_or_metadata_requests(self):
        for address in ['10.64.93.247','172.20.1.5','192.168.31.9']:
            self.assertFalse(self.allowed('idp.example.edu.cn',address))
    def test_login_still_requires_exact_approved_host(self):
        with patch.object(access.socket,'getaddrinfo',return_value=self.dns('10.1.1.1')) as dns:
            self.assertFalse(access.public_destination('https://other.example.edu/login',{'idp.example.edu'},authentication=True))
            dns.assert_not_called()
    def test_login_never_accepts_loopback_linklocal_or_unusable_dns(self):
        for address in ['127.0.0.1','169.254.169.254','0.0.0.0','224.0.0.1','::1','fc00::1','fe80::1','::ffff:10.1.1.1']:
            with self.subTest(address=address):self.assertFalse(self.allowed('login.example.org',address,authentication=True))
        for host in ['127.0.0.1','10.1.1.1','localhost','service.local','service.localhost']:
            self.assertFalse(self.allowed(host,'10.1.1.1',authentication=True))
    def test_login_keeps_tls_userinfo_and_port_checks(self):
        with patch.object(access.socket,'getaddrinfo',return_value=self.dns('10.1.1.1')):
            for url in ['http://idp.example.org/','https://user:pass@idp.example.org/','https://idp.example.org:8443/']:
                self.assertFalse(access.public_destination(url,{'idp.example.org'},authentication=True))
    def test_fake_ip_requires_existing_explicit_network_setting(self):
        self.assertFalse(self.allowed('login.example.org','198.18.1.10',authentication=True))
        self.assertTrue(self.allowed('login.example.org','198.18.1.10',allow_translated=True))
    def test_mixed_or_failed_dns_does_not_grant_access(self):
        with patch.object(access.socket,'getaddrinfo',return_value=self.dns('10.1.1.1')+self.dns('127.0.0.1')):
            self.assertFalse(access.public_destination('https://login.example.org/',{'login.example.org'},authentication=True))
        with patch.object(access.socket,'getaddrinfo',side_effect=OSError('dns failure')):
            self.assertFalse(access.public_destination('https://login.example.org/',{'login.example.org'},authentication=True))
    def test_private_redirect_requires_human_authentication_approval(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(access.socket,'getaddrinfo',return_value=self.dns('10.1.1.1')):
            root=Path(temp);config={'allowed_origins':['https://publisher.example.org/']}
            for purpose in ['authentication_navigation','paper_navigation','challenge_resource']:
                approval={'id':'confirmation','origin':'https://federation.example.org/','purpose':purpose}
                (root/'config.json').write_text(json.dumps(config),encoding='utf-8')
                (root/'status.json').write_text(json.dumps({'approval':approval}),encoding='utf-8')
                for body in [{'confirmed':False,'approval_id':'confirmation'},{'confirmed':True,'approval_id':'wrong'}]:
                    with self.assertRaisesRegex(DomainError,'institution_confirmation_required'):access.grant_site(root,body)
                if purpose=='authentication_navigation':
                    access.grant_site(root,{'confirmed':True,'approval_id':'confirmation'})
                    saved=json.loads((root/'config.json').read_text('utf-8'))
                    self.assertIn(approval['origin'],saved['allowed_origins'])
                else:
                    with self.assertRaisesRegex(DomainError,'institution_destination_unsafe'):
                        access.grant_site(root,{'confirmed':True,'approval_id':'confirmation'})

def nested_code(code,name):
    for value in code.co_consts:
        if isinstance(value,types.CodeType):
            if value.co_name==name:return value
            found=nested_code(value,name)
            if found:return found

def callback_cells(values):
    def cell(value):return (lambda:value).__closure__[0]
    return {name:cell(value) for name,value in values.items()}

def native_callback(name,cells):
    # Execute the shipped callback itself with harmless WebView/window doubles.
    # This catches closure bugs as well as source-vs-frozen behavior differences.
    code=nested_code(browser.run.__code__,name)
    for name in code.co_freevars:
        if name not in cells:cells[name]=callback_cells({name:None})[name]
    return types.FunctionType(code,browser.__dict__,closure=tuple(cells[n] for n in code.co_freevars))

class LoginRecoveryTests(unittest.TestCase):
    def test_interactive_sso_redirects_and_dependencies_need_no_site_confirmation(self):
        hosts={'publisher.example.org'}
        with patch.object(access.socket,'getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443))]):
            for uri in ['https://identity.institution.net/sso?SAMLRequest=opaque',
                        'https://identity.institution.net/callback#token=ephemeral',
                        'https://cdn.institution.net/login.js',
                        'https://example.token.awswaf.com/challenge.js']:
                with self.subTest(uri=uri):
                    self.assertTrue(browser.browser_destination(uri,hosts,interactive_login=True))
                    self.assertFalse(browser.browser_destination(uri,hosts,interactive_login=False))
                    self.assertFalse(browser.browser_destination(uri,hosts,interactive_login=True,target_active=True))
        self.assertEqual(hosts,{'publisher.example.org'})
    def test_automatic_login_redirect_keeps_network_and_scheme_boundaries(self):
        hosts={'publisher.example.org'}
        for address in ['127.0.0.1','169.254.169.254','10.2.3.4','192.168.1.2','::1']:
            with patch.object(access.socket,'getaddrinfo',return_value=[(2,1,6,'',(address,443))]):
                self.assertFalse(browser.browser_destination('https://new.example.org/sso',hosts,interactive_login=True))
        with patch.object(access.socket,'getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443))]):
            for uri in ['http://new.example.org/','file:///C:/file','https://user:secret@new.example.org/',
                        'https://new.example.org:8443/','https://[invalid/']:
                self.assertFalse(browser.browser_destination(uri,hosts,interactive_login=True))
        with patch.object(access.socket,'getaddrinfo',return_value=[(2,1,6,'',('10.2.3.4',443))]):
            self.assertTrue(browser.browser_destination('https://publisher.example.org/login',hosts,interactive_login=True))
            self.assertFalse(browser.browser_destination('https://publisher.example.org/paper',hosts,target_active=True))
    def test_native_navigation_frames_popup_and_resources_follow_human_login(self):
        calls=[];hosts={'publisher.example.org'}
        core=types.SimpleNamespace(Navigate=lambda uri:calls.append('navigate'),Environment=types.SimpleNamespace(
            CreateWebResourceResponse=lambda *args:calls.append('blocked-resource')))
        cells=callback_cells({'interactive_login':True,'target':None,'hosts':hosts,'config':{},
            'blocked':lambda uri:calls.append('blocked-navigation'),'browser':types.SimpleNamespace(CoreWebView2=core),
            'blocked_challenge':lambda uri:calls.append('blocked-challenge')})
        cells.update(callback_cells({'allowed':native_callback('allowed',cells)}))
        with patch.object(access.socket,'getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443))]):
            uri='https://identity.institution.net/sso?SAMLRequest=ephemeral'
            nav=types.SimpleNamespace(Uri=uri,NavigationId=10,Cancel=False)
            native_callback('navigation',cells)(None,nav)
            self.assertFalse(nav.Cancel)
            frame=types.SimpleNamespace(Uri=uri,Cancel=False)
            native_callback('frame_navigation',cells)(None,frame)
            self.assertFalse(frame.Cancel)
            popup=types.SimpleNamespace(Uri=uri,Handled=False)
            native_callback('new_window',cells)(None,popup)
            self.assertTrue(popup.Handled);self.assertEqual(calls,['navigate'])
            resource=types.SimpleNamespace(Request=types.SimpleNamespace(Uri='https://cdn.institution.net/login.js'),Response=None)
            native_callback('resource_requested',cells)(None,resource)
            self.assertIsNone(resource.Response);self.assertEqual(calls,['navigate'])
            cells['target'].cell_contents={'id':'paper'}
            nav.Cancel=False;native_callback('navigation',cells)(None,nav)
            self.assertTrue(nav.Cancel);self.assertIn('blocked-navigation',calls)
            cells['target'].cell_contents=None;cells['interactive_login'].cell_contents=False
            frame.Cancel=False;native_callback('frame_navigation',cells)(None,frame)
            self.assertTrue(frame.Cancel)
        self.assertEqual(hosts,{'publisher.example.org'})
    def test_connect_reopens_failed_or_blank_page_without_interrupting_work(self):
        for reason in browser.LOGIN_RECOVERY_REASONS:
            self.assertTrue(browser.reopen_login_entry('https://login.example.org/failed',reason))
            self.assertFalse(browser.reopen_login_entry('https://login.example.org/failed',reason,True))
        self.assertTrue(browser.reopen_login_entry('about:blank','browser_ready'))
        for reason in ['sign_in_required','challenge_requires_user','authenticated_session_ready','official_site_confirmation_required']:
            self.assertFalse(browser.reopen_login_entry('https://login.example.org/',reason))
    def test_real_open_entry_reloads_same_url_and_resets_stale_failure(self):
        calls=[];core=types.SimpleNamespace(Source='https://portal.example.org/',Reload=lambda:calls.append('reload'),Navigate=lambda u:calls.append(u))
        cells=callback_cells({'opening_at':None,'login_entry':core.Source,'challenge_blocked':True,'blocked_navigation':{'old':True},
            'page_loaded':True,'readiness_due':1,'readiness_task':'old','confirmation_button':types.SimpleNamespace(Visible=True),
            'browser':types.SimpleNamespace(CoreWebView2=core),'stop_download':lambda:calls.append('stop'),
            'explain':lambda text:None,'en':False,'status':lambda *a,**k:calls.append(a)})
        callback=native_callback('open_entry',cells);callback(None)
        self.assertIn('reload',calls);self.assertIn(('awaiting_login','user_login_required'),calls)
        self.assertFalse(cells['challenge_blocked'].cell_contents);self.assertIsNone(cells['blocked_navigation'].cell_contents)
        self.assertIsNone(cells['readiness_task'].cell_contents)
        callback('https://different.example.org/')
        self.assertEqual(calls[-1],'https://different.example.org/')
    def test_real_tick_reports_loading_timeout_and_still_consumes_reconnect(self):
        calls=[]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'command.json').write_text(json.dumps({'id':'retry','action':'show'}),encoding='utf-8')
            cells=callback_cells({'ready':True,'opening_at':browser.time.monotonic()-31,'page_loaded':False,'target':None,
                'root':root,'status':lambda *a,**k:calls.append(a),'explain':lambda text:None,'en':False,'show':lambda:calls.append('show')})
            native_callback('tick',cells)(None,None)
            self.assertIn(('awaiting_login','login_open_timeout'),calls);self.assertIn('show',calls)
            self.assertIsNone(cells['opening_at'].cell_contents)
            self.assertNotIn(('awaiting_test','browser_action_failed'),calls)
    def test_real_show_recovers_failed_page_and_preserves_login_in_progress(self):
        calls=[];form=types.SimpleNamespace(Opacity=0,ShowInTaskbar=False,WindowState='normal',Show=lambda:calls.append('show'),Activate=lambda:None)
        cells=callback_cells({'launch':{},'form':form,'F':types.SimpleNamespace(FormWindowState=types.SimpleNamespace(Minimized='minimized',Normal='normal')),
            'ready':True,'browser':types.SimpleNamespace(CoreWebView2=types.SimpleNamespace(Source='https://login.example.org/')),
            'last_state':{'reason':'login_navigation_failed'},'target':None,'open_entry':lambda:calls.append('open')})
        callback=native_callback('show',cells);callback();self.assertIn('open',calls)
        cells['last_state'].cell_contents={'reason':'sign_in_required'};calls.clear();callback()
        self.assertEqual(calls,['show'])
        cells['last_state'].cell_contents={'reason':'login_navigation_failed'};cells['target'].cell_contents={'id':'download'}
        calls.clear();callback();self.assertEqual(calls,['show'])
    def test_failed_component_restarts_only_owned_worker_and_keeps_profile(self):
        for reason in ['browser_process_failed','webview2_unavailable','webview2_initialization_timeout']:
            with self.subTest(reason=reason),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);(root/'profile').mkdir();marker=root/'profile'/'session';marker.write_text('retained')
                (root/'config.json').write_text(json.dumps({'allowed_origins':['https://portal.example.org/'],'allow_translated_network':True}),encoding='utf-8')
                (root/'status.json').write_text(json.dumps({'state':'awaiting_login','reason':reason}),encoding='utf-8')
                session=access.InstitutionalSession(types.SimpleNamespace(project=root,root=root/'incoming'),root)
                owned=unittest.mock.Mock();owned.poll.return_value=None;session.process=owned
                new=unittest.mock.Mock();new.poll.return_value=None
                layout=types.ModuleType(PACKAGE+'.layout');layout.app_dir=lambda project:project/'app'
                with patch.dict(sys.modules,{layout.__name__:layout}),patch.object(access.subprocess,'Popen',return_value=new) as launch:
                    session.connect()
                owned.wait.assert_called_once_with(timeout=8);owned.terminate.assert_not_called()
                launch.assert_called_once();self.assertIs(session.process,new);self.assertEqual(marker.read_text(),'retained')
                self.assertIn('profile', [p.name for p in root.iterdir()])
    def test_healthy_reconnect_uses_same_worker_and_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'config.json').write_text(json.dumps({'allow_translated_network':True}),encoding='utf-8')
            (root/'status.json').write_text(json.dumps({'state':'awaiting_login','reason':'sign_in_required'}),encoding='utf-8')
            session=access.InstitutionalSession(types.SimpleNamespace(project=root),root)
            owned=unittest.mock.Mock();owned.poll.return_value=None;session.process=owned
            with patch.object(access.subprocess,'Popen') as launch:session.connect()
            launch.assert_not_called();owned.wait.assert_not_called();self.assertIs(session.process,owned)
            self.assertEqual(json.loads((root/'command.json').read_text('utf-8'))['action'],'show')
    def test_quiet_reopen_retains_observed_login_but_pdf_history_is_not_login(self):
        for confirmed in [True,False]:
            with self.subTest(confirmed=confirmed),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);(root/'profile').mkdir();marker=root/'profile'/'session';marker.write_text('retained')
                (root/'config.json').write_text(json.dumps({'entry_url':'https://portal.example.org/','allow_translated_network':True}),encoding='utf-8')
                (root/'status.json').write_text(json.dumps({'state':'awaiting_test','reason':'browser_closed'}),encoding='utf-8')
                (root/'connection.json').write_text(json.dumps({'confirmed':confirmed}),encoding='utf-8')
                (root/'verification.json').write_text(json.dumps({'doi':'10.1234/old','tested_at':access.stamp()}),encoding='utf-8')
                session=access.InstitutionalSession(types.SimpleNamespace(project=root,root=root/'incoming'),root)
                self.assertEqual(session.status()['session_authenticated'],confirmed)
                self.assertFalse(session.status()['authentication_confirmed'])
                layout=types.ModuleType(PACKAGE+'.layout');layout.app_dir=lambda project:project/'app'
                worker=unittest.mock.Mock();worker.poll.return_value=None
                with patch.dict(sys.modules,{layout.__name__:layout}),patch.object(access.subprocess,'Popen',return_value=worker):
                    session.connect(hidden=True)
                launch=json.loads((root/'launch.json').read_text('utf-8'))
                self.assertTrue(launch['resume'])
                self.assertEqual(launch['session_authenticated'],confirmed)
                self.assertEqual(marker.read_text(),'retained')
    def test_failed_page_is_not_reported_ready_for_automatic_download(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'config.json').write_text(json.dumps({'entry_url':'https://portal.example.org/'}),encoding='utf-8')
            for reason in ['login_navigation_failed','login_open_timeout','institution_destination_unsafe','webview2_initialization_timeout']:
                (root/'status.json').write_text(json.dumps({'state':'awaiting_test','reason':reason}),encoding='utf-8')
                session=access.InstitutionalSession(types.SimpleNamespace(project=root),root)
                self.assertFalse(session.status()['task_ready'])

class DiscoveryEntryTests(unittest.IsolatedAsyncioTestCase):
    def test_specific_slam_technique_never_uses_broad_slam_auto_import(self):
        for topic in ['visual SLAM loop closure detection','visual loop closure detection','4D world model','视觉SLAM中的回环检测','经典的visual SLAM 以里程计为主']:
            job={'context':{'literature_search':{'search_plan':{'topic_query':topic}}}}
            self.assertIsNone(quota.kind(job),topic)
        self.assertEqual(quota.kind({'context':{'literature_search':{'query':'visual SLAM'}}}),'visual')

    def setUp(self):
        self.r=record();self.r['domain_ids']=['domain']
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        root=Path(directory.name);(root/'outputs').mkdir()
        self.store=types.SimpleNamespace(record=self.r,project=root,resource=lambda rid:{'metadata':{'pdf_version':'unknown'}})
        self.broker=object.__new__(broker_mod.InstitutionalBroker)
        self.broker.store=self.store;self.broker.write=AsyncMock()
        self.job={'id':'job','task':'discover_papers','context':{'job_id':'job','output_dir':'outputs','scope':{'domain_id':'domain'}}}
        self.broker.scope=lambda *args:(self.job,None)
        self.broker.guard_paper=unittest.mock.Mock()
        self.body={'job_id':'job','paper':{**self.r,'candidate_id':'candidate','citation_record_id':self.r['id'],'sources':[]}}

    async def test_no_institution_and_no_known_pdf_still_use_full_shared_pipeline(self):
        receipt={'resource_id':'pdf','version_id':'version','sha256':'hash','new_download':True}
        with patch.object(graph,'acquire_node',AsyncMock(return_value=receipt)) as acquire:
            result=await self.broker.acquire_fulltext(self.body)
        self.assertEqual(result['status'],'imported')
        self.assertEqual(result['citation_record_id'],self.r['id'])
        self.assertEqual(acquire.call_args.args[2]['download_sources'],[])
        self.assertIs(acquire.call_args.args[4],self.broker)
        self.assertEqual(acquire.call_args.args[5],'domain')
        saved=finish.read_receipts(self.store.project/'outputs'/finish.RECEIPTS,self.job['context'])
        self.assertEqual(saved['rows'][0]['version_id'],'version')
        self.assertEqual(saved['rows'][0]['citation_record_id'],self.r['id'])

    async def test_wrong_citation_or_domain_cannot_enter_download(self):
        for change in ['title','domain','record']:
            with self.subTest(change=change):
                body=copy.deepcopy(self.body)
                if change=='title':body['paper']['title']='A different paper'
                elif change=='record':body['paper'].pop('citation_record_id')
                else:self.r['domain_ids']=[]
                with patch.object(graph,'acquire_node',AsyncMock()) as acquire, self.assertRaises(DomainError):
                    await self.broker.acquire_fulltext(body)
                acquire.assert_not_awaited();self.r['domain_ids']=['domain']

    async def test_failed_download_and_cancel_never_report_imported(self):
        with patch.object(graph,'acquire_node',AsyncMock(return_value={'unavailable_reason':'no_public_pdf'})):
            result=await self.broker.acquire_fulltext(self.body)
        self.assertEqual(result['status'],'unavailable')
        self.assertNotIn('resource_id',result)
        saved=finish.read_receipts(self.store.project/'outputs'/finish.RECEIPTS,self.job['context'])
        self.assertEqual(saved['rows'][0]['unavailable_reason'],'no_public_pdf')
        with patch.object(graph,'acquire_node',AsyncMock(side_effect=asyncio.CancelledError)),self.assertRaises(asyncio.CancelledError):
            await self.broker.acquire_fulltext(self.body)


class AcquisitionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.r=record();self.node={**self.r,'id':'candidate'}
        self.store=types.SimpleNamespace(record=self.r,outcomes=[],resources=lambda:[],job=lambda i:{'status':'running'})
        self.job={'id':'job','task':'paper_relationships','context':{'scope':{},'external_network':'user_requested'}}
        self.calls=[]
        async def write(kind,body,action):return action()
        self.write=write
        for module,name in [(download,'locate_proceedings'),(download,'locate_openalex'),(download,'locate_public'),(download,'locate_index'),(official,'discover'),(official,'locate_publisher'),(official,'locate_github'),(sci_hub,'locate')]:
            p=patch.object(module,name,AsyncMock(side_effect=DomainError('public_repository_no_identity_match')));p.start();self.addCleanup(p.stop)
        p=patch.object(graph,'verified_resources',return_value=[]);p.start();self.addCleanup(p.stop)
    def broker(self,state,response):
        session=types.SimpleNamespace(status=lambda:state)
        async def acquire(body):self.calls.append(('publisher',body));return response
        return types.SimpleNamespace(manager=types.SimpleNamespace(status=lambda:{'sites':[state]},route_session=lambda url:('ieee',session)),acquire=acquire)
    async def test_unknown_publisher_route_resolves_only_after_positive_account_check(self):
        real_url=self.r['publisher_url'];self.r['publisher_url']='https://doi.org/'+self.r['doi']
        b=self.broker({'online':True,'authentication_confirmed':True,'task_ready':True},{'resource_id':'formal'})
        routed=[]
        b.manager.route_session=lambda url:(routed.append(url) or ('ieee',types.SimpleNamespace(status=lambda:{'online':True,'authentication_confirmed':True,'task_ready':True})))
        with patch.object(official,'resolve_publisher_url',AsyncMock(return_value={**self.r,'publisher_url':real_url})) as resolve:
            result=await graph.acquire_node(self.store,self.job,self.node,self.write,b)
        resolve.assert_awaited_once();self.assertEqual(routed,[real_url]);self.assertEqual(result['resource_id'],'formal')
    async def test_unlogged_skips_publisher_page_and_doi_redirect(self):
        self.r['publisher_url']='https://doi.org/'+self.r['doi']
        b=self.broker({'online':False,'state':'awaiting_login'},None)
        with patch.object(official,'resolve_publisher_url',AsyncMock()) as route:
            result=await graph.acquire_node(self.store,self.job,self.node,self.write,b)
        route.assert_not_awaited();official.locate_publisher.assert_not_awaited()
        download.locate_public.assert_awaited_once();official.locate_github.assert_awaited_once()
        self.assertFalse(self.calls);self.assertEqual(result['publisher_attempt']['status'],'skipped')
        self.assertFalse(result['publisher_attempt']['request_sent'])
    async def test_reported_login_and_online_browser_do_not_authorize_download(self):
        b=self.broker({'online':True,'task_ready':True,'login_reported_at':'now','authentication_confirmed':False},None)
        await graph.acquire_node(self.store,self.job,self.node,self.write,b)
        self.assertFalse(self.calls);official.locate_publisher.assert_not_awaited()
        download.locate_public.assert_awaited_once()
    async def test_expired_account_does_not_restore_or_request_publisher(self):
        b=self.broker({'online':True,'state':'expired','verified_pdf':{'doi':self.r['doi']}},None)
        b.resume_account=AsyncMock()
        await graph.acquire_node(self.store,self.job,self.node,self.write,b)
        b.resume_account.assert_not_awaited();self.assertFalse(self.calls)
    async def test_unlogged_registry_pdf_candidate_is_not_treated_as_oa(self):
        url='https://ieeexplore.ieee.org/paper.pdf'
        self.node['download_sources']=[{'public_oa':True,'access_url':url,'publisher_url':self.r['publisher_url']}]
        self.r['public_copy_bindings']=[{'pdf_url':url,'match_basis':'registered_doi_pdf_link_candidate_only'}]
        with patch.object(download,'acquire',AsyncMock()) as acquire:
            await graph.acquire_node(self.store,self.job,self.node,self.write,None)
        acquire.assert_not_awaited();official.locate_publisher.assert_not_awaited()
    async def test_known_oa_publisher_download_does_not_need_account(self):
        self.r['open_access_verified']=True
        url='https://ieeexplore.ieee.org/oa-paper.pdf'
        source={'public_oa':True,'access_url':url,'publisher_url':self.r['publisher_url']}
        self.r['public_download_sources']=[source]
        with patch.object(download,'acquire',AsyncMock(return_value={'resource_id':'oa','sha256':'s'})) as acquire:
            result=await graph.acquire_node(self.store,self.job,self.node,self.write,None)
        acquire.assert_awaited_once();self.assertEqual(result['resource_id'],'oa')
        self.assertEqual(result['publisher_attempt']['status'],'skipped')
    async def test_explicit_index_oa_link_on_publisher_host_survives_no_login(self):
        self.r['public_download_sources']=[{'public_oa':True,'open_access_verified':True,'publisher_url':self.r['publisher_url'],'access_url':'https://ieeexplore.ieee.org/oa.pdf'}]
        with patch.object(download,'acquire',AsyncMock(return_value={'resource_id':'oa'})):
            result=await graph.acquire_node(self.store,self.job,self.node,self.write,None)
        self.assertEqual(result['resource_id'],'oa');self.assertFalse(self.calls)
    async def test_authenticated_subscription_denial_of_other_article_does_not_disable_account(self):
        b=self.broker({'online':True,'authentication_confirmed':True,'task_ready':False,'reason':'subscription_denied'},
                      {'resource_id':'formal','sha256':'s'})
        result=await graph.acquire_node(self.store,self.job,self.node,self.write,b)
        self.assertEqual(result['resource_id'],'formal');self.assertEqual(len(self.calls),1)
    async def test_no_matching_account_skips_publisher_but_queries_repositories(self):
        b=self.broker({},None)
        b.manager.route_session=lambda url:(_ for _ in ()).throw(DomainError('institution_site_required'))
        result=await graph.acquire_node(self.store,self.job,self.node,self.write,b)
        self.assertEqual(result['publisher_attempt']['status'],'skipped')
        official.locate_publisher.assert_not_awaited();official.locate_github.assert_awaited_once()
    async def test_repository_misses_do_not_complete_coverage_when_index_is_limited(self):
        download.locate_openalex.side_effect=DomainError('public_index_unavailable',provider='OpenAlex',http_status=429,request_sent=False)
        result=await graph.acquire_node(self.store,self.job,self.node,self.write,None)
        self.assertTrue(result['full_text_checked'])
        self.assertFalse(result['full_text_coverage_complete'])
        self.assertEqual(next(row['status'] for row in result['full_text_sources'] if row['provider']=='OpenAlex'),'cooldown')
    async def test_logged_in_publisher_first_even_when_oa_plan_ranked_first(self):
        self.r['public_download_sources']=[{'public_oa':True,'pdf_version':'published','publisher_url':self.r['publisher_url'],'access_url':'https://example.edu/a.pdf'}]
        b=self.broker({'task_ready':True,'online':True,'authentication_confirmed':True},{'resource_id':'r1','version_id':'v1','sha256':'s'})
        result=await graph.acquire_node(self.store,self.job,self.node,self.write,b)
        self.assertEqual(result['resource_id'],'r1')
        source=self.calls[0][1]['paper']['sources'][0]
        self.assertEqual(source['access_url'],self.r['publisher_url'])
        self.assertFalse(source.get('public_oa'))
        official.discover.assert_not_awaited()
        download.locate_public.assert_not_awaited()
    async def test_challenged_session_keeps_reason_and_continues_public_lookup(self):
        b=self.broker({'online':True,'task_ready':False,'reason':'challenge_requires_user'},None)
        download.locate_openalex.side_effect=DomainError('public_index_unavailable',http_status=401)
        result=await graph.acquire_node(self.store,self.job,self.node,self.write,b)
        self.assertFalse(self.calls)
        self.assertEqual(result['publisher_attempt']['reason'],'challenge_requires_user')
        self.assertFalse(result['publisher_attempt']['request_sent'])
        self.assertEqual(result['full_text_status'],'search_incomplete')
        self.assertEqual(next(a for a in result['full_text_attempts'] if a.get('http_status'))['http_status'],401)
        official.discover.assert_awaited_once()
    async def test_public_copy_only_after_publisher_failure(self):
        b=self.broker({'online':True,'task_ready':True,'authentication_confirmed':True},{'status':'unavailable','reason':'subscription_denied'})
        source={'public_oa':True,'publisher_url':'https://arxiv.org/abs/2302.04031','access_url':'https://arxiv.org/pdf/2302.04031'}
        official.discover.side_effect=None;official.discover.return_value=(self.r,source)
        async def acquire(*a,**k):
            self.assertEqual(self.calls[0][0],'publisher');return {'resource_id':'r2','version_id':'v2','sha256':'s'}
        with patch.object(download,'acquire',acquire):result=await graph.acquire_node(self.store,self.job,self.node,self.write,b)
        self.assertEqual(result['resource_id'],'r2')
        self.assertEqual(result['publisher_attempt']['reason'],'subscription_denied')
    async def test_pending_candidate_survives_later_index_failure(self):
        candidate={'url':'https://arxiv.org/abs/2302.04031','title':'Candidate'}
        download.locate_public.side_effect=DomainError('public_repository_candidate_needs_review',candidates=[candidate])
        download.locate_openalex.side_effect=DomainError('public_index_unavailable')
        result=await graph.acquire_node(self.store,self.job,self.node,self.write,None)
        self.assertEqual(result['full_text_status'],'candidate_needs_review')
        self.assertEqual(result['full_text_candidates'],[candidate])
        self.assertEqual(self.store.outcomes[-1]['full_text_candidates'],[candidate])
    async def test_cancellation_is_not_swallowed_as_missing_pdf(self):
        official.discover.side_effect=asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):await graph.acquire_node(self.store,self.job,self.node,self.write,None)
    async def test_each_failed_pdf_url_is_attempted_only_once(self):
        source={'public_oa':True,'publisher_url':'https://example.edu/p.pdf','access_url':'https://example.edu/p.pdf'}
        self.node['download_sources']=[source]
        official.discover.side_effect=None;official.discover.return_value=(self.r,source)
        with patch.object(download,'acquire',AsyncMock(side_effect=DomainError('public_pdf_http_404'))) as acquire:
            await graph.acquire_node(self.store,self.job,self.node,self.write,None)
        self.assertEqual(acquire.await_count,1)

    async def test_existing_preprint_does_not_skip_logged_in_publisher(self):
        cached={'id':'preprint','version_id':'v_old','sha256':'s_old','metadata':{'pdf_version':'preprint'}}
        graph.verified_resources.return_value=[cached]
        b=self.broker({'task_ready':True,'online':True,'authentication_confirmed':True},{'resource_id':'published','version_id':'v_new','sha256':'s_new'})
        result=await graph.acquire_node(self.store,self.job,self.node,self.write,b)
        self.assertEqual(result['resource_id'],'published')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(cached['sha256'],'s_old')
        download.locate_public.assert_not_awaited()

    async def test_existing_published_pdf_is_reused_without_another_transfer(self):
        cached=[{'id':'published','version_id':'v','sha256':'s','metadata':{'pdf_version':'published'}}]
        graph.verified_resources.return_value=cached;self.store.resources=lambda:cached
        b=self.broker({'task_ready':True,'online':True},None)
        result=await graph.acquire_node(self.store,self.job,self.node,self.write,b)
        self.assertEqual(result['resource_id'],'published')
        self.assertEqual(result['pdf_version'],'published')
        self.assertFalse(result['new_download'])
        self.assertFalse(self.calls)

    async def test_failed_publisher_upgrade_keeps_saved_preprint_and_reason(self):
        cached=[{'id':'preprint','version_id':'v','sha256':'s','metadata':{'pdf_version':'preprint'}}]
        graph.verified_resources.return_value=cached;self.store.resources=lambda:cached
        b=self.broker({'task_ready':True,'online':True,'authentication_confirmed':True},{'status':'unavailable','reason':'subscription_denied'})
        result=await graph.acquire_node(self.store,self.job,self.node,self.write,b)
        self.assertEqual(result['resource_id'],'preprint')
        self.assertTrue(result['publisher_upgrade_pending'])
        self.assertEqual(result['publisher_attempt']['reason'],'subscription_denied')
        self.assertFalse(result['new_download'])
        official.discover.assert_not_awaited()
        download.locate_public.assert_not_awaited()

    async def test_challenged_account_does_not_hide_saved_preprint(self):
        cached=[{'id':'preprint','version_id':'v','sha256':'s','metadata':{'pdf_version':'preprint'}}]
        graph.verified_resources.return_value=cached;self.store.resources=lambda:cached
        b=self.broker({'online':True,'task_ready':False,'reason':'challenge_requires_user'},None)
        result=await graph.acquire_node(self.store,self.job,self.node,self.write,b)
        self.assertEqual(result['resource_id'],'preprint')
        self.assertFalse(result['publisher_attempt']['request_sent'])
        self.assertEqual(result['publisher_attempt']['reason'],'challenge_requires_user')
        self.assertFalse(self.calls)
        download.locate_public.assert_not_awaited()

class CachePreferenceTests(unittest.TestCase):
    def test_verified_published_pdf_wins_over_preprint_catalog_order(self):
        import tempfile
        r=record()
        with tempfile.TemporaryDirectory() as temp:
            files={};resources=[]
            for version in ['preprint','published']:
                path=Path(temp)/(version+'.pdf');path.write_bytes(version.encode())
                files[version]=path
                resources.append(dict(id=version,type='paper',state='ready',sha256=graph.digest(path),
                    metadata=dict(doi=r['doi'],publication_record_id=r['id'],pdf_version=version,
                                  pdf_identity={k:r[k] for k in ('title','authors','doi')})))
            store=types.SimpleNamespace(resources=lambda:resources,snapshot=lambda resource:files[resource['id']])
            with patch.object(graph,'validate_pdf') as validate:
                result=graph.verified_resources(store,{**r,'id':'candidate'},r)
            self.assertEqual([v['id'] for v in result],['published','preprint'])
            self.assertEqual(validate.call_count,2)

class StatusTests(unittest.TestCase):
    def test_original_nine_failures_do_not_mean_no_pdf(self):
        value={'full_text_reason':'public_index_unavailable; public_repository_no_identity_match'}
        self.assertEqual(graph.acquisition_state(value),'search_incomplete')
    def test_repository_empty_result_is_not_global_nonexistence(self):
        self.assertEqual(graph.describe({'unavailable_reason':'public_repository_no_identity_match'})['full_text_label'],'已检查来源暂未找到全文')
    def test_challenge_is_not_subscription_denial_or_not_found(self):
        self.assertEqual(graph.acquisition_state({'unavailable_reason':'challenge_requires_user'}),'access_restricted')
    def test_loaded_pdf_wins_over_old_failed_outcome(self):
        self.assertEqual(graph.acquisition_state({'cached_resources':[{'resource_id':'r'}],'full_text_reason':'public_index_unavailable'}),'acquired')
    def test_challenge_does_not_clear_without_positive_authentication(self):
        for flags in ({},{'authenticated':True,'challenge':True},{'authenticated':True,'loading':True},{'authenticated':True,'login':True}):
            self.assertIsNone(browser.readiness_result(flags,True))
    def test_human_completed_challenge_can_restore_authenticated_state(self):
        self.assertEqual(browser.readiness_result({'authenticated':True,'challenge':False,'loading':False,'login':False},True),
                         ('awaiting_test','authenticated_session_ready',True))
    def test_ordinary_article_without_signout_does_not_revoke_known_login(self):
        self.assertEqual(browser.readiness_result({},False,True),
                         ('awaiting_test','authenticated_session_ready',True))
        self.assertEqual(browser.readiness_result({'login':True},False,True),
                         ('awaiting_login','sign_in_required',False))
    def test_saved_login_never_bypasses_current_challenge(self):
        self.assertIsNone(browser.readiness_result({'challenge':True},True,True))
        self.assertIsNone(browser.readiness_result({},True,True))
    def test_google_scholar_entry_is_not_claimed_as_completed_verification(self):
        r=record();store=types.SimpleNamespace(record=r,resources=lambda:[])
        with patch.object(graph,'verified_resources',return_value=[]):
            result=enrich.display(store,{'nodes':[{**r,'id':'n'}]})
        entry=result['nodes'][0]['google_scholar_verification']
        self.assertEqual(entry['status'],'not_checked')
        self.assertTrue(entry['url'].startswith('https://scholar.google.com/scholar?'))
        self.assertTrue(entry['counts_separate'])

class BrokerRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_publisher_only_reconstructs_formal_route_from_record(self):
        r=record();r['public_download_sources']=[{'public_oa':True,'pdf_version':'published','publisher_url':'https://author.example.edu/p.pdf','access_url':'https://author.example.edu/p.pdf'}]
        store=types.SimpleNamespace(record=r,outcomes=[])
        state={'online':True,'task_ready':True,'authentication_confirmed':True,'state':'awaiting_test','config':{'method':'publisher','allowed_origins':['https://ieeexplore.ieee.org']}}
        requests=[]
        def test(request):requests.append(request);return state
        manager=types.SimpleNamespace(store=store,broker_lock=threading.Lock(),last_attempt=0,request_site_id=None,
            status=lambda:state,read=lambda *a:{'id':'target'},test=test)
        manager.route_session=lambda *a,**k:('ieee',manager)
        async def write(kind,body,action):return action()
        broker=broker_mod.InstitutionalBroker(manager,write)
        job={'id':'job','task':'paper_relationships','context':{'scope':{}}}
        broker.scope=lambda *a:(job,state['config']);broker.guard_paper=lambda *a:None;broker.active=lambda *a:True
        broker.wait=lambda *a:{'status':'unavailable','reason':'publisher_pdf_link_unavailable'}
        result=await broker.acquire({'job_id':'job','publisher_only':True,
            'paper':{**r,'citation_record_id':r['id'],'candidate_id':'n','sources':r['public_download_sources']}})
        self.assertEqual(len(requests),1)
        self.assertEqual(requests[0]['access_url'],r['publisher_url'])
        self.assertNotIn('public_oa',requests[0])
        self.assertEqual(result['reason'],'publisher_pdf_link_unavailable')

class SharedPublisherQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_saved_login_without_test_pdf_restores_before_download(self):
        states=iter([{'online':False,'state':'awaiting_test','task_ready':True,'session_authenticated':True},
                     {'online':True,'reason':'browser_ready','authentication_confirmed':False},
                     {'online':True,'reason':'official_page_loaded','authentication_confirmed':False},
                     {'online':True,'reason':'authenticated_session_ready','authentication_confirmed':True}])
        manager=types.SimpleNamespace(store=None,status=lambda:next(states),connect=unittest.mock.Mock())
        broker=broker_mod.InstitutionalBroker(manager,None);broker.active=lambda i:True
        with patch.object(broker_mod.asyncio,'sleep',AsyncMock()):ready=await broker.resume_account(manager,'job')
        manager.connect.assert_called_once_with(True)
        self.assertTrue(ready['authentication_confirmed'])
    async def test_restoration_challenge_never_promotes_saved_login_to_download_permission(self):
        states=iter([{'online':False,'state':'awaiting_test','task_ready':True,'session_authenticated':True},
                     {'online':True,'reason':'challenge_requires_user','session_authenticated':True,'authentication_confirmed':False}])
        manager=types.SimpleNamespace(store=None,status=lambda:next(states),connect=unittest.mock.Mock())
        broker=broker_mod.InstitutionalBroker(manager,None);broker.active=lambda i:True
        ready=await broker.resume_account(manager,'job')
        self.assertFalse(ready['authentication_confirmed'])
        self.assertEqual(ready['reason'],'challenge_requires_user')
    async def test_saved_account_startup_waits_for_ready_status(self):
        states=iter([{'online':True,'reason':'browser_starting','authentication_confirmed':True},
                     {'online':True,'reason':'browser_ready','task_ready':True,'authentication_confirmed':True}])
        manager=types.SimpleNamespace(store=None,status=lambda:next(states))
        broker=broker_mod.InstitutionalBroker(manager,None);broker.active=lambda i:True
        ready=await broker.resume_account(manager,'job')
        self.assertTrue(ready['task_ready'])
    async def test_busy_queue_reaches_bounded_fallback_without_touching_holder(self):
        manager=types.SimpleNamespace(store=None);broker=broker_mod.InstitutionalBroker(manager,None)
        await broker.acquisition_queue.acquire()
        with patch.object(broker_mod,'PUBLISHER_QUEUE_TIMEOUT_SECONDS',.01):
            with self.assertRaises(DomainError) as caught:await broker.acquire({})
        self.assertEqual(caught.exception.code,'institution_queue_timeout')
        self.assertTrue(broker.acquisition_queue.locked());broker.acquisition_queue.release()
    async def test_separate_task_brokers_wait_for_one_shared_browser(self):
        manager=types.SimpleNamespace(store=None)
        first=broker_mod.InstitutionalBroker(manager,None);second=broker_mod.InstitutionalBroker(manager,None)
        entered=[];release=asyncio.Event();started=asyncio.Event()
        async def slow(body):entered.append('first');started.set();await release.wait();return 'first'
        async def next_paper(body):entered.append('second');return 'second'
        first.acquire_one=slow;second.acquire_one=next_paper
        task1=asyncio.create_task(first.acquire({}));await started.wait()
        task2=asyncio.create_task(second.acquire({}));await asyncio.sleep(0)
        self.assertEqual(entered,['first']);release.set()
        self.assertEqual(await asyncio.gather(task1,task2),['first','second'])
        self.assertEqual(entered,['first','second'])

class PDFIdentityTests(unittest.TestCase):
    def test_chinese_full_author_name_order_not_a_one_character_surname(self):
        r=record();r.update(title='A Review of ORB-SLAM Algorithm',authors=['博娜 李'],doi='10.12677/sea.2023.121009')
        class Doc:
            is_pdf=True
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def __len__(self):return 1
            def __getitem__(self,i):return types.SimpleNamespace(get_text=lambda:content)
        stub('pdf',open_pdf=lambda p:Doc())
        with tempfile.TemporaryDirectory() as temp:
            pdf=Path(temp)/'paper.pdf';pdf.write_bytes(b'%PDF-1.4 fixture')
            target={**r,'citation_record':r,'pdf_identity':{k:r[k] for k in ('title','authors','doi')}}
            content=r['title']+' 李博娜 '+r['doi'];self.assertTrue(access.validate_pdf(pdf,target)['author_in_pdf'])
            content=r['title']+' 李 '+r['doi']
            with self.assertRaises(DomainError):access.validate_pdf(pdf,target)
    def test_actual_pdf_identity_and_version_bridge_are_both_required(self):
        import tempfile
        r=record()
        class Doc:
            is_pdf=True
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def __len__(self):return 1
            def __getitem__(self,i):return types.SimpleNamespace(get_text=lambda:'Old manuscript title Chunge Bai Tao Xiao arXiv:2302.04031v3')
        stub('pdf',open_pdf=lambda p:Doc())
        identity={'title':'Old manuscript title','authors':r['authors'],'arxiv_id':'2302.04031'}
        with tempfile.TemporaryDirectory() as temp:
            pdf=Path(temp)/'paper.pdf';pdf.write_bytes(b'%PDF-1.4 test fixture')
            target={**r,'citation_record':r,'pdf_identity':identity,'pdf_version':'preprint'}
            with self.assertRaises(DomainError):access.validate_pdf(pdf,target)
            r['related_identifiers']=['arxiv:2302.04031']
            self.assertTrue(access.validate_pdf(pdf,target)['linked_publication'])
            identity['authors']=['Wrong Author']
            with self.assertRaises(DomainError):access.validate_pdf(pdf,target)

if __name__=='__main__':unittest.main()
