"""Read a user-supplied public Connected Papers graph in isolated WebView2.

Only visible recommendations are collected. No similarity edges are treated as
citations, no graph generation/account operations and no school/browser session
reuse. A single page request has a bounded wait, independently of task duration.
"""
import copy
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from .safety import DomainError, atomic_json
from .paper_bibliography import stamp

HOSTS = {'www.connectedpapers.com', 'connectedpapers.com', 'api.connectedpapers.com',
         'backhpa.prod.connectedpapers.com', 'rest.prod.connectedpapers.com', 'iprest.connectedpapers.com'}
PAGE_HOSTS = {'www.connectedpapers.com', 'connectedpapers.com'}
_cache = {}
_active = {}
_lock = threading.Lock()


def graph_url(value):
    if not isinstance(value,str) or len(value)>1200:raise DomainError('connected_papers_url_invalid')
    try:
        p=urlsplit(value.strip());port=p.port
    except ValueError:raise DomainError('connected_papers_url_invalid')
    if p.scheme!='https' or p.hostname not in PAGE_HOSTS or p.username or p.password or port not in {None,443} or p.query or p.fragment or not re.fullmatch(r'/main/[0-9a-f]{40}/[^/]+/graph',p.path):
        raise DomainError('connected_papers_url_invalid')
    return 'https://www.connectedpapers.com'+p.path


SCRIPT = r"""(() => {
 if (location.href==='about:blank') return JSON.stringify({status:'loading'});
 if (!['connectedpapers.com','www.connectedpapers.com'].includes(location.hostname) || !/^\/main\/[0-9a-f]{40}\/[^/]+\/graph$/.test(location.pathname)) return JSON.stringify({status:'redirect_scope_blocked'});
 const body=document.body?.innerText||'';
 if (/verify (?:you are|that you are)|unusual traffic|captcha|access denied|too many requests/i.test(body)) return JSON.stringify({status:'access_challenge'});
 const circles=[...document.querySelectorAll('circle[id^="circle_"]')];
 if (!circles.length) return JSON.stringify({status:'loading'});
 const rows=[...document.querySelectorAll('.list-group-item-mod')].slice(0,60).map(row=>{
   const title=row.querySelector('h5')?.textContent?.trim()||'';
   const text=row.textContent||''; const tail=text.slice(text.indexOf(title)+title.length).trim();
   const match=tail.match(/(\d{4})\s*$/); const year=match?Number(match[1]):null;
   const byline=match?tail.slice(0,match.index).trim():tail;
   const matching=circles.filter(c=>c.textContent.trim()===title);const circle=matching.length===1?matching[0]:null;
   return {title,byline,year,paper_id:circle?.id.slice(7)||null,origin:row.classList.contains('main')};
 }).filter(r=>r.title);
 return JSON.stringify({status:rows.length?'candidates_found':'loading',papers:rows});
})()"""


def sanitize(data,url):
    url=graph_url(url);papers=[]
    for row in (data.get('papers') or [])[:60]:
        if not isinstance(row,dict):continue
        title=str(row.get('title','')).strip()[:500];identity=row.get('paper_id')
        if not title or not isinstance(identity,str) or not re.fullmatch('[0-9a-f]{40}',identity):continue
        year=row.get('year');year=year if isinstance(year,int) and not isinstance(year,bool) and 1500<=year<=2200 else None
        byline=str(row.get('byline',''))[:1000]
        papers.append({'id':'cp_'+identity,'title':title,'authors':[a.strip() for a in byline.split(',') if a.strip()][:30],
                       'byline':byline,'year':year,'paper_url':'https://www.semanticscholar.org/paper/'+identity,'pdf_url':'',
                       'origin':row.get('origin') is True,'metadata_status':'unverified','abstract_status':'source_not_provided'})
    status=data.get('status','source_unavailable')
    if not papers and status=='candidates_found':status='source_format_unrecognized'
    return {'provider':'Connected Papers','source_url':url,'retrieved_at':stamp(),'papers':papers,
            'status':'candidates_found' if papers else status,
            'expanded_search':False,'maximum_graph_pages':1,'similarity_edges_imported':False,
            'warnings':['Connected Papers recommendations are similarity-based candidates; identities, topical relevance, years and real citation edges still require verification.']}


