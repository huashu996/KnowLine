import asyncio
import json
import os
import sys
import secrets
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from .store import Store, now, uid
from .safety import DomainError, atomic_json, contained, digest, directory_manifest, hash_bytes, json_text
from . import pdf


def create_app(project=None, resource_root=None, state_dir='.knowledge', watch=True, ui_root=None):
    from .layout import project_root, app_dir,identity
    project = project_root(project or os.environ.get('KW_PROJECT', Path(__file__).resolve().parent.parent))
    store = Store(project, resource_root, state_dir)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='kw-writer')
    token = secrets.token_urlsafe(32)
    tasks = set()
    from .institutional_access import InstitutionalAccess
    institutional = InstitutionalAccess(store)
    app_institutional = institutional

    async def write(kind, body, action):
        result=await asyncio.get_running_loop().run_in_executor(executor, store.mutate, kind, body, action)
        # Common completion hook also covers bounded direct graph/public imports.
        # Never hold the single writer while waiting for an online source.
        if isinstance(result,dict) and ('import' in kind or kind in {'upload','direct_public_pdf','graph_direct_reuse'} or kind.startswith('replace_pdf:')):
            if isinstance(result.get('resource'),dict):return await paper_metadata.imported(result,body.get('metadata',{}))
            if result.get('resource_id') and store.resource(result['resource_id'])['type']=='paper':
                return {**result,'metadata_verification':await paper_metadata.verify(result['resource_id'])}
            if result.get('type')=='paper' and result.get('version_id'):
                await paper_metadata.verify(result['id'],body.get('metadata',{}))
                return store.resource(result['id'])
        return result

    from .paper_auto_metadata import PaperMetadataVerifier
    paper_metadata = PaperMetadataVerifier(store,write)

    async def verify_changes(result):
        identifiers=[rid for rid in result.get('changes',[]) if store.resource(rid)['type']=='paper' and store.resource(rid)['state']=='ready']
        reports=[]
        for offset in range(0,len(identifiers),2):
            reports.extend(await asyncio.gather(*(paper_metadata.verify(rid) for rid in identifiers[offset:offset+2])))
        return {**result,'metadata_verification':reports}

    def queue_metadata(result):
        if not result.get('changes'):return
        task=asyncio.create_task(verify_changes(result))
        tasks.add(task);task.add_done_callback(tasks.discard)

    from .institutional_broker import InstitutionalBroker
    institutional_broker = InstitutionalBroker(institutional,write)
    institutional_broker.paper_metadata = paper_metadata
    store.institutional = institutional

    from .codex_runner import CodexRunner, availability, instructions
    codex = CodexRunner(store, write)
    codex.institutional_broker = institutional_broker
    from .agent_bridge import AgentBridge, TASKS
    codex = AgentBridge(store, write, codex)

    def queue_build(id,run_codex=False):
        async def build():
            await asyncio.get_running_loop().run_in_executor(executor, store.build_kb, id)
            if not run_codex:return
            def create():
                kb=store.kb(id)
                if kb['index_state']!='ready' or not kb['layers']:return None
                for row in store.rows("SELECT id FROM jobs WHERE status IN ('queued','running')"):
                    existing=store.job(row['id'])
                    if existing['context']['scope'].get('kb_id')==id:return existing
                return store.create_job({'task':'build_knowledge','kb_id':id,'resource_ids':kb['resource_ids'],'question':'按用户设置的层名和侧重点深度阅读资料，提炼知识、论文贡献及有来源的创新分析，组织知识文档和关联，生成覆盖与检索评测报告。','skill':'knowline-build-knowledge'})
            try:
                job=await write('prepare_knowledge:'+id,{'operation_id':uid('op')},create)
                if job:await codex.start(job['id'],{'operation_id':uid('op'),'base_revision':job['revision']})
            except DomainError as exc:
                if exc.code!='kb_not_found':raise
        task = asyncio.create_task(build())
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return task

    async def watch_loop():
        from watchfiles import awatch
        async for changes in awatch(store.root, debounce=1500, step=300):
            if any((Path(p).suffix.lower() in {'.pdf', '.zip', '.url'} or any((store.project / rel) in Path(p).parents for rel in store.config.get('code_roots',[]))) and not Path(p).name.startswith('.kw-') for _, p in changes):
                queue_metadata(await write('scan', {'operation_id': uid('op')}, store.scan))

    @asynccontextmanager
    async def lifespan(app):
        if app_dir(project)!=project:
            from .output_names import migrate
            await write('output_directory_names',{'operation_id':uid('op')},lambda:migrate(store))
        await codex.startup()
        queue_metadata(await write('startup_scan', {'operation_id': uid('op')}, store.scan))
        await write('initialize_domains',{'operation_id':uid('op')},store.initialize_domains)
        from .retention import maintain
        await write('storage_startup',{'operation_id':uid('op')},lambda:maintain(store))
        if watch:
            task = asyncio.create_task(watch_loop())
            tasks.add(task)
        yield
        institutional.close_workers()
        await codex.close()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        await paper_metadata.close()
        from .office_clipboard import release_owned_sources
        await asyncio.to_thread(release_owned_sources)
        executor.shutdown(wait=True)

    app = FastAPI(title='Local Knowledge Workbench', version='0.1.0', lifespan=lifespan,docs_url=None,redoc_url=None)
    app.state.store = store
    app.state.token = token
    app.state.institutional = app_institutional
    app.state.paper_metadata = paper_metadata

    @app.post('/api/v1/institutional/candidates')
    async def more_paper_candidates(body:dict):
        institutional_broker.scope(body,True)
        from .research_discovery import more
        # The broker lock also prevents concurrent clients repeating a reserved page.
        if not institutional.broker_lock.acquire(blocking=False):raise DomainError('institution_download_busy',409)
        try:return await asyncio.to_thread(more,store,store.job(body.get('job_id','')))
        finally:institutional.broker_lock.release()

    async def cancel_related(predicate):
        for job in [store.job(row['id']) for row in store.rows("SELECT id FROM jobs WHERE status IN ('queued','running')")]:
            if predicate(job):
                await codex.cancel(job['id'])
                if store.job(job['id'])['status'] in {'queued','running'}:
                    await codex.transition(job['id'],'interrupted','目标已删除，本次执行已停止；冻结资料和历史成果保留。')

    @app.post('/api/v1/resources/delete-selected')
    async def delete_resources(body:dict):
        from .management import resources
        entries=body.get('resources')
        if not isinstance(entries,list) or not entries or any(not isinstance(e,dict) for e in entries):raise DomainError('invalid_request')
        ids={e.get('id') for e in entries}
        for entry in entries:store.check(store.resource(entry.get('id','')),entry)
        await cancel_related(lambda job:bool(ids.intersection(job['context']['scope'].get('resource_ids',[]))))
        return await write('delete_resources',body,lambda:resources(store,entries))

    @app.delete('/api/v1/resources/{id}')
    async def delete_resource(id:str,body:dict):
        return await delete_resources({**body,'resources':[{'id':id,'base_revision':body.get('base_revision')}]})

    @app.delete('/api/v1/groups/{id}')
    async def delete_group(id:str,body:dict):
        from .management import group
        value=next((g for g in store.groups() if g['id']==id),None)
        if not value:raise DomainError('group_not_found',404)
        store.check(value,body)
        await cancel_related(lambda job:job['context']['scope'].get('domain_id')==id)
        return await write('delete_group:'+id,body,lambda:group(store,id,body))

    @app.delete('/api/v1/ideas/{id}')
    async def delete_idea(id:str,body:dict):
        from .management import idea
        store.check(store.idea(id),body)
        await cancel_related(lambda job:job['context'].get('proposal',{}).get('idea_id')==id)
        return await write('delete_idea:'+id,body,lambda:idea(store,id,body))


    @app.get('/docs',include_in_schema=False)
    def docs():
        # Offline OpenAPI schema; no remote Swagger CDN scripts.
        return app.openapi()

    @app.middleware('http')
    async def boundary(request: Request, call_next):
        host = request.headers.get('host', '')
        try:
            host_name = urlsplit('http://' + host).hostname
        except ValueError:
            host_name = None
        if host_name not in {'127.0.0.1', 'localhost'}:
            return JSONResponse({'code': 'host_rejected'}, 403)
        origin = request.headers.get('origin')
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'code':'origin_rejected'},403)
        if origin and origin != 'http://' + host:
            # Vite dev proxy is same-origin to the browser; host rewritten by proxy.
            return JSONResponse({'code': 'origin_rejected'}, 403)
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            if not secrets.compare_digest(request.headers.get('x-kw-token', ''), token):
                return JSONResponse({'code': 'token_required'}, 403)
            length = request.headers.get('content-length', '')
            limit=128*1024*1024 if request.url.path in {'/api/v1/imports/upload','/api/v1/institutional/manual-upload'} or request.url.path.endswith('/replace-pdf') else 2*1024*1024
            if not length.isdigit() or int(length) > limit:
                return JSONResponse({'code': 'request_too_large'}, 413)
        try:
            response = await call_next(request)
        except DomainError as exc:
            response = JSONResponse({'code': exc.code, 'params': exc.params}, exc.status)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        if not request.url.path.startswith('/api/') and not request.url.path.startswith('/assets/'):
            response.headers['Cache-Control']='no-cache, must-revalidate'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; worker-src 'self' blob:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse({'code': exc.code, 'params': exc.params}, exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request,exc):
        return JSONResponse({'code':'invalid_request','params':{'fields':[list(error['loc']) for error in exc.errors()]}},422)

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        # Do not expose filenames, private content, keys or traces to clients.
        return JSONResponse({'code': 'internal_error'}, 500)

    @app.get('/api/v1/health')
    def health():
        import sqlite3
        return {'status': 'ok', 'app': 'local-knowledge-workbench', 'project_id':identity(project), 'schema_version': 1, 'sqlite_version': sqlite3.sqlite_version, 'event_sequence': store.sequence(),'capabilities':{'local_agent':1,'persistent_agent_binding':1,'institutional_access':1,'institutional_broker':1,'institutional_single_url':1,'institutional_sites':1,'scoped_publication':1,'resource_summary':1,'storage_usage':1}}

    @app.get('/api/v1/session')
    def session():
        return {'token': token, 'config': store.config, 'project_root': str(project), 'resource_root': store.config['resource_root'], 'event_sequence': store.sequence(), 'navigation':project_view()}

    @app.get('/api/v1/codex/status')
    @app.get('/api/v1/agent/status')
    async def codex_status():
        return codex.status()

    @app.get('/api/v1/agent/protocol')
    def agent_protocol():
        return {'protocol':1,'transport':'local-command-worker','tasks':TASKS,
                'entrypoint':'app/kw.cmd agent connect --command-file <local adapter JSON>',
                'documentation':'app/docs/LOCAL_AGENT.md','ui_configuration_required':False}

    @app.post('/api/v1/agent/{action}')
    async def agent_control(action: str, body: dict, request: Request):
        codex.authenticate(request)
        if action=='launch':return await codex.launch(body)
        if action=='probe':return await codex.begin(body)
        if action=='register':return await codex.register(body)
        if action=='heartbeat':return await codex.heartbeat(body)
        if action=='next':return await codex.next(body)
        if action=='disconnect':
            codex.check_agent(body)
            await codex.disconnect()
            return codex.status()
        raise DomainError('invalid_request')

    @app.post('/api/v1/settings')
    async def settings(body: dict):
        def action():
            if body.get('ui_locale', store.config['ui_locale']) not in {'zh', 'en'}:
                raise DomainError('invalid_locale')
            if 'workspace_name' in body and (not isinstance(body['workspace_name'], str) or not 1 <= len(body['workspace_name'].strip()) <= 80):
                raise DomainError('invalid_setting')
            if 'external_network' in body:
                if not isinstance(body['external_network'], bool):
                    raise DomainError('invalid_setting')
            if 'storage_budgets' in body:
                from .retention import validate_budgets
                store.config['storage_budgets']=validate_budgets(body['storage_budgets'])
            store.config['ui_locale'] = body.get('ui_locale', store.config['ui_locale'])
            if 'workspace_name' in body:
                store.config['workspace_name'] = body['workspace_name'].strip()
            if 'external_network' in body:
                store.config['external_network'] = body['external_network']
            atomic_json(store.state / 'config.json', store.config)
            store.event('settings', 'settings', 1)
            return store.config
        return await write('settings', body, action)

    @app.get('/api/v1/institutional')
    def institutional_status():
        return institutional.status()

    @app.post('/api/v1/institutional/configure')
    async def institutional_configure(body:dict):
        return await asyncio.to_thread(institutional.configure,body)

    @app.post('/api/v1/institutional/sites')
    async def institutional_add_site(body:dict):
        return await asyncio.to_thread(institutional.add_site,body)

    @app.post('/api/v1/institutional/sites/{site_id}/{action}')
    async def institutional_site_action(site_id:str,action:str,body:dict):
        return await asyncio.to_thread(institutional.site_action,site_id,action,body)

    @app.post('/api/v1/institutional/manual-upload')
    async def institutional_manual_upload(request:Request):
        return await asyncio.to_thread(institutional.manual_upload,await request.body())

    @app.post('/api/v1/institutional/{action}')
    async def institutional_action(action:str,body:dict):
        if action=='connect-preset':return await asyncio.to_thread(institutional.connect_preset,body)
        if action=='approve-site':return await asyncio.to_thread(institutional.approve_site,body)
        if action=='acquire':return await institutional_broker.acquire(body)
        if action=='lookup':return await institutional_broker.lookup(body)
        if action == 'connect':
            if body.get('entry_url'):
                from .institutional_access import safe_url
                entry=safe_url(body['entry_url'])
                return await asyncio.to_thread(institutional.connect_entry,entry,body)
            return await asyncio.to_thread(institutional.connect)
        if action == 'test':
            return await asyncio.to_thread(institutional.test,body)
        if action == 'cancel':
            return await asyncio.to_thread(institutional.cancel)
        if action == 'prepare-manual':
            return await asyncio.to_thread(institutional.prepare_manual,body)
        if action == 'logout':
            return await asyncio.to_thread(institutional.clear)
        if action == 'relogin':
            config = institutional.read('config.json',None)
            await asyncio.to_thread(institutional.clear)
            if not config:raise DomainError('institution_configuration_required')
            await asyncio.to_thread(institutional.configure,config)
            return await asyncio.to_thread(institutional.connect)
        if action == 'import':
            clean = {'operation_id':body.get('operation_id'),'domain':body.get('domain','')}
            return await write('institutional_import',clean,lambda:institutional.import_result(clean))
        raise DomainError('invalid_request')

    @app.post('/api/v1/scan')
    async def scan(body: dict):
        return await verify_changes(await write('scan', body, store.scan))

    @app.get('/api/v1/project/catalog')
    def project_catalog():
        from .project_catalog import catalog
        return catalog(store)

    @app.get('/api/v1/project/view')
    def project_view():
        row=store.one("SELECT value FROM settings WHERE key='ui_navigation'")
        return json.loads(row['value']) if row else {'route':'library','type':'all'}

    @app.post('/api/v1/project/view')
    async def navigate_project(body:dict):
        return await write('project_view',body,lambda:store.project_view(body))

    @app.post('/api/v1/project/import')
    async def import_to_domain(body:dict):
        from .project_catalog import resolve
        def action():
            destination=body.get('destination','domain')
            if destination not in {'library','domain'} or (destination=='library' and body.get('domain')):raise DomainError('invalid_request')
            group=resolve(store.groups(),body.get('domain',''),'group') if destination=='domain' else None
            metadata=body.get('metadata',{})
            acquisition_fields={'publisher_url','access_method','pdf_version','pdf_version_basis','acquired_at','fallback_reason','pdf_identity','publication_record_id'}
            if not isinstance(metadata,dict) or set(metadata)-({'title','year','venue','doi','authors','tags','field_sources','metadata_status','source_type','volume','issue','pages','url'}|acquisition_fields):
                raise DomainError('invalid_request')
            if metadata.get('publisher_url'):
                from .institutional_access import safe_url
                metadata['publisher_url']=safe_url(metadata['publisher_url'])
            if 'pdf_version' in metadata:
                from .institutional_access import VERSIONS
                if metadata['pdf_version'] not in VERSIONS or (metadata['pdf_version']!='unknown' and not metadata.get('pdf_version_basis')):raise DomainError('institution_version_basis_required')
                if metadata['pdf_version'] in {'accepted_manuscript','preprint'} and not metadata.get('fallback_reason'):raise DomainError('institution_fallback_reason_required')
            result=store.import_local(body)
            r=result['resource']
            citation_id=metadata.get('publication_record_id')
            if result.get('duplicate'):
                metadata={k:v for k,v in metadata.items() if k not in acquisition_fields}
                protected=r['metadata'].get('metadata_status')=='verified' or r['metadata'].get('publication_status')=='published'
                if protected:metadata={k:v for k,v in metadata.items() if k not in {'title','authors','year','venue','doi','volume','issue','pages','source_type','url','field_sources'}}
            if metadata:
                # Hints are not proof. Verification follows registration outside the writer.
                prior_status=r['metadata'].get('metadata_status')
                status=prior_status if result.get('duplicate') and prior_status else 'needs_review'
                metadata={**metadata,'metadata_status':status}
                metadata['field_sources']={**{k:{'source':'import_hint','locked':False} for k in metadata if k!='field_sources'},**metadata.get('field_sources',{})}
                r=store.update_resource(r['id'],{**metadata,'base_revision':r['revision']})['resource']
            if group:
                group=resolve(store.groups(),group['id'],'group')
                if r['id'] not in group['resource_ids']:
                    store.group_members(group['id'],{'base_revision':group['revision'],'resource_ids':group['resource_ids']+[r['id']]})
            return {**result,'resource':store.resource(r['id']),'domain':group['name'] if group else None,'destination':destination}
        return await write('project_import',body,action)

    @app.post('/api/v1/project/jobs')
    async def project_job(body:dict):
        from .project_catalog import resolve
        def action():
            group=resolve(store.groups(),body.get('domain',''),'group')
            resource_type=body.get('type','all')
            if resource_type not in {'all','paper','code'}:
                raise DomainError('invalid_request')
            ids=[id for id in group['resource_ids'] if store.resource(id)['type']!='link' and
                 (resource_type=='all' or store.resource(id)['type']==resource_type)]
            return store.create_job({**body,'resource_ids':ids})
        return await write('project_job',body,action)

    @app.get('/api/v1/word/sessions')
    def word_sessions():
        from .word_bridge import sessions
        return sessions(project)

    @app.post('/api/v1/word/open')
    async def word_open(body:dict):
        from .word_bridge import start
        if not isinstance(body.get('document'),str):raise DomainError('word_docx_required')
        return await asyncio.to_thread(start,project,document=body['document'],direct_original=True)

    @app.get('/api/v1/word/open-documents')
    async def user_word_documents():
        from .word_bridge import open_documents
        return await asyncio.to_thread(open_documents)

    @app.post('/api/v1/word/{session_id}/actions')
    async def word_action(session_id:str,body:dict):
        from .word_bridge import request as word_request
        action=body.get('action')
        if action not in {'inspect','cite','style','format','refresh','save','close','bibliography'} or not body.get('operation_id'):
            raise DomainError('invalid_request')
        params={}
        if action=='style':params={'name':body.get('name')}
        if action=='format':params={'formatting':body.get('formatting',{})}
        if action=='cite':
            from .word_sources import domain_sources
            if not isinstance(body.get('resource_ids'),list) or not body.get('if_text_hash'):
                raise DomainError('invalid_request')
            params={'sources':domain_sources(project,body.get('domain',''),body['resource_ids'])['sources'],
                    'selection':True,'if_text_hash':body['if_text_hash'],'allow_cursor':True,
                    'selection_start':body.get('selection_start'),'selection_end':body.get('selection_end')}
            params['if_context_hash']=body.get('if_context_hash')
        # Word has a separate STA worker and serialized queue; never block the SQLite writer.
        return await asyncio.to_thread(word_request,project,session_id,action,operation_id=body['operation_id'],**params)

    @app.post('/api/v1/imports/upload')
    async def upload(request:Request):
        # The OS picker supplies bytes, never an arbitrary path to read on the server.
        from urllib.parse import unquote
        name=unquote(request.headers.get('x-kw-filename',''))
        kind=request.headers.get('x-kw-kind','paper')
        domain=request.headers.get('x-kw-domain','')
        if not name or Path(name).name!=name or any(c in name for c in '<>:"/\\|?*') or len(name)>180:
            raise DomainError('invalid_filename')
        if (kind=='paper' and Path(name).suffix.lower()!='.pdf') or (kind=='word' and Path(name).suffix.lower()!='.docx') or (kind=='code-project' and Path(name).suffix.lower()!='.zip') or kind not in {'paper','word','code','code-project'}:
            raise DomainError('invalid_request')
        body=await request.body()
        if not body and kind!='code':raise DomainError('file_empty')
        if len(body)>128*1024*1024:raise DomainError('upload_too_large',limit_mb=128)
        operation=request.headers.get('x-kw-operation','')
        if not operation or len(operation)>100:raise DomainError('invalid_request')
        def action():
            from .project_catalog import resolve
            group=resolve(store.groups(),domain,'group') if domain else None
            if kind in {'code','code-project'}:
                from .code_import import import_bytes
                return import_bytes(store,name,kind,body,group)
            target=contained(project,'incoming/'+hash_bytes(body)[:12]+'-'+name,False)
            target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists() and digest(target)!=hash_bytes(body):raise DomainError('hash_conflict')
            if not target.exists():
                temp=target.with_suffix(target.suffix+'.upload');temp.write_bytes(body)
                try:
                    if kind=='paper':
                        with pdf.open_pdf(temp) as doc:
                            if not len(doc):raise DomainError('pdf_invalid')
                    else:
                        from .word_bridge import validate_docx
                        validate_docx(temp)
                    os.replace(temp,target)
                finally:
                    if temp.exists():temp.unlink()
            if kind=='word':return {'path':target.relative_to(project).as_posix()}
            result=store.import_local({'path':target.relative_to(project).as_posix()})
            resource=result['resource']
            if group and resource['id'] not in group['resource_ids']:
                store.group_members(group['id'],{'base_revision':group['revision'],'resource_ids':group['resource_ids']+[resource['id']]})
            # Existing verified metadata is never overwritten by upload hints.
            metadata_task=None
            # Automatic public bibliography verification runs after this transaction.
            return {**result,'resource':store.resource(resource['id']),'metadata_job':metadata_task}
        return await write('upload',{'operation_id':operation,'sha256':hash_bytes(body),'name':name,'kind':kind,'domain':domain},action)

    @app.get('/api/v1/resources')
    def resources(type: str | None = None, summary: bool = False):
        result = store.resources(summary=summary)
        return [r for r in result if not type or r['type'] == type]

    @app.post('/api/v1/paper-metadata/verify')
    async def verify_paper_metadata(body:dict):
        identifiers=body.get('resource_ids')
        if not isinstance(identifiers,list) or not 1<=len(identifiers)<=200 or any(not isinstance(rid,str) for rid in identifiers):raise DomainError('invalid_request')
        identifiers=list(dict.fromkeys(identifiers))
        if any(store.resource(rid)['type']!='paper' or store.resource(rid)['state']!='ready' for rid in identifiers):raise DomainError('scope_violation',409)
        reports=[]
        for offset in range(0,len(identifiers),2):
            batch=identifiers[offset:offset+2]
            results=await asyncio.gather(*(paper_metadata.verify(rid,{'refresh':True}) for rid in batch))
            reports.extend({'resource_id':rid,**result} for rid,result in zip(batch,results))
        return {'rows':reports,'total':len(reports),'verified_count':sum(r['state']=='verified' for r in reports),'metadata_job':None}

    @app.get('/api/v1/resources/{id}')
    def resource(id: str):
        return store.resource(id)

    @app.patch('/api/v1/resources/{id}')
    async def update_resource(id: str, body: dict):
        return await write('resource:' + id, body, lambda: store.update_resource(id, body))

    @app.get('/api/v1/resources/{id}/file')
    def resource_file(id: str, version: str | None = None):
        r = store.resource(id)
        if r['type'] != 'paper':
            raise DomainError('paper_required')
        return FileResponse(store.snapshot(r, version), media_type='application/pdf', headers={'Cache-Control': 'no-store'})

    @app.get('/api/v1/resources/{id}/page/{index}')
    def page(id: str, index: int, version: str | None = None):
        r = store.resource(id)
        snapshot=store.snapshot(r,version)
        current=store.current_path(r) if r['state']=='ready' and (not version or version==r['version_id']) else None
        shared=bool(current and os.path.samefile(current,snapshot))
        return {**pdf.page_info(snapshot,index,editable_path=current,allow_readonly_source=shared), 'version_id': version or r['version_id']}

    @app.get('/api/v1/resources/{id}/annotations')
    def annotation_list(id: str, version: str | None = None):
        r = store.resource(id)
        if version:
            store.snapshot(r, version)
        return [a for a in store.annotation_list(id) if not version or a['version_id'] == version]

    @app.post('/api/v1/resources/{id}/annotations')
    async def annotation(id: str, body: dict):
        return await write('annotation:' + id, body, lambda: store.annotate(id, body))

    @app.post('/api/v1/papers/rename-plan')
    def rename_plan(body: dict):
        return store.rename_plan(body)

    @app.post('/api/v1/resources/{id}/rename')
    async def rename(id: str, body: dict):
        return await write('rename:' + id, body, lambda: store.rename(id, body))

    @app.post('/api/v1/resources/{id}/replace-pdf')
    async def replace_pdf(id:str,request:Request):
        try:revision=int(request.headers.get('x-kw-revision',''))
        except ValueError:raise DomainError('revision_required')
        data=await request.body()
        body={'operation_id':request.headers.get('x-kw-operation',''),'base_revision':revision,'base_sha256':request.headers.get('x-kw-sha256',''),'version_id':request.headers.get('x-kw-version',''),'replacement_sha256':hash_bytes(data)}
        return await write('replace_pdf:'+id,body,lambda:store.replace_pdf(id,body,data))

    @app.get('/api/v1/resources/{id}/code')
    def code(id: str, version: str | None = None):
        r = store.resource(id)
        if r['type'] != 'code':
            raise DomainError('code_required')
        return {'resource_id': id, 'version_id': version or r['version_id'], 'files': store.code_manifest(r, version)}

    @app.get('/api/v1/resources/{id}/code/file')
    def code_file(id: str, file: str, version: str | None = None, encoding: str = 'utf-8-sig'):
        r = store.resource(id)
        if r['type'] != 'code':
            raise DomainError('code_required')
        return store.code_file(r, file, version, encoding)

    @app.post('/api/v1/resources/{id}/extract')
    async def extract(id: str, body: dict):
        return await write('extract:' + id, body, lambda: store.extract_code(id, body))

    @app.get('/api/v1/groups')
    def groups():
        return store.groups()

    @app.post('/api/v1/groups')
    async def create_group(body: dict):
        return await write('create_group', body, lambda: store.create_group(body))

    @app.put('/api/v1/groups/{id}/members')
    async def members(id: str, body: dict):
        return await write('group_members:' + id, body, lambda: store.group_members(id, body))

    @app.put('/api/v1/groups/{id}')
    async def rename_group(id: str, body: dict):
        return await write('rename_group:' + id, body, lambda: store.rename_group(id, body))

    @app.get('/api/v1/knowledge-bases')
    def kbs():
        return store.kbs()

    @app.get('/api/v1/knowledge-bases/{id}')
    def kb(id: str):
        return store.kb(id)

    @app.post('/api/v1/knowledge-bases')
    async def create_kb(body: dict):
        kb = await write('create_kb', body, lambda: store.create_kb(body))
        queue_build(kb['id'],body.get('run_agent',body.get('run_codex',True)))
        return kb

    @app.put('/api/v1/knowledge-bases/{id}')
    async def update_kb(id: str, body: dict):
        kb = await write('update_kb:' + id, body, lambda: store.update_kb(id, body))
        if kb['resource_ids']:
            queue_build(id,body.get('run_agent',body.get('run_codex',True)))
        return kb

    @app.post('/api/v1/knowledge-bases/{id}/add-resources')
    async def add_knowledge_resources(id:str,body:dict):
        def action():
            from .knowledge import get
            kb=store.kb(id);store.check(kb,body)
            added=store.selection({**body,'allow_links':True})
            new=[rid for rid in added if rid not in kb['resource_ids']]
            if not new:raise DomainError('knowledge_members_unchanged')
            previous=get(store,'kb_cards:'+id,{})
            updated=store.update_kb(id,{**body,'resource_ids':kb['resource_ids']+new})
            job=store.create_job({'task':'update_knowledge','kb_id':id,'resource_ids':updated['resource_ids'],
                  'question':'按原有层级更新知识库，分析新增资料并核对原有知识的关系。保留仍有效的原知识卡片，合并新的有来源知识；旧卡片不得直接当作当前范围结论。',
                  'skill':'knowline-build-knowledge'})
            context=job['context'];context['knowledge_update']={'added_resource_ids':new,'previous_member_revision':kb['member_revision'],'previous_cards':previous}
            store.db.execute('UPDATE jobs SET context=? WHERE id=?',(json_text(context),job['id']))
            atomic_json(store.state/'jobs'/job['id']/'context.json',context)
            return {'knowledge_base':updated,'job':store.job(job['id'])}
        result=await write('knowledge_add:'+id,body,action)
        await queue_build(id)
        if body.get('run_agent',body.get('run_codex',True)):await codex.start(result['job']['id'],{'operation_id':uid('op'),'base_revision':result['job']['revision']})
        return result

    @app.post('/api/v1/knowledge-bases/{id}/build')
    async def build(id: str, body: dict):
        def action():
            kb = store.kb(id)
            store.check(kb, body)
            store.db.execute("UPDATE knowledge_bases SET index_state='queued' WHERE id=?", (id,))
            return store.kb(id)
        kb = await write('build:' + id, body, action)
        queue_build(id,body.get('run_agent',body.get('run_codex',True)))
        return kb

    @app.post('/api/v1/knowledge-bases/{id}/assemble')
    async def assemble(id: str, body: dict):
        from .knowledge import assemble
        return await write('assemble:'+id,body,lambda:assemble(store,id,body))

    @app.post('/api/v1/knowledge-bases/select-folder')
    async def select_knowledge_folder(body:dict):
        from .folder_picker import select_folder
        return await asyncio.to_thread(select_folder)

    @app.post('/api/v1/knowledge-bases/import-preview')
    async def preview_knowledge_import(body:dict):
        from .knowledge_import import preview
        return await asyncio.to_thread(preview,body.get('folder'))

    @app.post('/api/v1/knowledge-bases/import-folder')
    async def import_existing_knowledge(body:dict):
        from .knowledge_import import import_folder
        return await write('import_knowledge_folder',body,lambda:import_folder(store,body))

    @app.get('/api/v1/knowledge-bases/{id}/imported-source/{document_id}')
    def imported_knowledge_source(id:str,document_id:str):
        from .knowledge_import import source_document
        return Response(source_document(store,id,document_id),media_type='text/plain; charset=utf-8',headers={'X-Content-Type-Options':'nosniff'})

    @app.get('/api/v1/knowledge-bases/{id}/cards')
    def knowledge_cards(id: str):
        from .knowledge import cards
        kb=store.kb(id)
        return {'knowledge_base':kb,'cards':cards(store,kb)}

    @app.get('/api/v1/knowledge-bases/{id}/cards/{card_id}/figure')
    def knowledge_figure(id: str, card_id: str):
        from .knowledge import figure_path
        return FileResponse(figure_path(store,id,card_id),media_type='image/png')

    @app.get('/api/v1/knowledge-bases/{id}/query')
    def query(id: str, q: str, kb_revision:int):
        kb=store.kb(id)
        if kb_revision != kb['revision']:
            raise DomainError('revision_conflict',409,current_revision=kb['revision'])
        return store.query(id, q[:500])

    @app.get('/api/v1/knowledge-bases/{id}/graph')
    def graph(id: str, parent: str | None = None):
        return store.graph(id, parent)

    @app.get('/api/v1/knowledge-bases/{id}/nodes')
    def nodes(id: str, q: str = ''):
        store.kb(id)
        return store.rows('SELECT id,label,kind,parent_id FROM nodes WHERE kb_id=? AND label LIKE ? LIMIT 80', (id, '%' + q[:100] + '%'))

    @app.patch('/api/v1/nodes/{id}')
    async def update_node(id: str, body: dict):
        return await write('node:' + id, body, lambda: store.update_node(id, body))

    @app.get('/api/v1/relations')
    def relations():
        return store.rows('SELECT * FROM relations')

    @app.post('/api/v1/relations')
    async def relation(body: dict):
        return await write('relation', body, lambda: store.relation(body))

    @app.delete('/api/v1/relations/{id}')
    async def delete_relation(id: str, body: dict):
        return await write('delete_relation:' + id, body, lambda: store.delete_relation(id, body))

    @app.get('/api/v1/jobs')
    def jobs():
        return [codex.job(j['id']) for j in store.rows('SELECT id FROM jobs ORDER BY created_at DESC')]

    @app.get('/api/v1/jobs/{id}')
    def job(id: str):
        return codex.job(id)

    @app.get('/api/v1/jobs/{id}/instructions')
    def job_instructions(id: str):
        return {'text': instructions(store, store.job(id)), 'project_root': str(project)}

    @app.post('/api/v1/jobs/{id}/office-extract/{action}')
    async def office_extract(id:str,action:str,body:dict):
        from .office_extract import service_step
        job=store.job(id);store.check(job,body)
        if job['task']!='copy_office_selection' or job['status'] in {'completed','partial'}:raise DomainError('office_fragment_not_ready')
        if action not in {'prepare','build','revise'}:raise DomainError('invalid_request')
        return await asyncio.to_thread(service_step,store,id,action,body)

    @app.post('/api/v1/jobs/{id}/office-native')
    async def native_office_step(id: str, body: dict):
        from .office_native import run
        return await asyncio.to_thread(run, store, id, body)

    @app.post('/api/v1/jobs/{id}/run')
    async def run_codex(id: str, body: dict):
        return await codex.start(id, body)

    @app.post('/api/v1/jobs/{id}/cancel')
    async def cancel_job(id: str, body: dict):
        store.check(store.job(id),body)
        await codex.cancel(id)
        def stop():
            job=store.job(id)
            if job['status'] in {'completed','partial','failed','interrupted'}:return codex.job(id)
            store.db.execute("UPDATE jobs SET status='interrupted',revision=revision+1,updated_at=? WHERE id=?",(now(),id))
            store.event('job',id,job['revision']+1)
            codex.info(id,'interrupted','用户已取消执行，已保存的资料和证据保留。')
            return codex.job(id)
        return await write('cancel_job:'+id,body,stop)

    @app.post('/api/v1/jobs/{id}/literature-budget')
    async def literature_budget(id: str, body: dict):
        return await write('literature-budget:'+id,body,lambda:store.revise_literature_job(id,body))

    @app.post('/api/v1/jobs/{id}/audit-completion')
    async def audit_completion(id: str, body: dict):
        return await write('audit-completion:'+id,body,lambda:store.audit_literature_job(id,body))

    @app.post('/api/v1/jobs/{id}/claim')
    async def claim_job(id: str, body: dict):
        return await codex.claim(id, body)

    @app.post('/api/v1/jobs/{id}/fail')
    async def fail_job(id: str, body: dict, request: Request):
        codex.guard(id,body,request)
        return await codex.fail(id, body)

    @app.get('/api/v1/jobs/{id}/paper-graph')
    def paper_graph(id:str):
        from .paper_graph import load
        return load(store,store.job(id))

    @app.post('/api/v1/jobs/{id}/paper-graph/import-saved')
    async def import_graph_saved(id:str,body:dict):
        from .graph_direct_import import run
        return await run(store,store.job(id),body,write)

    @app.post('/api/v1/jobs/{id}/copy-office')
    async def copy_office(id:str,body:dict):
        from .office_clipboard import copy
        job=store.job(id);store.check(job,body)
        if job['task']!='copy_office_selection' or job['status']!='completed':raise DomainError('office_fragment_not_ready')
        spec=(job['result'] or {}).get('office_fragment',{})
        artifact=next((a for a in job['result']['artifacts'] if a['path']==spec.get('path')),None)
        if not artifact or spec.get('target')!=job['context'].get('office_selection',{}).get('target'):raise DomainError('office_fragment_invalid')
        path=contained(project,artifact['path'])
        if digest(path)!=artifact['sha256']:raise DomainError('artifact_hash_mismatch')
        return await asyncio.to_thread(copy,path,spec['target'])

    @app.post('/api/v1/jobs')
    async def create_job(body: dict):
        job = await write('create_job', body, lambda: store.create_job(body))
        if body.get('run_agent',body.get('run_codex')) is True and job['status'] == 'waiting_user':
            return await codex.start(job['id'], {'operation_id': 'dispatch-' + body['operation_id'], 'base_revision': job['revision']})
        return codex.job(job['id'])

    @app.get('/api/v1/ideas')
    def ideas():
        return store.ideas()

    @app.get('/api/v1/ideas/{id}')
    def idea(id: str):
        return store.idea(id)

    @app.post('/api/v1/ideas')
    async def create_idea(body: dict):
        return await write('create_idea', body, lambda: store.create_idea(body))

    @app.patch('/api/v1/ideas/{id}')
    async def update_idea(id: str, body: dict):
        return await write('update_idea:' + id, body, lambda: store.update_idea(id, body))

    @app.post('/api/v1/jobs/delete-selected')
    async def delete_jobs(body: dict):
        entries=body.get('jobs')
        if not isinstance(entries,list) or not 1<=len(entries)<=200 or any(not isinstance(e,dict) or not isinstance(e.get('id'),str) for e in entries) or len({e['id'] for e in entries})!=len(entries):raise DomainError('invalid_request')
        for entry in entries:store.check(store.job(entry['id']),entry)
        for entry in entries:await codex.cancel(entry['id'])
        def remove():
            entries=body.get('jobs')
            if not isinstance(entries,list) or not 1<=len(entries)<=200 or any(not isinstance(e,dict) or not isinstance(e.get('id'),str) for e in entries):
                raise DomainError('invalid_request')
            if len({e['id'] for e in entries})!=len(entries):raise DomainError('invalid_request')
            selected=[]
            for entry in entries:
                job=store.job(entry['id']);selected.append(job)
            for job in selected:
                store.db.execute('DELETE FROM jobs WHERE id=?',(job['id'],))
                store.event('job',job['id'],job['revision']+1)
            return {'deleted':[job['id'] for job in selected]}
        return await write('delete_jobs',body,remove)

    @app.delete('/api/v1/jobs/{id}')
    async def delete_job(id:str,body:dict):
        store.check(store.job(id),body)
        await codex.cancel(id)
        def remove():
            job=store.job(id)
            store.db.execute('DELETE FROM jobs WHERE id=?',(id,))
            store.event('job',id,job['revision']+1)
            return {'id':id,'state':'deleted'}
        return await write('delete_job:'+id,body,remove)

    @app.post('/api/v1/jobs/{id}/ingest')
    async def ingest(id: str, body: dict, request: Request):
        codex.guard(id,body,request)
        job=store.job(id)
        if job['task']=='paper_relationships' and job['status'] not in {'completed','partial'}:
            store.check(job,body)
            manifest=body.get('manifest')
            if not isinstance(manifest,dict):raise DomainError('invalid_result')
            path=manifest.get('paper_graph_artifact')
            item=next((a for a in manifest.get('artifacts',[]) if a.get('path')==path),None)
            if not item:raise DomainError('invalid_paper_graph')
            file=contained(store.project,path)
            if not file.is_relative_to(contained(store.project,job['context']['output_dir'])) or digest(file)!=item.get('sha256'):raise DomainError('artifact_hash_mismatch')
            from .research_enrich import artifact as enrich_graph
            await enrich_graph(store,job,write,budget=40,path=file,broker=institutional_broker)
            item['sha256']=digest(file)
            atomic_json(file.parent/'result.json',manifest)
        result=await write('ingest:' + id, body, lambda: codex.ingest_result(id,body,request))
        await codex.accepted(id)
        return result

    @app.get('/api/v1/jobs/{id}/artifact')
    def artifact(id: str, path: str, preview: bool = False):
        job = store.job(id)
        if not job['result'] or path not in [a['path'] for a in job['result']['artifacts']]:
            raise DomainError('path_outside_scope')
        file=contained(store.project, path)
        if preview and file.suffix.lower()=='.png':
            return FileResponse(file,media_type='image/png')
        from .output_names import download_name
        artifact=next(a for a in job['result']['artifacts'] if a['path']==path)
        return FileResponse(file, filename=download_name(Path(path).name,store.config['ui_locale'],job['task'],artifact['sha256']))

    @app.post('/api/v1/backup')
    async def backup(body: dict):
        return await write('backup', body, store.backup)

    @app.post('/api/v1/maintenance/coalesce-papers')
    async def coalesce_paper_storage(body:dict):
        from .paper_storage import coalesce
        return await write('coalesce_papers',body,lambda:coalesce(store))

    @app.post('/api/v1/maintenance/storage')
    async def storage_maintenance(body:dict):
        from .storage_delete import drain
        from .retention import maintain
        return await write('storage_maintenance',body,lambda:{'retention':maintain(store),'deletions':drain(store)})

    @app.get('/api/v1/maintenance/storage')
    def storage_policy():
        from .storage import POLICY
        from .retention import budgets
        return {'policy':POLICY,'limits':budgets(store),'full_backups_disabled':True,'retention_active':True}

    @app.get('/api/v1/maintenance/storage/usage')
    async def storage_usage():
        from .storage_usage import usage
        return await asyncio.get_running_loop().run_in_executor(executor,usage,store)

    @app.get('/api/v1/maintenance/storage/preview')
    async def storage_preview():
        from .retention import maintain
        return await asyncio.get_running_loop().run_in_executor(executor,lambda:maintain(store,dry_run=True))

    @app.post('/api/v1/maintenance/storage/clean')
    async def storage_clean(body:dict):
        from .retention import maintain
        # Separate from the legacy deletion queue; this only cleans derived data.
        return await write('storage_clean',body,lambda:maintain(store))

    @app.post('/api/v1/maintenance/storage/compact-vectors')
    async def storage_compact_vectors(body:dict):
        from .storage_usage import compact_vectors
        return await write('storage_compact_vectors',body,lambda:compact_vectors(store))

    @app.get('/api/v1/operations')
    def operations():
        return store.rows("SELECT id,kind,state,created_at FROM operations WHERE state IN('conflict','prepared')")

    @app.get('/api/v1/skills')
    def skills():
        from .skills import inventory
        return inventory(store.project)

    @app.delete('/api/v1/knowledge-bases/{id}')
    async def delete_kb(id:str,body:dict):
        store.check(store.kb(id),body)
        await cancel_related(lambda job:job['context']['scope'].get('kb_id')==id or id in [k['id'] for k in job['context'].get('proposal',{}).get('knowledge_bases',[])])
        def action():
            kb=store.kb(id);store.check(kb,body)
            for table in ['kb_members','kb_chunks','nodes']:
                store.db.execute('DELETE FROM '+table+' WHERE kb_id=?',(id,))
            store.db.execute('DELETE FROM knowledge_bases WHERE id=?',(id,))
            for idea in store.ideas():
                if id in idea['knowledge_base_ids']:
                    store.db.execute('UPDATE proposal_ideas SET knowledge_base_ids=?,revision=revision+1,updated_at=? WHERE id=?',(json_text([i for i in idea['knowledge_base_ids'] if i!=id]),now(),idea['id']))
            store.event('knowledge_base',id,kb['revision']+1)
            return {'id':id,'state':'deleted'}
        return await write('delete_kb:'+id,body,action)

    @app.get('/api/v1/events')
    async def events(request: Request, after: int = 0):
        async def stream():
            cursor = after
            while not await request.is_disconnected():
                data = store.rows('SELECT * FROM events WHERE sequence>? ORDER BY sequence LIMIT 100', (cursor,))
                for event in data:
                    cursor = event['sequence']
                    yield 'id: ' + str(cursor) + '\ndata: ' + json_text(event) + '\n\n'
                if not data:
                    yield ': heartbeat\n\n'
                await asyncio.sleep(1)
        return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    @app.post('/api/v1/discovery/search')
    async def discovery(body: dict):
        if not store.config['external_network'] or body.get('consent') is not True:
            raise DomainError('network_disabled', 403)
        query = str(body.get('query', '')).strip()[:300]
        if not query:
            raise DomainError('query_required')
        params = {'query.bibliographic': query, 'rows': 15}
        if body.get('from_year'):
            params['filter'] = 'from-pub-date:' + str(int(body['from_year'])) + '-01-01'
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as client:
                resp = await client.get('https://api.crossref.org/works', params=params, headers={'User-Agent': 'LocalKnowledgeWorkbench/0.1 (manual metadata lookup)'})
                resp.raise_for_status()
                data = resp.json()['message']['items']
        except (httpx.HTTPError, ValueError, KeyError):
            raise DomainError('discovery_failed', 502)
        candidates = []
        existing = {r['metadata'].get('doi', '').lower() for r in store.resources()}
        for item in data:
            date = item.get('published', {}).get('date-parts', [[]])[0]
            candidates.append({'doi': item.get('DOI', ''), 'title': (item.get('title') or [''])[0], 'year': date[0] if date else None, 'venue': (item.get('container-title') or [''])[0], 'authors': [' '.join([a.get('given', ''), a.get('family', '')]).strip() for a in item.get('author', [])], 'source': 'Crossref', 'source_url': 'https://api.crossref.org/works/' + item.get('DOI', ''), 'retrieved_at': now(), 'duplicate_doi': item.get('DOI', '').lower() in existing, 'licenses': item.get('license', []), 'status': 'needs_review'})
        from .paper_bibliography import crossref,save
        def retain_records():
            for item,candidate in zip(data,candidates):
                try:
                    record=crossref(item,now())
                    if record['publication_status']=='published':
                        record=save(store,record,body.get('domain_id'))
                        candidate.update(citation_record_id=record['id'],publication_status=record['publication_status'],metadata_status=record['metadata_status'],latest_checked_at=record['latest_checked_at'],pdf_status=record['pdf_status'])
                except DomainError as exc:candidate['citation_reason']=exc.code
        await write('discovery_records',{**body,'operation_id':body.get('operation_id') or uid('op')},retain_records)
        atomic_json(store.state / 'cache' / ('discovery-' + str(int(time.time())) + '.json'), {'query': query, 'candidates': candidates, 'retrieved_at': now()})
        from .retention import maintain
        await write('discovery_cache_trim',{'operation_id':uid('op')},lambda:maintain(store))
        return {'candidates': candidates, 'source': 'Crossref'}

    def bibliography_scope(body):
        if body.get('job_id'):
            job=store.job(body['job_id'])
            if job['task'] not in {'discover_papers','import_graph_papers','paper_relationships','verify_paper_metadata'} or job['status'] not in {'running','waiting_user'} or not str(job['context'].get('external_network','')).startswith('user_requested'):raise DomainError('scope_violation',409)
            return job['context']['scope'].get('domain_id')
        if not store.config['external_network'] or body.get('consent') is not True:raise DomainError('network_disabled',403)
        return body.get('domain_id')

    @app.get('/api/v1/paper-records')
    def paper_records():
        from .paper_bibliography import rows
        return rows(store)

    @app.get('/api/v1/paper-records/{id}')
    def paper_record(id:str):
        from .paper_bibliography import get
        return get(store,id)

    @app.post('/api/v1/paper-records/resolve')
    async def resolve_citation(body:dict):
        domain_id=bibliography_scope(body)
        from .paper_bibliography import resolve,save,attach,outcome,get
        if body.get('resource_id') and body.get('job_id'):
            job=store.job(body['job_id']);frozen=next((r for r in job['context'].get('resources',[]) if r['resource_id']==body['resource_id']),None)
            if not frozen or store.resource(body['resource_id'])['version_id']!=frozen['version_id']:raise DomainError('scope_violation',409)
        record=await resolve(body.get('doi'),body.get('arxiv_id'))
        value=await write('paper_record',body,lambda:save(store,record,domain_id))
        if body.get('resource_id'):
            # Persist the citation first: a failed PDF association cannot roll it back.
            link_body={**body,'operation_id':hash_bytes((body['operation_id']+':pdf-link').encode())}
            try:
                await write('paper_record_link',link_body,lambda:attach(store,value,body['resource_id'],body.get('pdf_identity')))
            except DomainError as exc:
                failed={**body,'operation_id':hash_bytes((body['operation_id']+':pdf-link-failed').encode())}
                await write('paper_record_pdf',failed,lambda:outcome(store,value['id'],'needs_user',reason=exc.code))
                return {**get(store,value['id']),'pdf_link':{'status':'needs_user','reason':exc.code}}
            value=get(store,value['id'])
        return value

    @app.post('/api/v1/paper-records/{id}/export')
    async def export_citation(id:str,body:dict):
        domain_id=bibliography_scope(body)
        from .paper_bibliography import get,resolve,save,export
        previous=get(store,id)
        if body.get('job_id') and domain_id and domain_id not in previous['domain_ids']:raise DomainError('scope_violation',409)
        # Export always asks the public source again; stale cached citations are not substituted.
        record=await resolve(previous.get('doi') or None,previous.get('arxiv_id') if previous['publication_status']=='preprint' else None)
        record=await write('paper_record_refresh',body,lambda:save(store,record))
        return {'record':record,'text':export(record,body.get('format','text'))}

    @app.post('/api/v1/import')
    async def import_local(body: dict):
        return await write('import', body, lambda: store.import_local(body))

    dist = Path(ui_root) if ui_root else app_dir(project) / 'dist'
    if not dist.exists() and getattr(sys,'frozen',False):dist=Path(sys._MEIPASS)/'dist'
    if dist.exists():
        app.mount('/', StaticFiles(directory=dist, html=True), name='ui')
    return app
