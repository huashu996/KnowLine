"""A persistent bridge owned by the local tool-capable AI, never the browser."""
import json
import os
import subprocess
import sys
import time
import threading
import urllib.request
import urllib.error
import socket
from pathlib import Path
from .layout import data_path, identity, app_dir
from .safety import DomainError, atomic_json, contained
from .store import uid
from .research_policy import total_budget
from .agent_connection import (CONNECT_SECONDS, PROBE_SECONDS, LOCAL_REQUEST_SECONDS,
                               read_adapter, prepare_adapter, same_adapter, connect_lock)


def request_timeout(path):
    # Ingestion includes full-text acquisition, metadata enrichment and result
    # validation. It is task execution, not a bounded control-plane request.
    # A socket read deadline here would reintroduce a total task time limit.
    if path.startswith('/jobs/') and path.endswith('/ingest'):
        return None
    if path == '/agent/launch':
        return 30
    return LOCAL_REQUEST_SECONDS


def launch(project, port, config_path):
    if getattr(sys,'frozen',False):argv=[sys.executable,'--cli','--project',str(project),'--port',str(port),'agent','worker','--command-file',str(config_path)]
    else:argv=[sys.executable,'-m','backend.cli','--project',str(project),'--port',str(port),'agent','worker','--command-file',str(config_path)]
    return subprocess.Popen(argv,cwd=app_dir(project),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))


def execute(command, prompt, project, prompt_file, result_file, heartbeat, timeout):
    prompt_file.write_text(prompt,encoding='utf-8')
    argv=[arg.replace('{project}',str(project)).replace('{prompt_file}',str(prompt_file)).replace('{result_file}',str(result_file)) for arg in command]
    # argv only, never a shell. Each child inherits its own client's local permissions.
    with prompt_file.open('rb') as prompt_input,subprocess.Popen(argv,cwd=project,stdin=prompt_input,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),env={**os.environ,'PYTHONUTF8':'1'}) as process:
        try:
            started=time.monotonic()
            while process.poll() is None:
                if timeout is not None and time.monotonic()-started>timeout:raise DomainError('agent_execution_timeout',409)
                heartbeat();time.sleep(2)
            if process.returncode:raise DomainError('agent_execution_failed',409)
        except BaseException:
            if process.poll() is None:
                from .codex_runner import CodexRunner
                CodexRunner.stop_process(process)
            raise


def run(args):
    # The bridge runs hidden; report startup failures to the waiting connector
    # instead of making an already exited worker look like a slow probe.
    if args.action == 'connect':
        started = time.monotonic()
        with connect_lock(data_path(Path(args.project).resolve(), '.knowledge/agent-worker')):
            result = _run(args, deadline=started + CONNECT_SECONDS)
            result['elapsed_seconds'] = round(time.monotonic() - started, 2)
            return result
    if args.action != 'worker':
        return _run(args)
    state_file = data_path(Path(args.project).resolve(), '.knowledge/agent-worker/startup.json')
    state = {'generation': None, 'pid': os.getpid(), 'state': 'starting'}
    try:
        config = read_adapter(args.command_file)
        state['generation'] = config.get('generation')
        atomic_json(state_file, state)
        return _run(args)
    except Exception as exc:
        state.update(state='failed', code=getattr(exc, 'code', 'agent_worker_start_failed'))
        try:atomic_json(state_file, state)
        except OSError:pass
        raise


