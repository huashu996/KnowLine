"""Search metadata must not depend on the attached PDF or erase its provenance."""
import copy
import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

APP=Path(__file__).resolve().parents[1]
EXE=None
if '--exe' in sys.argv:
    at=sys.argv.index('--exe');EXE=Path(sys.argv[at+1]);del sys.argv[at:at+2]
PACKAGE='_search_metadata_test'
package=types.ModuleType(PACKAGE);package.__path__=[str(APP/'backend')];sys.modules[PACKAGE]=package
pdf=types.ModuleType(PACKAGE+'.pdf');pdf.open_pdf=lambda *a:None;sys.modules[pdf.__name__]=pdf
store=types.ModuleType(PACKAGE+'.store');store.uid=lambda prefix:prefix+'_test';sys.modules[store.__name__]=store
def load(name):
    if not EXE:return importlib.import_module(PACKAGE+'.'+name)
    sys.path.insert(0,str(APP/'scripts'))
    from patch_frozen_modules import module_code
    mod=types.ModuleType(PACKAGE+'.'+name);mod.__package__=PACKAGE;sys.modules[mod.__name__]=mod
    exec(module_code(EXE,'backend.'+name),mod.__dict__);return mod
bib=load('paper_bibliography');auto=load('paper_auto_metadata')

def record():
    return {'id':'pr_latest','revision':1,'resource_ids':['r_paper'],'title':'Current published title',
            'authors':['Current Author'],'doi':'10.1234/paper','year':2026,'venue':'Current journal',
            'source_type':'JournalArticle','url':'https://doi.org/10.1234/paper',
            'publication_status':'published','metadata_status':'verified','latest_verified':True,
            'latest_checked_at':bib.stamp(),'source_url':'https://api.crossref.org/works/10.1234/paper',
            'identity_key':'doi:10.1234/paper','evidence_path':'source.json','evidence_sha256':'source-hash'}

class Store:
    def __init__(self):
        self.value={'id':'r_paper','type':'paper','state':'ready','title':'Different old manuscript title','revision':1,
                    'version_id':'v_original','sha256':'original-pdf-hash',
                    'metadata':{'doi':'10.1234/paper','authors':['Old Author'],'year':2020,'venue':'Old venue',
                                'pdf_version':'preprint','pdf_identity':{'title':'Old PDF title'},
                                'access_method':'public_repository','field_sources':{},
                                'metadata_status':'verified','metadata_verification':{'state':'identity_conflict'}}}
    def resource(self,rid):return copy.deepcopy(self.value)
    def resources(self,summary=False):return [self.resource('r_paper')]
    def snapshot(self,*a):raise AssertionError('Known search identity must not open the PDF')
    def update_resource(self,rid,body):
        assert body['base_revision']==self.value['revision']
        for key,value in body.items():
            if key=='title':self.value['title']=value
            elif key=='field_sources':self.value['metadata'].setdefault(key,{}).update(value)
            elif key!='base_revision':self.value['metadata'][key]=value
        self.value['revision']+=1
        return {'resource':self.resource(rid)}

