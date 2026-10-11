"""Project-local authenticated agent routing. No provider discovery or fallback."""
import asyncio
import hashlib
import json
import secrets
import time
from .safety import DomainError, atomic_json, contained
from .store import now, uid
from .codex_runner import instructions
from .research_policy import total_budget

TASKS = ['read_resources','compare_resources','translate_resources','analyze_resources',
         'discover_papers','paper_relationships','refresh_graph_citations','import_graph_papers',
         'verify_paper_metadata','build_knowledge','update_knowledge','copy_office_selection',
         'replicate_paper_figure','proposal_word','proposal_ppt']


def protect_local_file(path):
    import os
    if os.name=='nt':
        import csv, subprocess, io
        who=subprocess.run(['whoami','/user','/fo','csv','/nh'],capture_output=True,text=True,check=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        sid=list(csv.reader(io.StringIO(who.stdout)))[0][1]
        subprocess.run(['icacls',str(path),'/inheritance:r','/grant:r','*'+sid+':F'],capture_output=True,check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    else:path.chmod(0o600)


class AgentBridge:
    def __init__(self, store, write, compatibility):
        self.store, self.write, self.compatibility = store, write, compatibility
        self.key = secrets.token_urlsafe(32)
        self.file = store.state / 'agent-local.json'
        # Only local filesystem callers receive this credential. Never publish in catalog/session.
        atomic_json(self.file, {'protocol': 1, 'key': self.key})
        protect_local_file(self.file)
        self.selected = None
        self.pending = {}
        self.routes = {}
        self.monitor = None
        self.binding = store.state/'agent-worker'/'adapter.json'
        self.recovery = set()
        self.worker = None
        self.last_launch = 0
        self.worker_generation = None
        compatibility.external_dispatch=self.dispatch_prepared

    async def dispatch_prepared(self,job,info,started):
        elapsed=time.monotonic()-started
        budget=total_budget(job)
        remaining=max(1,budget-elapsed-20) if budget is not None else None
        id=job['id']
        def dispatch():
            current=self.store.job(id)
            if self.status()['available']:
                self.routes[id]={'agent_id':self.selected['id'],'lease':None,'timeout_seconds':remaining,'preflight_seconds':round(elapsed,2)}
                status='queued';message='前置核验已完成，等待本地智能体领取剩余任务。'
            else:
                self.recovery.add(id);status='waiting_user';message='前置核验已完成，等待绑定的本地智能体上线。'
            self.store.db.execute('UPDATE jobs SET status=?,revision=revision+1,updated_at=? WHERE id=?',(status,now(),id))
            current=self.store.job(id);self.store.event('job',id,current['revision']);self.info(id,status,message)
        await self.write('agent-prepared:'+id,{'operation_id':uid('op')},dispatch)

    async def startup(self):
        # Process leases cannot survive a server restart. Persisted binding can.
        for row in self.store.rows("SELECT id FROM jobs WHERE status IN ('queued','running')"):
            job=self.store.job(row['id'])
            if job['context'].get('inference_provider')=='project_local_agent':
                await self.transition(job['id'],'interrupted','软件重启，等待原绑定智能体恢复。')
                self.recovery.add(job['id']);self.info(job['id'],'interrupted','软件重启，任务等待原绑定执行端恢复。')
        for file in (self.store.state/'jobs').glob('*/agent-execution.json'):
            saved=json.loads(file.read_text('utf-8'))
            if saved.get('status') in {'queued','running'} or saved.get('resumable'):
                id=file.parent.name
                if id in self.recovery:continue
                try:
                    if self.store.job(id)['status'] in {'queued','running','interrupted','waiting_user'}:
                        if self.store.job(id)['status']!='waiting_user':await self.transition(id,'interrupted','软件重启，等待原绑定智能体恢复。')
                        self.recovery.add(id)
                except DomainError:pass
        self.monitor=asyncio.create_task(self.watch())

    def restore(self):
        if not self.binding.exists() or time.monotonic()-self.last_launch<30:return
        config=json.loads(self.binding.read_text('utf-8'))
        generation=config.get('generation')
        if self.worker and self.worker.poll() is None and self.worker_generation==generation:return
        from .agent_worker import launch
        self.last_launch=time.monotonic()
        try:
            self.worker=launch(self.store.project,self.store.config['port'],self.binding)
            self.worker_generation=generation
        except OSError:pass

    async def launch(self,body):
        config=json.loads(self.binding.read_text('utf-8'))
        if body.get('generation')!=config.get('generation'):raise DomainError('agent_binding_changed',409)
        if self.worker and self.worker.poll() is None and self.worker_generation==config.get('generation'):return {'pid':self.worker.pid}
        await self.disconnect()
        self.last_launch=0
        self.restore()
        if not self.worker or self.worker.poll() is not None:raise DomainError('agent_worker_start_failed',409)
        return {'pid':self.worker.pid}

    def authenticate(self, request):
        if not secrets.compare_digest(request.headers.get('x-kw-agent-key',''), self.key):
            raise DomainError('agent_local_credential_required',403)

    def status(self):
        live = bool(self.selected and self.selected.get('verified') and time.monotonic()-self.selected['heartbeat'] < 20)
        bound=self.binding.exists()
        try:binding=json.loads(self.binding.read_text('utf-8')) if bound else {}
        except (OSError,ValueError):binding={}
        state = 'connected' if live else 'disconnected' if self.selected or bound else 'not_connected'
        return {'state':state,'available':live,'bound':bound,'execution_timeout_seconds':None,'execution_policy':'until_complete_or_cancelled','binding_id':binding.get('generation'),'session_id':self.selected['id'] if live else None,'name':self.selected['name'] if self.selected else binding.get('name'),
                'message':{'connected':'本地智能体已连接，可执行任务；成果通过校验后回流。',
                           'disconnected':'绑定的本地智能体暂时离线，正在等待自动恢复；任务不会切换到其他执行器。',
                           'not_connected':'尚未连接本地智能体。请在本地 AI 项目中要求“将本地智能体连接到知序”。'}[state]}

    async def begin(self, body):
        generation=body.get('generation')
        if generation and generation!=json.loads(self.binding.read_text('utf-8')).get('generation'):raise DomainError('agent_binding_changed',409)
        name=body.get('name','本地智能体')
        if not isinstance(name,str) or not 1<=len(name)<=80:raise DomainError('invalid_request')
        id=uid('agent');nonce=secrets.token_urlsafe(32)
        folder=self.store.state/'agent-probe';folder.mkdir(exist_ok=True)
        # A single bounded challenge; replacing a probe never changes the current selection.
        source=folder/'challenge.json';result=folder/'proof.json'
        if result.exists():result.unlink()
        atomic_json(source,{'nonce':nonce,'agent_id':id})
        self.pending={id:{'name':name,'nonce':nonce,'expires':time.monotonic()+120,'result':result,'generation':generation}}
        return {'agent_id':id,'source':str(source),'result':str(result),
                'prompt':f'这是知序本地工具执行探测。读取 {source}，计算 nonce 的 UTF-8 SHA256。用本地文件工具向 {result} 写 JSON：agent_id 为读到的 agent_id，proof 为计算的十六进制 SHA256。不要注册或运行其他任务。'}

    async def register(self, body):
        id=body.get('agent_id');pending=self.pending.get(id)
        if not pending or pending['expires']<time.monotonic():raise DomainError('agent_probe_expired',409)
        if pending.get('generation') and pending['generation']!=json.loads(self.binding.read_text('utf-8')).get('generation'):raise DomainError('agent_binding_changed',409)
        try:
            result=pending['result']
            if result.is_symlink() or result.stat().st_size>4096:raise ValueError()
            proof=json.loads(result.read_text('utf-8'))
        except (OSError,ValueError):raise DomainError('agent_probe_failed',409)
        if proof!={'agent_id':id,'proof':hashlib.sha256(pending['nonce'].encode()).hexdigest()}:raise DomainError('agent_probe_failed',409)
        await self.disconnect()
        self.selected={'id':id,'name':pending['name'],'heartbeat':time.monotonic(),'verified':True}
        self.pending={}
        if not self.monitor or self.monitor.done():self.monitor=asyncio.create_task(self.watch())
        for job_id in list(self.recovery):
            try:
                job=self.store.job(job_id)
                if job['status'] in {'interrupted','waiting_user'}:await self.start(job_id,{'operation_id':uid('op'),'base_revision':job['revision']})
            except DomainError:pass
        self.recovery.clear()
        return {'agent_id':id,**self.status()}

    def check_agent(self, body):
        if not self.status()['available'] or body.get('agent_id')!=self.selected['id']:raise DomainError('agent_disconnected',409)

    async def heartbeat(self, body):
        if not self.selected or body.get('agent_id')!=self.selected['id'] or not self.selected['verified']:raise DomainError('agent_disconnected',409)
        if time.monotonic()-self.selected['heartbeat']>=20:
            await self.disconnect();raise DomainError('agent_disconnected',409)
        self.selected['heartbeat']=time.monotonic()
        if body.get('job_id'):
            route=self.routes.get(body['job_id'])
            if not route or route['agent_id']!=body['agent_id'] or route['lease']!=body.get('lease'):raise DomainError('agent_lease_invalid',409)
        return self.status()

    async def disconnect(self):
        if self.selected:self.selected['verified']=False
        for id in list(self.routes):
            try:
                await self.cancel(id)
                # Explicit cancellation clears recovery. A connection loss
                # restores it only after the old lease has been invalidated.
                if self.store.job(id)['status']=='interrupted':
                    self.recovery.add(id)
                    self.info(id,'interrupted','本地智能体已断开，等待原绑定执行端恢复。')
            except DomainError:pass  # Deleted jobs have no remaining owner.

    async def watch(self):
        while True:
            await asyncio.sleep(5)
            if self.selected and self.selected['verified'] and not self.status()['available']:await self.disconnect()
            if not self.status()['available']:self.restore()

    def job(self,id):
        job=self.compatibility.job(id)
        if job['task']=='import_graph_papers':return job
        file=self.store.state/'jobs'/id/'agent-execution.json'
        if file.exists():
            shared=job.get('execution') or {}
            execution=json.loads(file.read_text('utf-8'))
            execution['stages']={**shared.get('stages',{}),**execution.get('stages',{})}
            for key in ['preparation','citation_preflight','publication_preflight','discovery','queue_seconds']:
                if key in shared:execution[key]=shared[key]
            if shared.get('started_at'):execution['preflight_started_at']=shared['started_at']
            if shared.get('finished_at'):execution['preflight_finished_at']=shared['finished_at']
            job['execution']=execution
        return job

    def info(self,id,status,message,**details):
        path=self.store.state/'jobs'/id/'agent-execution.json'
        previous=json.loads(path.read_text('utf-8')) if path.exists() else {}
        if status in {'queued','waiting_user'}:
            previous={}
        if status=='running':details['started_at']=now()
        if status in {'completed','partial','failed','interrupted'}:details['finished_at']=now()
        atomic_json(path,{**previous,**details,'status':status,'message':message,'mode':'local_agent','resumable':id in self.recovery,'updated_at':now()})

    async def start(self,id,body):
        if self.store.job(id)['task'] in {'import_graph_papers','discover_papers','paper_relationships','verify_paper_metadata','build_knowledge','update_knowledge'}:
            # Fixed frozen-selection downloads never use a model, regardless of binding.
            # Other tasks reuse their original deterministic cache/preflight before dispatch.
            return await self.compatibility.start(id,body)
        if not self.status()['available']:
            def wait():
                job=self.store.job(id);self.store.check(job,body)
                if job['status'] not in {'completed','partial'}:
                    self.recovery.add(id);self.info(id,'waiting_user','任务等待绑定的本地智能体上线；恢复后自动执行。')
                return self.job(id)
            return await self.write('agent-wait:'+id,body,wait)
        def reserve():
            job=self.store.job(id);self.store.check(job,body)
            if job['status'] in {'queued','running','completed'}:return job
            from .skills import require_task_skill
            require_task_skill(self.store.project,job['task'])
            self.store.db.execute("UPDATE jobs SET status='queued',error=NULL,revision=revision+1,updated_at=? WHERE id=?",(now(),id))
            job=self.store.job(id);self.store.event('job',id,job['revision'])
            self.routes[id]={'agent_id':self.selected['id'],'lease':None}
            self.info(id,'queued','任务已交给当前本地智能体，等待领取。')
            return job
        await self.write('agent-dispatch:'+id,body,reserve)
        return self.job(id)

    async def next(self,body):
        self.check_agent(body)
        # Idle polling must not create persistent operation records. The actual
        # claim still rechecks status inside the single writer below.
        if not any(route['agent_id']==body['agent_id'] and not route['lease']
                   and self.store.job(id)['status']=='queued'
                   for id,route in self.routes.items()):
            return {'job':None}
        def claim():
            for id,route in self.routes.items():
                if route['agent_id']!=body['agent_id'] or route['lease']:continue
                job=self.store.job(id)
                if job['status']!='queued':continue
                route['lease']=secrets.token_urlsafe(24)
                route['claimed_at']=time.monotonic()
                self.store.db.execute("UPDATE jobs SET status='running',revision=revision+1,updated_at=? WHERE id=?",(now(),id))
                job=self.store.job(id);self.store.event('job',id,job['revision']);self.info(id,'running','本地智能体已领取任务，正在执行。')
                prompt=instructions(self.store,job,automatic=True)
                from .research_query import names
                discovery_file=names(job['context'].get('literature_search',{}))['discovery']
                if route.get('preflight_seconds') is not None and route.get('timeout_seconds') is not None:
                    prompt+=f'\n确定性前置流程已执行 {route["preflight_seconds"]} 秒，剩余执行预算 {round(route["timeout_seconds"])} 秒。先读取已生成的核验记忆与 {discovery_file}；不得重复发起 Google 学术发现请求。'
                elif route.get('preflight_seconds') is not None:
                    prompt+=f'\n本任务无总执行时限。先读取已生成的核验记忆与 {discovery_file}，不得重复发起已完成的发现请求。'
                return {'job':job,'lease':route['lease'],'prompt':prompt,'timeout_seconds':route.get('timeout_seconds')}
            return {'job':None}
        return await self.write('agent-next',body,claim)

    def guard(self,id,body,request):
        route=self.routes.get(id)
        if route:
            self.authenticate(request);self.check_agent(body)
            if route['agent_id']!=body.get('agent_id') or not route['lease'] or not secrets.compare_digest(route['lease'],body.get('lease','')):raise DomainError('agent_lease_invalid',409)
        elif self.selected:raise DomainError('agent_lease_invalid',409)

    async def accepted(self,id):
        route=self.routes.pop(id,None)
        job=self.store.job(id)
        elapsed=round(time.monotonic()-route['claimed_at'],2) if route and route.get('claimed_at') else None
        from .literature_results import failure_diagnostic
        self.info(id,job['status'],'智能体成果已通过校验并回流。' if job['status']=='completed' else '执行结果已校验并回流，仍有未完成范围；请查看结果提醒。',agent_seconds=elapsed,stages={'agent_seconds':elapsed},**failure_diagnostic(job))

    def ingest_result(self,id,body,request):
        self.guard(id,body,request)
        manifest=body.get('manifest')
        if isinstance(manifest,dict):
            for warning in (self.compatibility.describe(id) or {}).get('discovery',{}).get('warnings',[]):
                if warning not in manifest.setdefault('warnings',[]):manifest['warnings'].append(warning)
        accepted=self.store.ingest_job(id,body)
        if id in self.routes and accepted['task'] in {'build_knowledge','update_knowledge'} and accepted['status']=='completed':
            from .knowledge import assemble
            kb=self.store.kb(accepted['context']['scope']['kb_id'])
            assemble(self.store,kb['id'],{'base_revision':kb['revision'],'job_id':id})
        return accepted

    async def cancel(self,id):
        self.recovery.discard(id)
        route=self.routes.pop(id,None)
        if route:
            await self.transition(id,'interrupted','本地智能体断开或切换，执行租约已失效；请重新启动任务。')
            self.info(id,'interrupted','本次执行已中断；旧执行器不能提交结果。')
        else:await self.compatibility.cancel(id)

    async def claim(self,id,body):
        if self.selected:raise DomainError('agent_worker_required',409)
        return await self.compatibility.claim(id,body)

    async def fail(self,id,body):
        if id in self.routes:
            await self.transition(id,'failed',str(body.get('reason','智能体执行失败'))[:1500]);self.routes.pop(id,None)
            self.info(id,'failed','智能体执行或成果校验失败。')
            return self.job(id)
        return await self.compatibility.fail(id,body)

    async def transition(self,*args):return await self.compatibility.transition(*args)

    async def close(self):
        if self.monitor:self.monitor.cancel()
        await self.compatibility.close()
        await self.disconnect()
        if self.worker and self.worker.poll() is None:self.worker.terminate()
