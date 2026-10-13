"""Read-only online smoke checks against this instance's known missing papers.

Runs the production locator code with the installed TLS roots; never imports
files, mutates the catalog, edits a task or reuses institution credentials.
"""
import asyncio,importlib.util,json,ssl,sys,types,urllib.request,urllib.parse
from pathlib import Path

APP=Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding='utf-8')
PROJECT=APP.parent
spec=importlib.util.spec_from_file_location('lookup_fixture',APP/'tests/test_paper_acquisition.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
certifi=types.ModuleType('certifi');certifi.where=lambda:str(APP/'Knowline/_internal/certifi/cacert.pem')
sys.modules.setdefault('certifi',certifi)
context=ssl.create_default_context(cafile=certifi.where())
port=json.loads((PROJECT/'resource/.knowledge/config.json').read_text('utf-8'))['port']
with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/v1/paper-records',timeout=10) as response:
    records=json.load(response)

async def arxiv_bytes(url):
    target=urllib.parse.urlsplit(url)
    if target.scheme!='https' or target.hostname!='export.arxiv.org' or target.path!='/api/query':raise ValueError('outside_exact_arxiv_api')
    def read():
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Knowline paper lookup verification/1.0'}),context=context,timeout=20) as response:
            raw=response.read(2*1024*1024+1)
            if len(raw)>2*1024*1024:raise ValueError('response_too_large')
            return raw
    return await asyncio.to_thread(read)

fixture.bib.fetch=arxiv_bytes
async def main():
    report={'read_only':True,'registered_pdfs':0,'checks':[]}
    dsm=next(r for r in records if r['doi']=='10.1109/tro.2020.2991614')
    review=next(r for r in records if r['doi']=='10.12677/sea.2023.121009')
    for name,locator,record in [('arXiv',fixture.download.locate_public,dsm),('GitHub',fixture.official.locate_github,dsm),('Publisher',fixture.official.locate_publisher,review)]:
        try:
            updated,source=await locator(record)
            report['checks'].append({'provider':name,'status':'located','title':record['title'],
                'formal_doi':updated['doi'],'pdf_url':source['access_url'],'pdf_version':source['pdf_version'],
                'actual_pdf_downloaded':False,'identity':source.get('pdf_identity'),
                'source_url':source.get('version_source_url') or source.get('publisher_url')})
        except Exception as exc:
            report['checks'].append({'provider':name,'status':'incomplete','reason':getattr(exc,'code',type(exc).__name__),
                                     'details':getattr(exc,'params',{})})
    output=PROJECT/'outputs/论文星图全文定位在线验证_2026-10-12.json'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
asyncio.run(main())