class MetadataTests(unittest.IsolatedAsyncioTestCase):
    async def run_update(self,store,source=None):
        async def write(kind,body,action):return action()
        verifier=auto.PaperMetadataVerifier(store,write)
        resolver=AsyncMock(return_value=source or record())
        with patch.object(verifier,'resolve',resolver),patch.object(bib,'save',side_effect=lambda s,r:r),patch.object(auto,'identity',side_effect=AssertionError('PDF identity gate called')):
            report=await verifier.verify('r_paper',{'refresh':True})
        return report,resolver

    async def test_current_search_wins_without_reading_or_matching_pdf(self):
        store=Store();original=copy.deepcopy(store.value)
        report,resolver=await self.run_update(store)
        self.assertEqual(report['state'],'verified')
        self.assertTrue(report['independent_of_pdf'])
        self.assertEqual(report['policy'],'publication_record_v2')
        self.assertEqual(store.value['title'],'Current published title')
        self.assertEqual(store.value['metadata']['authors'],['Current Author'])
        self.assertEqual(store.value['metadata']['year'],2026)
        self.assertEqual(store.value['metadata']['venue'],'Current journal')
        for key in ('pdf_version','pdf_identity','access_method'):
            self.assertEqual(store.value['metadata'][key],original['metadata'][key])
        self.assertEqual(store.value['sha256'],original['sha256'])
        self.assertEqual(store.value['version_id'],original['version_id'])
        resolver.assert_awaited_once_with('10.1234/paper',refresh=True)

    async def test_locked_manual_field_is_reported_without_pdf_conflict(self):
        store=Store();store.value['metadata']['field_sources']['title']={'locked':True}
        report,_=await self.run_update(store)
        self.assertEqual(store.value['title'],'Different old manuscript title')
        self.assertEqual(report['state'],'partial')
        self.assertEqual(report['reason'],'locked_field_conflict')
        self.assertEqual(report['conflicting_fields'],['title'])

    async def test_changed_pdf_version_during_lookup_cannot_receive_old_result(self):
        store=Store()
        async def write(kind,body,action):
            store.value['version_id']='v_new'
            return action()
        verifier=auto.PaperMetadataVerifier(store,write)
        with patch.object(verifier,'resolve',AsyncMock(return_value=record())):
            result=await verifier.verify('r_paper')
        self.assertEqual(result['state'],'superseded')
        self.assertEqual(store.value['revision'],1)

    async def test_network_failure_retains_existing_citation(self):
        store=Store()
        async def write(kind,body,action):return action()
        verifier=auto.PaperMetadataVerifier(store,write)
        with patch.object(verifier,'resolve',AsyncMock(side_effect=bib.DomainError('citation_source_unavailable',502))):
            result=await verifier.verify('r_paper')
        self.assertEqual(result['state'],'source_unavailable')
        self.assertEqual(store.value['title'],'Different old manuscript title')
        self.assertEqual(store.value['metadata']['metadata_status'],'verified')

    async def test_maintenance_repairs_old_conflict_once_without_reimport(self):
        store=Store()
        async def write(kind,body,action):return action()
        verifier=auto.PaperMetadataVerifier(store,write)
        resolver=AsyncMock(return_value=record())
        with patch.object(verifier,'resolve',resolver),patch.object(bib,'save',side_effect=lambda s,r:r):
            result=await verifier.repair_pending()
            self.assertEqual(result[0]['state'],'verified')
            self.assertEqual(await verifier.repair_pending(),[])
        resolver.assert_awaited_once()
        self.assertEqual(store.value['sha256'],'original-pdf-hash')

    async def test_failed_refresh_retains_evidenced_status_then_auto_recovers(self):
        store=Store();store.value['metadata']['metadata_verification']=bib.metadata_report(record())
        checked=store.value['metadata']['metadata_verification']['checked_at']
        async def write(kind,body,action):return action()
        verifier=auto.PaperMetadataVerifier(store,write)
        with patch.object(verifier,'resolve',AsyncMock(side_effect=bib.DomainError('citation_source_unavailable',502))):
            report=await verifier.verify('r_paper',{'refresh':True})
        self.assertEqual(report['state'],'verified')
        self.assertEqual(report['checked_at'],checked)
        self.assertEqual(report['refresh_state'],'source_unavailable')
        self.assertEqual(report['retry_count'],1)
        self.assertFalse(auto.verification_due(store.value))
        with patch.object(bib,'fresh',return_value=False),patch.object(verifier,'resolve',AsyncMock(return_value=record())),patch.object(bib,'save',side_effect=lambda s,r:r):
            recovered=await verifier.repair_pending()
        self.assertEqual(recovered[0]['state'],'verified')
        self.assertNotIn('refresh_state',recovered[0])
        self.assertFalse(auto.verification_due(store.value))

    async def test_failed_unverified_lookup_backs_off_and_changed_query_retries(self):
        store=Store()
        async def write(kind,body,action):return action()
        verifier=auto.PaperMetadataVerifier(store,write)
        resolver=AsyncMock(side_effect=bib.DomainError('citation_source_unavailable',502))
        with patch.object(verifier,'resolve',resolver):
            report=await verifier.verify('r_paper')
            self.assertEqual(report['state'],'source_unavailable')
            self.assertFalse(auto.verification_due(store.value))
            self.assertEqual(await verifier.repair_pending(),[])
            store.value['metadata']['doi']='10.1234/corrected'
            self.assertTrue(auto.verification_due(store.value))
            await verifier.repair_pending()
        self.assertEqual(resolver.await_count,2)
        self.assertEqual(store.value['metadata']['metadata_verification']['retry_count'],2)

    def test_maintenance_ignores_deleted_missing_and_non_papers(self):
        for field,value in [('state','deleted'),('state','missing'),('type','code')]:
            store=Store();store.value[field]=value
            self.assertFalse(auto.verification_due(store.value))

    async def test_deleted_resource_does_not_stop_the_retry_batch(self):
        store=Store()
        async def write(kind,body,action):return action()
        verifier=auto.PaperMetadataVerifier(store,write)
        with patch.object(verifier,'verify',AsyncMock(side_effect=bib.DomainError('resource_not_found',404))):
            self.assertEqual(await verifier.repair_pending(),[])

    async def test_exact_title_search_does_not_compare_pdf_authors(self):
        source=record()
        with patch.object(bib,'fetch',AsyncMock(return_value=json.dumps({'message':{'items':[{'DOI':source['doi']}]}}).encode())),patch.object(bib,'crossref',return_value=source),patch.object(bib,'resolve',AsyncMock(return_value=source)):
            result=await auto.search_title({'title':source['title'],'authors':['Old PDF Author']})
        self.assertEqual(result['authors'],['Current Author'])

    async def test_ambiguous_search_is_not_auto_attached(self):
        one=record();two={**one,'doi':'10.1234/other'}
        with patch.object(bib,'fetch',AsyncMock(return_value=json.dumps({'message':{'items':[{},{}]}}).encode())),patch.object(bib,'crossref',side_effect=[one,two]):
            with self.assertRaises(bib.DomainError) as caught:await auto.search_title({'title':one['title']})
        self.assertEqual(caught.exception.code,'citation_search_ambiguous')

    def test_download_metadata_replaces_old_pdf_conflict_with_source_status(self):
        result=bib.metadata(record())
        self.assertEqual(result['metadata_verification']['state'],'verified')
        self.assertTrue(result['metadata_verification']['independent_of_pdf'])
        self.assertNotIn('pdf_identity',result)

    async def test_metadata_transport_rejects_other_hosts_and_credentials(self):
        for url in ['http://api.crossref.org/works','https://example.com/works','https://user:secret@api.crossref.org/works']:
            with self.assertRaises(bib.DomainError):await bib._fetch(url)

    async def test_metadata_transport_bounds_response_and_never_follows_redirects(self):
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,size):return b'x'*size
        class Opener:
            def open(self,*args,**kwargs):return Response()
        with patch.object(bib.urllib.request,'build_opener',return_value=Opener()) as builder:
            with self.assertRaises(bib.DomainError) as caught:await bib._fetch('https://api.crossref.org/works/10.1234/paper')
        self.assertEqual(caught.exception.code,'citation_source_invalid')
        redirect=builder.call_args.args[0]
        self.assertIsNone(redirect.redirect_request(None,None,302,None,None,'https://example.com'))

if __name__=='__main__':unittest.main()
