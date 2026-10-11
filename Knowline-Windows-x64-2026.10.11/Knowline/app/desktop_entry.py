"""Native Windows window over the same project; no model runtime or second database."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request


def project_root(explicit=None):
    if explicit:
        project=Path(explicit).resolve()
    else:
        location=Path(sys.executable if getattr(sys,'frozen',False) else __file__).resolve()
        project=next((p for p in location.parents if (p/'app/project-layout.json').is_file() or ((p/'kw.cmd').is_file() and (p/'AGENTS.md').is_file())),None)
    from backend.layout import project_root as canonical, app_dir
    if project:project=canonical(project)
    if not project or not (app_dir(project)/'AGENTS.md').is_file() or not (app_dir(project)/'kw.cmd').is_file():
        raise RuntimeError('Select a Knowline project containing AGENTS.md and kw.cmd with --project.')
    return project


def connection(project):
    from backend.layout import data_path,app_dir
    config_file=data_path(project,'.knowledge/config.json')
    config=json.loads(config_file.read_text('utf-8')) if config_file.exists() else {}
    marker=app_dir(project)/'project-layout.json'
    defaults=json.loads(marker.read_text('utf-8')) if marker.exists() else {}
    port=config.get('port',defaults.get('default_port',8765))
    if not isinstance(port,int) or not 1024<=port<=65535:raise RuntimeError('Invalid project port')
    if not config_file.exists() and not health(f'http://127.0.0.1:{port}',project):
        with socket.socket() as probe:
            try:probe.bind(('127.0.0.1',port))
            except OSError:
                with socket.socket() as spare:
                    spare.bind(('127.0.0.1',0));port=spare.getsockname()[1]
                config_file.parent.mkdir(parents=True,exist_ok=True)
                config_file.write_text(json.dumps({'schema_version':1,'resource_root':'resource/incoming','ui_locale':'zh','port':port,'external_network':False,'code_roots':[],'inference_provider':'none','retrieval':'local_fts5','backup_retention':'disabled'}),encoding='utf-8')
    return f'http://127.0.0.1:{port}',port


def health(url,project):
    try:
        with urllib.request.urlopen(url+'/api/v1/health',timeout=1) as response:data=json.load(response)
        from backend.layout import identity
        return data.get('app')=='local-knowledge-workbench' and data.get('project_id')==identity(project)
    except OSError:return False


def ensure_service(project):
    url,port=connection(project)
    if health(url,project):return url,None
    with socket.socket() as probe:
        try:probe.bind(('127.0.0.1',port))
        except OSError:raise RuntimeError('Port belongs to another service; change this project port. No process was stopped.')
    from backend.layout import app_dir,data_path
    bundle=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))
    ui_root=app_dir(project)/'dist' if (app_dir(project)/'dist/index.html').is_file() else bundle/'dist'
    if not (ui_root/'index.html').is_file():raise RuntimeError('Frontend build missing')
    arguments=['--project',str(project),'--port',str(port),'serve','--ui-root',str(ui_root)]
    command=[sys.executable,'--cli',*arguments] if getattr(sys,'frozen',False) else [sys.executable,'-m','backend.cli',*arguments]
    data_path(project,'.knowledge').mkdir(parents=True,exist_ok=True)
    env=dict(os.environ)
    if not getattr(sys,'frozen',False):env['PYTHONPATH']=str(Path(__file__).parent)+os.pathsep+env.get('PYTHONPATH','')
    process=subprocess.Popen(command,cwd=project,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    for _ in range(120):
        if health(url,project):return url,process
        if process.poll() is not None:raise RuntimeError('Project service failed; read .knowledge/desktop-server.log')
        time.sleep(.25)
    process.terminate();process.wait(timeout=10)
    raise RuntimeError('Project service startup timed out')


def main():
    if len(sys.argv)>1 and sys.argv[1]=='--connected-papers-worker':
        from backend.connected_papers import worker
        worker(sys.argv[2]);return
    if len(sys.argv)>1 and sys.argv[1]=='--institution-worker':
        from backend.institutional_browser import run
        run(sys.argv[2]);return
    if len(sys.argv)>1 and sys.argv[1] in {'--cli','--semantic-worker'}:
        semantic_worker=sys.argv[1]=='--semantic-worker'
        sys.argv=[sys.argv[0],*sys.argv[2:]]
        # A windowed executable still writes machine-readable CLI output to inherited handles.
        if sys.stdout is None or sys.stderr is None:
            import ctypes,msvcrt
            ctypes.windll.kernel32.GetStdHandle.restype=ctypes.c_void_p
            def stream(number):
                handle=ctypes.windll.kernel32.GetStdHandle(number)
                if not handle or handle==ctypes.c_void_p(-1).value:return open(os.devnull,'w',encoding='utf-8')
                return os.fdopen(msvcrt.open_osfhandle(handle,os.O_WRONLY),'w',encoding='utf-8',closefd=False)
            if sys.stdout is None:sys.stdout=stream(-11)
            if sys.stderr is None:sys.stderr=stream(-12)
            if semantic_worker and sys.stdin is None:
                handle=ctypes.windll.kernel32.GetStdHandle(-10)
                sys.stdin=os.fdopen(msvcrt.open_osfhandle(handle,os.O_RDONLY),'r',encoding='utf-8',closefd=False)
        for output in [sys.stdout,sys.stderr]:
            if hasattr(output,'reconfigure'):output.reconfigure(encoding='utf-8')
        if semantic_worker:
            parser=argparse.ArgumentParser();parser.add_argument('--project',required=True)
            args=parser.parse_args();from backend.semantic import serve
            serve(project_root(args.project));return
        from backend.cli import run
        run();return
    if len(sys.argv)>1 and sys.argv[1]=='--word-worker':
        parser=argparse.ArgumentParser();parser.add_argument('--word-worker',required=True);parser.add_argument('--project',required=True)
        args=parser.parse_args();from backend.word_bridge import worker
        worker(args.project,args.word_worker);return
    parser=argparse.ArgumentParser();parser.add_argument('--project');parser.add_argument('--self-test-report')
    args=parser.parse_args();project=project_root(args.project);url,owned=ensure_service(project)
    import webview
    # No custom native bridge is exposed; writes use the existing token/revision API.
    webview.settings['ALLOW_DOWNLOADS']=True
    window=webview.create_window('Knowline · 共享研究工作台',url+'/?ui='+str(time.time_ns()),width=1440,height=960,min_size=(800,600),hidden=False,minimized=bool(args.self_test_report),focus=not bool(args.self_test_report),text_select=True)
    def verify():
        report=Path(args.self_test_report).resolve();report.relative_to(project);report.parent.mkdir(parents=True,exist_ok=True)
        try:
            for _ in range(80):
                data=window.evaluate_js("({title:document.title,sections:[...document.querySelectorAll('.nav-caption')].map(e=>e.textContent),resources:document.querySelectorAll('.resource-row').length,url:location.href,refreshButtons:[...document.querySelectorAll('button')].filter(e=>e.textContent.includes('刷新界面')).length,modelInputs:document.querySelectorAll('input[type=password]').length})")
                if len(data.get('sections',[]))>=6 and any(name in data.get('sections',[]) for name in ['方案','Proposal']):break
                time.sleep(.25)
            with urllib.request.urlopen(url+'/api/v1/project/catalog',timeout=3) as response:catalog_data=json.load(response)
            catalog={'resource_count':len(catalog_data['resources']),'domain_count':len(catalog_data['domains']),'project_name':catalog_data['project_name']}
            data.update(catalog)
            data.update(passed=len(data.get('sections',[]))>=6 and any(name in data.get('sections',[]) for name in ['方案','Proposal']) and data['modelInputs']==0 and catalog['resource_count']>=0,renderer='edgechromium',project=str(project))
            report=Path(args.self_test_report).resolve();report.relative_to(project)
            report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        except Exception as exc:report.write_text(json.dumps({'passed':False,'error':str(exc)}),encoding='utf-8')
        finally:window.destroy()
    if args.self_test_report:window.events.loaded+=verify
    from backend.layout import data_path,app_dir
    profile='.knowledge/desktop-self-test-profile' if args.self_test_report else '.knowledge/desktop-profile'
    storage=data_path(project,profile);storage.mkdir(parents=True,exist_ok=True)
    icon=app_dir(project)/'public/knowline.ico'
    if not icon.exists():icon=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'public/knowline.ico'
    os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']=os.environ.get('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS','')+' --disk-cache-size=16777216 --media-cache-size=8388608'
    try:webview.start(gui='edgechromium',icon=str(icon) if icon.exists() else None,private_mode=False,storage_path=str(storage),debug=False)
    finally:
        # Leave a normal project's service available for Codex after closing its window.
        if args.self_test_report and owned and owned.poll() is None:
            subprocess.run(['taskkill','/PID',str(owned.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
            owned.wait(timeout=10)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        if '--self-test-report' in sys.argv:
            target=Path(sys.argv[sys.argv.index('--self-test-report')+1]);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps({'passed':False,'error':str(exc)}),encoding='utf-8')
        if sys.stderr is not None:print(str(exc),file=sys.stderr)
        elif '--self-test-report' not in sys.argv and (len(sys.argv)==1 or '--project' in sys.argv):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0,str(exc),'知序启动失败',0x10)
        sys.exit(1)
