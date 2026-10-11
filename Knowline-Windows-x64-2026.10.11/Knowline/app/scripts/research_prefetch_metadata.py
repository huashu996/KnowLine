"""Extract frozen local PDF identity evidence and prefetch bounded Crossref DOI records."""
import json,re,sys,time,urllib.request,urllib.parse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import pymupdf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.safety import contained
from backend.layout import project_root

def main():
    context_path=Path(sys.argv[1]).resolve(strict=True);root=project_root(Path.cwd())
    context=json.loads(context_path.read_text('utf-8-sig'));out=contained(root,context['output_dir'],False);out.mkdir(exist_ok=True,parents=True)
    docs={};rows=[]
    for frozen in context['resources']:
        sha=frozen['sha256']
        if sha not in docs:
            with pymupdf.open(contained(root,frozen['snapshot_path'])) as pdf:
                text='\n'.join(pdf[i].get_text() for i in range(min(2,len(pdf))))
                docs[sha]={'sha256':sha,'page_count':len(pdf),'text':text[:22000],'dois':list(dict.fromkeys(re.findall(r'10\.\d{4,9}/[^\s<>]+',text)))[:3],'arxiv_ids':list(dict.fromkeys(re.findall(r'(?:arXiv\s*:\s*|arxiv.org/(?:abs|pdf)/)(\d{4}\.\d{4,5})',text)))[:2]}
        rows.append({**frozen,'local_evidence':docs[sha]})
    dois=list(dict.fromkeys(doi.rstrip('.,;)') for d in docs.values() for doi in d['dois']))
    deadline=time.monotonic()+120
    def request(doi):
        url='https://api.crossref.org/works/'+urllib.parse.quote(doi,safe='/');row={'doi':doi,'url':url,'retrieved_at':datetime.now(timezone.utc).isoformat()}
        try:
            if time.monotonic()>deadline:raise TimeoutError('prefetch deadline')
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Knowline batch PDF identity audit'}),timeout=15) as response:
                row.update(status=response.status,response=json.loads(response.read(2*1024*1024)))
        except Exception as exc:row['error']=type(exc).__name__+': '+str(exc)
        return row
    sources=list(ThreadPoolExecutor(4).map(request,dois))
    p=out/'metadata-prefetch.json';p.write_text(json.dumps({'job_id':context['job_id'],'resources':rows,'crossref_responses':sources},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'path':str(p),'resources':len(rows),'unique_pdfs':len(docs),'doi_requests':len(dois),'successful_sources':sum(s.get('status')==200 for s in sources)},ensure_ascii=True))
if __name__=='__main__':main()