def _run(args, deadline=None):
    project=Path(args.project).resolve();base=f'http://127.0.0.1:{args.port}/api/v1'
    # Local credentials must never follow a system HTTP proxy or redirects.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def request(path,body=None,secret=False):
        headers={'Content-Type':'application/json'}
        if body is not None:
            body=dict(body)
            headers['X-KW-Token']=token;body.setdefault('operation_id',uid('op'))
        if secret:headers['X-KW-Agent-Key']=json.loads(data_path(project,'.knowledge/agent-local.json').read_text('utf-8'))['key']
        timeout=request_timeout(path)
        if deadline is not None:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise DomainError('agent_probe_timeout',409)
            timeout=min(timeout or remaining,remaining)
        try:
            with opener.open(urllib.request.Request(base+path,json.dumps(body).encode() if body is not None else None,headers),timeout=timeout) as response:return json.load(response)
        except urllib.error.HTTPError as exc:
            error=json.load(exc)
            import re
            detail=(error.get('params') or {}).get('reason')
            params={'reason':detail} if isinstance(detail,str) and re.fullmatch(r'[a-z][a-z0-9_]{0,119}',detail) else {}
            raise DomainError(error.get('code','agent_request_failed'),exc.code,**params)
        except (TimeoutError,socket.timeout) as exc:
            raise DomainError('agent_request_timeout',409) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason,(TimeoutError,socket.timeout)):
                raise DomainError('agent_request_timeout',409) from exc
            raise
    service=None
    try:health=request('/health')
    except urllib.error.URLError:
        if args.action!='connect':raise
        # One-call connection also starts this instance's normal single-writer service.
        if getattr(sys,'frozen',False):argv=[sys.executable,'--cli','--project',str(project),'--port',str(args.port),'serve']
        else:argv=[sys.executable,'-m','backend.cli','--project',str(project),'--port',str(args.port),'serve']
        service=subprocess.Popen(argv,cwd=app_dir(project),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        service_deadline=min(deadline or float('inf'),time.monotonic()+30)
        while True:
            if service.poll() is not None:raise DomainError('agent_service_unavailable',409)
            try:health=request('/health');break
            except urllib.error.URLError:
                if time.monotonic()>service_deadline:raise DomainError('agent_service_unavailable',409)
                time.sleep(.3)
    if health['project_id']!=identity(project):raise DomainError('project_mismatch',409)
    token=request('/session')['token']
    if args.action=='status':return request('/agent/status')
    if args.action=='disconnect':
        local=json.loads(data_path(project,'.knowledge/agent-worker.json').read_text('utf-8'))
        return request('/agent/disconnect',{'agent_id':local['agent_id']},True)
    if args.action=='connect':
        folder=data_path(project,'.knowledge/agent-worker');folder.mkdir(exist_ok=True)
        config_path=folder/'adapter.json'
        current=request('/agent/status')
        if not args.builtin and not args.command_file and current['available']:
            return {**current,'reused':True}
        if args.builtin:
            from .codex_runner import executable
            exe=executable()
            if not exe:raise DomainError('agent_command_missing',409)
            config={'argv':[exe,'exec','--skip-git-repo-check','--sandbox','workspace-write','-c','approval_policy="never"','-C','{project}','-'],'builtin':'codex','name':'本地智能体'}
        else:
            if not args.command_file and not config_path.is_file():raise DomainError('agent_command_file_required',409)
            config=read_adapter(args.command_file or config_path)
        config=prepare_adapter(config,project)
        if current['available'] and config_path.is_file():
            saved=read_adapter(config_path)
            if same_adapter(config,saved):return {**current,'reused':True}
        # Check installation/flags/login before replacing a working binding.
        config=prepare_adapter(config,project,check_client=True)
        config['generation']=uid('binding')
        # Local command/config never goes into HTTP responses or published snapshots.
        atomic_json(config_path,config)
        from .agent_bridge import protect_local_file
        protect_local_file(config_path)
        launched=request('/agent/launch',{'generation':config['generation']},True)
        worker_pid=launched['pid']
        # Completion is executable-probe success, never just process launch/registration.
        deadline=deadline or time.monotonic()+CONNECT_SECONDS
        while time.monotonic()<deadline:
            status=request('/agent/status')
            if status.get('binding_id')!=config['generation']:raise DomainError('agent_binding_changed',409)
            local_file=data_path(project,'.knowledge/agent-worker.json')
            if local_file.exists():
                local=json.loads(local_file.read_text('utf-8'))
                if status['available'] and status.get('session_id')==local['agent_id']:
                    return {'state':'connected','pid':local.get('pid'),'service_pid':service.pid if service else None,'message':'本地智能体已完成工具执行探测，持续任务桥已启动。'}
            if status.get('connection_phase')=='failed':
                raise DomainError(status.get('error_code') or 'agent_worker_start_failed',409)
            startup_file=folder/'startup.json'
            if startup_file.exists():
                startup=json.loads(startup_file.read_text('utf-8'))
                if (startup.get('generation')==config['generation'] and startup.get('pid')==worker_pid
                        and startup.get('state')=='failed'):
                    raise DomainError(startup.get('code','agent_worker_start_failed'),409)
            time.sleep(1)
        raise DomainError('agent_probe_timeout',409)
    config=prepare_adapter(read_adapter(args.command_file),project,check_client=True);command=config['argv']
    if config.get('builtin')=='codex':
        from .codex_runner import execution_environment
        os.environ.update(execution_environment())
    probe=request('/agent/probe',{'name':config.get('name','本地智能体'),'generation':config.get('generation')},True)
    prompt_file=data_path(project,'.knowledge/agent-probe/prompt.txt')
    execute(command,probe['prompt'],project,prompt_file,Path(probe['result']),lambda:None,PROBE_SECONDS)
    agent_id=probe['agent_id'];request('/agent/register',{'agent_id':agent_id},True)
    atomic_json(data_path(project,'.knowledge/agent-worker.json'),{'agent_id':agent_id,'pid':os.getpid()})
    atomic_json(data_path(project,'.knowledge/agent-worker/startup.json'),
                {'generation':config.get('generation'),'pid':os.getpid(),'state':'connected'})
    active={};active_lock=threading.Lock();heartbeat_error=threading.Event();stop=threading.Event()
    def heartbeat():
        if stop.is_set() or heartbeat_error.is_set():raise DomainError('agent_disconnected',409)
        # Connection liveness is independent of any one job's lease.
        return request('/agent/heartbeat',{'agent_id':agent_id},True)
    def keepalive():
        while not stop.wait(5):
            try:heartbeat()
            except Exception:
                heartbeat_error.set();return
    thread=threading.Thread(target=keepalive,daemon=True);thread.start()
    def execute_delivery(delivery,state,previous):
        job=delivery['job'];body={'agent_id':agent_id,'lease':delivery['lease'],'base_revision':job['revision']}
        def job_heartbeat():
            if stop.is_set() or heartbeat_error.is_set() or state['stop'].is_set():raise DomainError('agent_disconnected',409)
            return request('/agent/heartbeat',{'agent_id':agent_id,'job_id':job['id'],'lease':delivery['lease']},True)
        try:
            # A cancelled attempt must exit before a retry touches the same output.
            # Other jobs never wait on these predecessor threads.
            for prior in previous:prior['thread'].join()
            job_heartbeat()
            output=contained(project,job['context']['output_dir']);result_file=output/'result.json'
            # A stale manifest from a prior attempt must never be accepted as a new execution.
            if result_file.exists():result_file.replace(output/'result.previous.json')
            budget=total_budget(job)
            timeout=None if budget is None else delivery.get('timeout_seconds') or budget
            job_command=list(command)
            if config.get('builtin')=='codex':
                network=str(job['context'].get('external_network','')).startswith('user_requested')
                job_command[-1:-1]=['-c','sandbox_workspace_write.network_access='+str(network).lower()]
                if network:job_command[-1:-1]=['-c','web_search="live"']
                if job['task']=='paper_relationships':
                    job_command[-1:-1]=['-c','features.multi_agent=true','-c','agents.enabled=true',
                                       '-c','agents.max_concurrent_threads_per_session=2']
            execute(job_command,delivery['prompt'],project,output/'agent-prompt.txt',result_file,job_heartbeat,timeout)
            job_heartbeat()
            if not result_file.is_file():raise DomainError('agent_result_missing',409)
            body['manifest']=json.loads(result_file.read_text('utf-8'))
            request('/jobs/'+job['id']+'/ingest',body,True)
        except Exception as exc:
            # Cancellation/stale leases affect only this child, never its siblings.
            reason='智能体执行或成果校验失败：'+getattr(exc,'code',type(exc).__name__)
            detail=getattr(exc,'params',{}).get('reason')
            if detail=='nearest_work_identity':
                reason+='；相关研究对比项的来源身份不一致，请将论文证据与代码、综合卡的补充依据分开。已生成文件可先下载。'
            elif detail=='dataset_split_budget_comparability':
                reason+='；实验对照清单缺少统一数据、划分、预算、失败样本统计或阈值状态字段。已生成文件可先下载。'
            elif detail:
                reason+='；具体检查项：'+detail
            if getattr(exc,'code',None)=='agent_result_missing':
                reason='智能体未生成最终成果清单，任务尚未通过核验。'
                try:
                    stage=output/'stage-result.json'
                    if stage.is_file() and stage.stat().st_size<=256000:
                        progress=json.loads(stage.read_text('utf-8-sig'))
                        if progress.get('job_id')==job['id']:
                            import re
                            codes=[b.get('code','') for b in progress.get('blockers',[]) if isinstance(b,dict)]
                            codes=[c for c in codes if isinstance(c,str) and re.fullmatch(r'[a-z][a-z0-9_]{0,79}',c)]
                            if codes:reason+=' 阶段核验原因：'+', '.join(dict.fromkeys(codes))[:500]
                except (OSError,ValueError,TypeError):pass
            try:request('/jobs/'+job['id']+'/fail',{**body,'reason':reason},True)
            except DomainError as failure:
                if failure.code not in {'agent_lease_invalid','agent_disconnected','job_not_found'}:
                    # An unreportable execution must not leave a live, leased job
                    # forever. Restore the connection and its unfinished leases.
                    heartbeat_error.set()
            except Exception:heartbeat_error.set()
        finally:
            with active_lock:active.pop(delivery['lease'],None)
            # execute() has stopped/joined the child before acknowledging cleanup.
            try:request('/agent/heartbeat',{'agent_id':agent_id,'finished_lease':delivery['lease']},True)
            except Exception:pass
    try:
        while True:
            heartbeat();delivery=request('/agent/next',{'agent_id':agent_id},True)
            if not delivery['job']:stop.wait(1);continue
            state={'job_id':delivery['job']['id'],'stop':threading.Event()}
            with active_lock:
                previous=[s for s in active.values() if s['job_id']==state['job_id']]
                for prior in previous:prior['stop'].set()
                state['thread']=threading.Thread(target=execute_delivery,args=(delivery,state,previous),daemon=True)
                active[delivery['lease']]=state
            state['thread'].start()
    finally:
        stop.set();thread.join(timeout=1)
        with active_lock:children=list(active.values())
        deadline=time.monotonic()+20
        for child in children:child['thread'].join(timeout=max(0,deadline-time.monotonic()))
        try:request('/agent/disconnect',{'agent_id':agent_id},True)
        except Exception:pass