def collect(store,job):
    url=graph_url(job['context']['literature_search']['connected_papers_url']);started=time.monotonic()
    with _lock:
        cached=_cache.get(url)
        if cached and time.monotonic()-cached[0]<300:
            result=copy.deepcopy(cached[1]);result.update(reused=True,duration_seconds=0);return result
    cache_root=store.state/'cache';cache_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache_root,prefix='public-graph-',ignore_cleanup_errors=True) as folder:
        root=Path(folder);request=root/'request.json'
        atomic_json(request,{'url':url})
        if getattr(sys,'frozen',False):command=[sys.executable,'--connected-papers-worker',str(request)]
        else:command=[sys.executable,'-c','import packed_runtime; from backend.connected_papers import worker; worker()',str(request)]
        from .layout import app_dir
        import os
        env={**os.environ,'PYTHONUTF8':'1','PYTHONPATH':os.pathsep.join([str(app_dir(store.project)),str(app_dir(store.project)/'tests')])}
        process=subprocess.Popen(command,cwd=app_dir(store.project),env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        key=(str(store.project),job['id'])
        with _lock:_active[key]=process
        try:
            try:process.wait(timeout=45)
            except subprocess.TimeoutExpired:
                from .codex_runner import CodexRunner
                CodexRunner.stop_process(process)
            path=root/'response.json'
            data=json.loads(path.read_text('utf-8')) if path.is_file() and path.stat().st_size<=256*1024 else {'status':'source_unavailable'}
            result=sanitize(data,url)
        finally:
            with _lock:_active.pop(key,None)
        result['duration_seconds']=round(time.monotonic()-started,3)
        for paper in result['papers']:paper['source']={k:result[k] for k in ('provider','source_url','retrieved_at')};paper['source']['url']=url
        result['response_sha256']=hashlib.sha256(json.dumps(result['papers'],sort_keys=True).encode()).hexdigest()
        if result['status']=='candidates_found':
            with _lock:
                _cache[url]=(time.monotonic(),copy.deepcopy(result))
                while len(_cache)>4:_cache.pop(next(iter(_cache)))
        return result


def cancel(project,id):
    with _lock:process=_active.get((str(project),id))
    if process and process.poll() is None:
        from .codex_runner import CodexRunner
        CodexRunner.stop_process(process)


def worker(request_file=None):
    request_file=Path(request_file or sys.argv[-1]).resolve();root=request_file.parent
    source=graph_url(json.loads(request_file.read_text('utf-8'))['url'])
    atomic_json(root/'worker-status.json',{'phase':'initializing_runtime'})
    import clr,os,webview
    clr.AddReference('System.Windows.Forms');clr.AddReference('System.Drawing')
    lib=Path(webview.__file__).parent/'lib'
    for name in ['Core','WinForms']:clr.AddReference(str(lib/('Microsoft.Web.WebView2.'+name+'.dll')))
    os.environ['PATH']=str(lib/'runtimes/win-x64/native')+os.pathsep+os.environ.get('PATH','')
    from System.Drawing import Size
    from System.Threading import Thread,ThreadStart,ApartmentState
    from System.Diagnostics import Process
    from Microsoft.Web.WebView2.WinForms import WebView2,CoreWebView2CreationProperties
    from Microsoft.Web.WebView2.Core import CoreWebView2WebResourceContext,CoreWebView2PermissionState
    import System.Windows.Forms as F
    def main():
        form=F.Form();form.Text='Knowline · Public graph discovery';form.Size=Size(1200,800);form.Opacity=0;form.ShowInTaskbar=False
        view=WebView2();view.Dock=F.DockStyle.Fill;form.Controls.Add(view)
        props=CoreWebView2CreationProperties();props.UserDataFolder=str(root/'profile')
        props.AdditionalBrowserArguments='--disk-cache-size=4194304 --media-cache-size=1048576 --disable-crash-reporter';view.CreationProperties=props
        task=None;ready=False;started=time.monotonic();blocked_hosts={};navigation_result={}
        def finish(data):atomic_json(root/'response.json',data);timer.Stop();form.Close()
        def navigation(sender,args):
            try:graph_url(str(args.Uri))
            except DomainError:args.Cancel=True;finish({'status':'redirect_scope_blocked'})
        def resource(sender,args):
            p=urlsplit(str(args.Request.Uri))
            if p.scheme!='https' or p.hostname not in HOSTS or p.username or p.password or p.port not in {None,443}:
                blocked_hosts[p.hostname or 'invalid']=blocked_hosts.get(p.hostname or 'invalid',0)+1
                args.Response=view.CoreWebView2.Environment.CreateWebResourceResponse(None,403,'Blocked','Content-Type: text/plain')
        def navigated(sender,args):
            navigation_result.update(success=bool(args.IsSuccess),web_error=str(args.WebErrorStatus))
        def denied(sender,args):args.State=CoreWebView2PermissionState.Deny
        def download(sender,args):args.Cancel=True
        def popup(sender,args):args.Handled=True
        def initialize(sender,args):
            nonlocal ready
            if not args.IsSuccess:finish({'status':'webview2_unavailable'});return
            core=view.CoreWebView2
            core.Settings.AreDevToolsEnabled=False;core.Settings.AreHostObjectsAllowed=False;core.Settings.IsPasswordAutosaveEnabled=False;core.Settings.IsGeneralAutofillEnabled=False
            core.NavigationStarting+=navigation;core.NavigationCompleted+=navigated;core.NewWindowRequested+=popup;core.PermissionRequested+=denied;core.DownloadStarting+=download
            core.AddWebResourceRequestedFilter('*',CoreWebView2WebResourceContext.All);core.WebResourceRequested+=resource
            ready=True;core.Navigate(source);form.Hide()
            atomic_json(root/'worker-status.json',{'phase':'reading_public_graph'})
        def tick(sender,args):
            nonlocal task
            try:
                if time.monotonic()-started>35:finish({'status':'source_unavailable'});return
                if not ready:return
                if task is not None:
                    if not task.IsCompleted:return
                    value=json.loads(json.loads(task.Result));task=None
                    atomic_json(root/'worker-status.json',{'phase':'reading_public_graph','status':value.get('status'),'candidate_count':len(value.get('papers',[])),'blocked_hosts':blocked_hosts,'navigation':navigation_result})
                    if value['status']!='loading':finish(value);return
                task=view.CoreWebView2.ExecuteScriptAsync(SCRIPT)
            except Exception:finish({'status':'source_format_unrecognized'})
        timer=F.Timer();timer.Interval=750;timer.Tick+=tick;timer.Start()
        view.CoreWebView2InitializationCompleted+=initialize
        def shown(sender,args):view.EnsureCoreWebView2Async(None)
        form.Shown+=shown
        def closing(sender,args):
            timer.Stop()
            if ready:
                pid=int(view.CoreWebView2.BrowserProcessId);view.Dispose()
                try:Process.GetProcessById(pid).WaitForExit(3000)
                except Exception:pass
        form.FormClosing+=closing;F.Application.Run(form)
    thread=Thread(ThreadStart(main));thread.SetApartmentState(ApartmentState.STA);thread.Start()
    # Python.NET's blocking Join can hold the GIL while the STA delegate needs it.
    while thread.IsAlive:time.sleep(.1)
