"""Job-scoped bridge: bibliographic DTOs only; browser credentials remain private."""
import asyncio
import time
import uuid
from urllib.parse import urlsplit,quote
from .institutional_access import safe_url, normalize, paper_request
from .safety import DomainError, atomic_json
from .store import uid

PUBLISHER_QUEUE_TIMEOUT_SECONDS=30


class InstitutionalBroker:
    def __init__(self, manager, write, graph_operation=None):
        self.manager = manager
        self.store = manager.store
        self.write = write
        self.requests = {}
        self.public_blocks = {}
        self.public_locations = {}
        # All brokers for this installation share the same browser queue,
        # including concurrent graph prefetch, discovery and direct import.
        if not hasattr(manager,'acquisition_queue'):manager.acquisition_queue=asyncio.Lock()
        self.acquisition_queue = manager.acquisition_queue
        self.graph_candidates = {}  # Validated graph prefetch only; never caller-supplied scope.
        # Internal direct import only: the caller validates the frozen artifact,
        # selected IDs and revision on every transfer/write, without a new job.
        self.graph_operation=graph_operation
        if graph_operation:self.graph_candidates[graph_operation['job_id']]=graph_operation['nodes']

    def active(self,job_id):
        if self.graph_operation and job_id==self.graph_operation['job_id']:
            self.graph_operation['active']()
            return True
        return self.store.job(job_id)['status'] in {'running','waiting_user'}

    async def resume_account(self,manager,job_id):
        state=manager.status()
        # Closing a worker/restarting the app keeps the isolated account profile.
        # Reopen that profile quietly only when a prior connection was ready;
        # a configured-but-never-logged-in site stays on the public route.
        saved=(state.get('task_ready') or state.get('reason')=='subscription_denied') and (state.get('verified_pdf') or state.get('authentication_confirmed'))
        if not state.get('online') and saved:
            await asyncio.to_thread(manager.connect,True)
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                if not self.active(job_id):raise DomainError('originating_task_stopped',409)
                state=manager.status()
                if state.get('online') and state.get('reason')!='browser_starting':break
                if state.get('state') in {'expired','unconfigured'} or state.get('reason') in {'browser_process_failed','browser_event_failed','webview2_unavailable'}:break
                await asyncio.sleep(.1)
        if state.get('reason')=='browser_starting' and (state.get('verified_pdf') or state.get('authentication_confirmed')):
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                if not self.active(job_id):raise DomainError('originating_task_stopped',409)
                state=manager.status()
                if state.get('reason')!='browser_starting':break
                await asyncio.sleep(.25)
        return state

    def scope(self, body, download=False):
        job = self.store.job(str(body.get('job_id','')))
        direct=self.graph_operation and job['id']==self.graph_operation['job_id'] and job['task']=='paper_relationships' and job['status'] in {'completed','partial'}
        if job['task'] not in {'discover_papers','paper_relationships','import_graph_papers','verify_paper_metadata'} or (not direct and job['status'] not in {'running','waiting_user'}):
            raise DomainError('scope_violation',409)
        if direct:
            self.active(job['id'])
            job={**job,'context':{**job['context'],'scope':{**job['context']['scope'],'domain_id':self.graph_operation.get('domain')}}}
        if not str(job['context'].get('external_network','')).startswith('user_requested'):raise DomainError('scope_violation',409)
        if download and (job['task']=='verify_paper_metadata' or (job['task']=='paper_relationships' and job['id'] not in self.graph_candidates)):raise DomainError('scope_violation',409)
        state=self.manager.status()
        config=state.get('config') or next((s['config'] for s in state.get('sites',[])),None)
        if not config and not download:raise DomainError('institution_configuration_required',409)
        return job,config

    def guard_paper(self,job,paper):
        if not isinstance(paper,dict):raise DomainError('invalid_request')
        search=job['context'].get('literature_search',{})
        year=paper.get('year')
        if isinstance(year,bool) or not isinstance(year,int) or not 1500<=year<=2200:raise DomainError('scope_violation',409)
        candidates=self.graph_candidates.get(job['id'],job['context'].get('paper_graph_selection',{}).get('candidates',[]))
        if job['task']=='import_graph_papers' or job['id'] in self.graph_candidates:
            matches=[p for p in candidates if p.get('id')==paper.get('candidate_id')]
            if len(matches)!=1 or matches[0].get('year')!=year or normalize(matches[0]['title'])!=normalize(str(paper.get('title',''))) or (matches[0].get('doi') and str(matches[0]['doi']).lower()!=str(paper.get('doi','')).lower()):
                raise DomainError('scope_violation',409)
        elif not search.get('from_year',1500)<=year<=search.get('to_year',2200):raise DomainError('scope_violation',409)
        count=len(candidates) if candidates else job['context'].get('literature_search',{}).get('target_count',10)
        count=max(1,min(100,int(count)*(10 if job['task']=='discover_papers' else 1)))
        key=paper.get('candidate_id') or paper.get('doi')
        if not isinstance(key,str) or not key or len(key)>200:raise DomainError('institution_identity_required')
        seen=self.requests.setdefault(job['id'],set())
        if key not in seen and len(seen)>=count:raise DomainError('scope_violation',409)
        seen.add(key)

    def wait(self,identifier,job_id,timeout=120,manager=None):
        manager=manager or self.manager
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            state=manager.status()
            # Cancellation/closing an originating task cancels its browser operation too.
            try:active=self.active(job_id)
            except DomainError:
                manager.cancel();raise
            if not active:
                manager.cancel();return {'status':'unavailable','reason':'originating_task_stopped'}
            if state.get('target_id')==identifier and state.get('pdf_ready'):return {'status':'ready'}
            lookup=manager.read('lookup.json',{})
            if lookup.get('target_id')==identifier:return {'status':'metadata','result':lookup}
            if not state.get('pending') and state.get('reason') not in {'browser_starting','browser_ready','user_login_required','user_reported_login_complete'}:
                return {'status':'needs_user' if state.get('state') in {'expired','awaiting_login'} or 'requires_user' in state.get('reason','') or state.get('approval') or state.get('reason')=='redirect_scope_blocked' else 'unavailable','reason':state.get('reason','browser_not_ready')}
            time.sleep(.25)
        manager.cancel()
        settled=time.monotonic()+3
        while time.monotonic()<settled:
            if not manager.status().get('pending'):return {'status':'unavailable','reason':'bounded_request_timeout'}
            time.sleep(.1)
        manager.command('show')
        return {'status':'needs_user','reason':'browser_cancel_pending'}

    async def acquire(self,body):
        try:await asyncio.wait_for(self.acquisition_queue.acquire(),PUBLISHER_QUEUE_TIMEOUT_SECONDS)
        except TimeoutError:raise DomainError('institution_queue_timeout',409)
        try:return await self.acquire_one(body)
        finally:self.acquisition_queue.release()

    async def acquire_one(self,body):
        job,config=self.scope(body,True)
        paper=body.get('paper');self.guard_paper(job,paper)
        from .paper_bibliography import get as get_record,outcome
        record=get_record(self.store,paper['citation_record_id']) if paper.get('citation_record_id') else None
        if record and job['context']['scope'].get('domain_id') and job['context']['scope']['domain_id'] not in record['domain_ids']:raise DomainError('scope_violation',409)
        async def record_outcome(status,**details):
            if record:
                clean={'operation_id':uid('op')}
                await self.write('paper_record_pdf',clean,lambda:outcome(self.store,record['id'],status,**details))
        choices=paper.get('sources',[])
        if not isinstance(choices,list) or not 0<=len(choices)<=3 or any(not isinstance(c,dict) for c in choices):raise DomainError('institution_manifest_required')
        # The synchronous/manual client may own the lock. Busy is transient,
        # not a failed article: wait within the article's bounded request.
        deadline=time.monotonic()+30
        while not self.manager.broker_lock.acquire(blocking=False):
            if not self.active(job['id']):raise DomainError('originating_task_stopped',409)
            if time.monotonic()>=deadline:raise DomainError('institution_queue_timeout',409)
            await asyncio.sleep(.1)
        try:
            cached=(record or {}).get('public_download_sources',[])
            from .research_policy import source_priority,institution_timeout,authenticated_account,public_source
            publisher_only=body.get('publisher_only') is True
            choices=[c for c in choices if not publisher_only or c.get('public_oa') is not True]
            if not publisher_only:choices=[*choices,*[c for c in cached[:3] if c.get('access_url') not in {s.get('access_url') for s in choices}]]
            if record and record.get('publication_status')=='published' and record.get('latest_verified'):
                from .research_import import publisher_source
                publisher=publisher_source(record)
                if not any(c.get('publisher_url')==publisher['publisher_url'] and c.get('public_oa') is not True for c in choices):choices.insert(0,publisher)
            choices=sorted(choices,key=lambda c:source_priority(c,record))
            failures=[];blocked=[];attempted=set()
            def pause(reason,**details):
                blocked.append({'status':'needs_user','reason':reason,**details})
                failures.append(reason)
            # Try bounded exact-paper public sources after the existing plans.
            has_arxiv=any(urlsplit(str(c.get('access_url') or c.get('publisher_url',''))).hostname in {'arxiv.org','export.arxiv.org'} for c in choices)
            if not publisher_only:
                from .institutional_access import rss_pdf_url
                if record and rss_pdf_url(record.get('doi')):choices.append('proceedings')
                choices.append('index')
                if not has_arxiv:choices.append('arxiv')
            for source in choices:
                if not self.active(job['id']):
                    return {'status':'unavailable','reason':'originating_task_stopped','candidate_id':paper.get('candidate_id')}
                if isinstance(source,str):
                    provider=source
                    location_key=(job['id'],paper.get('candidate_id') or paper.get('doi'),provider)
                    if location_key in self.public_locations:
                        located=self.public_locations[location_key]
                        if isinstance(located,str):failures.append(located);continue
                        record,source=located
                    else:
                        # Public source authorization is task-scoped, independent
                        # of institution login/redirect origin confirmations.
                        lookup_host={'arxiv':'arxiv.org','index':'api.semanticscholar.org','proceedings':'www.roboticsproceedings.org'}[provider]
                        if lookup_host in self.public_blocks:
                            pause(self.public_blocks[lookup_host]);continue
                        try:
                            from .research_download import locate_public,locate_index,locate_proceedings
                            locator={'arxiv':locate_public,'index':locate_index,'proceedings':locate_proceedings}[provider]
                            updated,source=await locator(record)
                            if not self.active(job['id']):raise DomainError('originating_task_stopped',409)
                            from .paper_bibliography import save
                            record=await self.write('public_source_identity',{'operation_id':uid('op')},lambda:save(self.store,updated,job['context']['scope'].get('domain_id')))
                            self.public_locations[location_key]=(record,source)
                        except DomainError as exc:
                            if exc.code in {'citation_source_unavailable','public_index_unavailable'} and exc.params.get('http_status') in {403,429}:
                                self.public_blocks[lookup_host]='public_locator_requires_user'
                                pause('public_locator_requires_user');continue
                            self.public_locations[location_key]=exc.code;failures.append(exc.code);continue
                public=source.get('public_oa') is True
                if public and not public_source(source,record):
                    failures.append('publisher_open_access_not_verified');continue
                source_url=safe_url(source.get('access_url') or source.get('publisher_url'),public_copy=public)
                if source_url in attempted:continue
                attempted.add(source_url)
                public_host=urlsplit(source_url).hostname if public else None
                if public:
                    from .research_download import permitted_public_host
                    if not permitted_public_host(public_host,record,source_url):
                        failures.append('public_pdf_source_outside_policy');continue
                if public_host in self.public_blocks:
                    pause(self.public_blocks[public_host]);continue
                manager=None;site_id=None
                # Institution origins govern only controlled browser transfers.
                # Legal public sources use their own policy and PDF identity checks.
                if not config and not public:
                    failures.append('institution_not_connected');continue
                if config and not public:
                    known_state=self.manager.status()
                    if not known_state.get('sites') and (known_state.get('approval') or 'requires_user' in known_state.get('reason','')):
                        pause('official_site_confirmation_required' if known_state.get('approval') else known_state['reason']);continue
                try:
                    if config and not public:site_id,manager=self.manager.route_session(source.get('publisher_url'),source.get('site_id'),public=False)
                except DomainError as exc:
                    if exc.code not in {'institution_site_required','institution_site_ambiguous'}:raise
                    # An account for a different publisher is not authorization
                    # for this one. Continue public lookup without a login prompt.
                    failures.append(exc.code);continue
                self.manager.request_site_id=site_id
                state=manager.status() if manager else {}
                if manager and not authenticated_account(state) and state.get('verified_pdf') and state.get('state') not in {'expired','awaiting_login','unconfigured'}:
                    state=await self.resume_account(manager,job['id'])
                if not public and not authenticated_account(state):
                    failures.append('publisher_not_authenticated_public_direct');continue
                source_config=manager.status()['config'] if manager else {'method':'publisher','allowed_origins':[]}
                if manager and manager.status().get('approval'):
                    pause('official_site_confirmation_required',site_id=site_id);continue
                request={**source,**{k:paper.get(k) for k in ['doi','title','authors','year','venue']},'identity_confirmed':True,'automatic':True,'asserted_by':'job_source_evidence',**({'citation_record':record} if record else {})}
                if record:
                    if not source.get('pdf_identity'):
                        request['pdf_identity']={'title':paper['title'],'authors':paper['authors'],**({'doi':paper['doi']} if paper.get('doi') else {'arxiv_id':record.get('arxiv_id')})}
                    request.update({k:record.get(k) for k in ['doi','title','authors','year','venue']})
                if not manager:
                    # These URLs are still validated by paper_request and fetch_pdf's
                    # repository/publisher policy and SSRF/redirect checks.
                    source_config['allowed_origins']=list({urlsplit(safe_url(request[k],public_copy=True)).scheme+'://'+urlsplit(safe_url(request[k],public_copy=True)).netloc for k in ['publisher_url','access_url','metadata_url','version_source_url'] if request.get(k)})
                hosts={urlsplit(u).hostname for u in source_config['allowed_origins']}
                missing_site=None
                for key in ['publisher_url','access_url','version_source_url']:
                    if request.get(key):
                        url=safe_url(request[key],public_copy=public)
                        if key=='publisher_url' and record and url in {record.get('publisher_url'),record.get('url')}:continue
                        if urlsplit(url).hostname not in hosts:
                            manager.require_site(url);missing_site=urlsplit(url).hostname;break
                if missing_site:
                    pause('official_site_confirmation_required',site=missing_site);continue
                if source_config['method']=='proxy' and not public and source_config.get('proxy_template'):
                    original=safe_url(source.get('access_url') or source.get('publisher_url'))
                    if urlsplit(original).hostname!=urlsplit(source_config['entry_url']).hostname:
                        request['access_url']=source_config['proxy_template'].replace('{url}',quote(original,safe=''))
                    request['metadata_url']=request['access_url']
                paper_request(request,source_config,public_copy=public) # Public proof is rechecked before transfer; account requests remain HTTPS.
                denied_target=manager.read('target.json',{}) if manager else {}
                same_denied_paper=denied_target.get('doi')==request.get('doi') and denied_target.get('access_url')==request.get('access_url')
                if state.get('reason')=='subscription_denied' and same_denied_paper and source.get('public_oa') is not True:
                    failures.append('subscription_denied');continue
                if 'requires_user' in state.get('reason','') or state.get('reason')=='redirect_scope_blocked':
                    pause(state['reason']);continue
                if state.get('pending') or state.get('pdf_ready'):raise DomainError('institution_download_busy',409)
                # Rate limit applies across manual and automatic clients; no unbounded retry.
                delay=5-(time.monotonic()-getattr(manager or self.manager,'last_attempt',0))
                if delay>0:await asyncio.sleep(delay)
                if failures and request.get('pdf_version')!='published':
                    request['fallback_reason']=(str(source.get('fallback_reason',''))+'; '+'; '.join(failures))[:500]
                if public:
                    from .research_download import acquire as acquire_public
                    async def guarded_write(kind,clean,action):
                        def active_action():
                            if not self.active(job['id']):raise DomainError('originating_task_stopped',409)
                            return action()
                        return await self.write(kind,clean,active_action)
                    (manager or self.manager).last_attempt=time.monotonic()
                    try:
                        imported=await acquire_public(self.store,paper,record,request,guarded_write,job['context']['scope'].get('domain_id'),body.get('timeout_seconds',25))
                    except DomainError as exc:
                        if exc.code in {'public_pdf_requires_user','public_pdf_http_403','public_pdf_http_429'}:
                            # Keep the actual source challenge; other public sites
                            # remain independent. Do not retry this source via WebView.
                            self.public_blocks[public_host]=exc.code
                            pause(exc.code);continue
                        if exc.code=='official_site_confirmation_required':pause(exc.code);continue
                        if exc.code=='originating_task_stopped':return {'status':'unavailable','reason':exc.code,'candidate_id':paper.get('candidate_id')}
                        failures.append(exc.code);continue
                    except (OSError,TimeoutError) as exc:
                        failures.append('public_pdf_request_failed:'+type(exc).__name__);continue
                    await record_outcome('acquired',resource_id=imported['resource_id'],pdf_version=imported['acquisition']['pdf_version'])
                    return {**imported,'candidate_id':paper.get('candidate_id'),'existing_annotations_preserved':True,'warnings':failures,'site_id':site_id}
                state=await asyncio.to_thread(manager.test,request)
                identifier=manager.read('target.json',{})['id']
                timeout=institution_timeout(body,job)
                result=await asyncio.to_thread(self.wait,identifier,job['id'],timeout,manager)
                if result['status']=='ready':
                    domain=job['context']['scope'].get('domain_id')
                    clean={'operation_id':uid('op'),'domain':domain} if domain else {'operation_id':uid('op')}
                    imported=await self.write('institutional_job_import',clean,lambda:manager.import_result(clean))
                    if getattr(self,'paper_metadata',None) and not imported.get('metadata_verification'):
                        imported=await self.paper_metadata.imported(imported,paper)
                    resource=imported['resource']
                    await record_outcome('acquired',resource_id=resource['id'],pdf_version=resource['metadata'].get('pdf_version','unknown'))
                    return {'status':'imported','candidate_id':paper.get('candidate_id'),'resource_id':resource['id'],
                            'version_id':resource['version_id'],'sha256':resource['sha256'],'acquisition':imported['acquisition'],
                            'metadata_verification':imported.get('metadata_verification'),
                            'existing_annotations_preserved':imported['existing_annotations_preserved'],'warnings':failures,'site_id':site_id}
                if result['status']=='needs_user':
                    if result.get('reason')=='subscription_denied':failures.append('subscription_denied');continue
                    pause(result.get('reason'));continue
                failures.append(result['reason'])
            if blocked:
                await record_outcome('needs_user',reason='; '.join(failures))
                return {**blocked[0],'candidate_id':paper.get('candidate_id'),'warnings':failures,'blocked_sources':blocked}
            await record_outcome('unavailable',reason='; '.join(failures))
            return {'status':'unavailable','candidate_id':paper.get('candidate_id'),'reason':'; '.join(failures)}
        finally:
            self.manager.request_site_id=None
            self.manager.broker_lock.release()

    async def lookup(self,body):
        job,config=self.scope(body)
        url=safe_url(body.get('url'))
        frozen=None
        if job['task']=='verify_paper_metadata':
            frozen=next((r for r in job['context']['resources'] if r['resource_id']==body.get('resource_id')),None)
            if not frozen or frozen['type']!='paper':raise DomainError('scope_violation',409)
            resource=self.store.resource(frozen['resource_id'])
            if resource['version_id']!=frozen['version_id']:raise DomainError('version_conflict',409)
            original=[resource['metadata'].get('publisher_url'),resource['metadata'].get('url')]+[s.get('url') for s in resource['metadata'].get('field_sources',{}).values() if isinstance(s,dict)]
            approved=[]
            for value in original:
                try:approved.append(safe_url(value))
                except DomainError:pass
            if url not in approved:raise DomainError('scope_violation',409)
        try:site_id,manager=self.manager.route_session(url,body.get('site_id'),public=True)
        except DomainError as exc:
            if exc.code not in {'institution_site_required','institution_site_ambiguous'}:raise
            return {'status':'needs_user','reason':exc.code,'site':exc.params.get('site')}
        config=manager.status()['config']
        if urlsplit(url).hostname not in {urlsplit(u).hostname for u in config['allowed_origins']}:
            manager.require_site(url,'metadata_request')
            return {'status':'needs_user','reason':'official_site_confirmation_required','site':urlsplit(url).hostname}
        if config['method']=='proxy' and config.get('proxy_template') and urlsplit(url).hostname!=urlsplit(config['entry_url']).hostname:
            url=safe_url(config['proxy_template'].replace('{url}',quote(url,safe='')))
        # Metadata search is separately recorded; never proves PDF subscription rights.
        count=self.requests.setdefault('lookup:'+job['id'],set())
        if len(count)>=20:raise DomainError('institution_rate_limited',429)
        if not manager.broker_lock.acquire(blocking=False):raise DomainError('institution_download_busy',409)
        try:
            self.manager.request_site_id=site_id
            state=manager.status()
            if state.get('approval'):return {'status':'needs_user','reason':'official_site_confirmation_required'}
            if 'requires_user' in state.get('reason','') or state.get('reason') in {'subscription_denied','redirect_scope_blocked'}:
                return {'status':'needs_user','reason':state['reason']}
            if state.get('pending') or state.get('pdf_ready'):raise DomainError('institution_download_busy',409)
            if state['state']=='expired':
                await asyncio.to_thread(manager.connect)
                return {'status':'needs_user','reason':'institution_login_required'}
            # Original public bibliographic pages may be read without PDF entitlement.
            # The same profile is reused; an actual login/challenge page still pauses.
            if state['state']=='awaiting_login':await asyncio.to_thread(manager.connect,True)
            if not state['online']:await asyncio.to_thread(manager.connect,True)
            delay=5-(time.monotonic()-manager.last_attempt)
            if delay>0:await asyncio.sleep(delay)
            count.add(url);manager.last_attempt=time.monotonic()
            target={'id':str(uuid.uuid4()),'kind':'lookup','access_url':url,'automatic':True,'prior_state':state['state'],
                    'prior':{k:state[k] for k in ['tested_at','tested_site','doi'] if k in state}}
            atomic_json(manager.root/'status.json',{'state':'awaiting_test','pending':target['id'],'reason':'metadata_lookup'})
            manager.command('test',target)
            response=await asyncio.to_thread(self.wait,target['id'],job['id'],60,manager)
            if frozen and response.get('status')=='metadata':
                from .acquisition_metadata import reverify
                clean={'operation_id':uid('op'),'resource_id':frozen['resource_id'],'version_id':frozen['version_id']}
                verification=await self.write('institutional_metadata_verify',clean,lambda:reverify(self.store,frozen,response['result']))
                response={**response,'metadata_verification':verification}
            return response
        finally:
            self.manager.request_site_id=None
            self.manager.broker_lock.release()
