"""kw: all business writes go through the same HTTP API as the browser."""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import urllib.parse
from .safety import DomainError
from .project_catalog import read as read_catalog, resolve
from pathlib import Path
from .store import uid


def acquire_manifest(request,job_id,papers):
    """A source gate pauses its own row; other scoped candidates still run."""
    rows=[request('/institutional/acquire',{'job_id':job_id,'paper':paper}) for paper in papers]
    return {'results':rows,'paused':any(row.get('status')=='needs_user' for row in rows)}


def run():
    parser = argparse.ArgumentParser(prog='kw')
    parser.add_argument('--project', default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--json', action='store_true')
    subs = parser.add_subparsers(dest='command', required=True)
    serve = subs.add_parser('serve')
    serve.add_argument('--resource-root')
    serve.add_argument('--project', dest='serve_project')
    serve.add_argument('--ui-root')
    subs.add_parser('doctor')
    subs.add_parser('scan')
    subs.add_parser('backup')
    agent=subs.add_parser('agent').add_subparsers(dest='action',required=True)
    agent.add_parser('status')
    agent.add_parser('disconnect')
    for action in ['connect','worker']:
        a=agent.add_parser(action);a.add_argument('--command-file')
        a.add_argument('--builtin',choices=['codex'])
    citations=subs.add_parser('citations').add_subparsers(dest='action',required=True)
    citations.add_parser('list')
    citation=citations.add_parser('resolve');citation.add_argument('--doi');citation.add_argument('--arxiv');citation.add_argument('--job');citation.add_argument('--domain');citation.add_argument('--consent',action='store_true');citation.add_argument('--resource');citation.add_argument('--pdf-identity')
    citation=citations.add_parser('export');citation.add_argument('id');citation.add_argument('--job');citation.add_argument('--consent',action='store_true');citation.add_argument('--format',choices=['text','ris','json'],default='text')
    institution=subs.add_parser('institutional').add_subparsers(dest='action',required=True)
    institution.add_parser('status')
    candidates=institution.add_parser('candidates');candidates.add_argument('--job',required=True)
    for command in ['acquire','lookup']:
        s=institution.add_parser(command);s.add_argument('--job',required=True)
        if command=='acquire':s.add_argument('--manifest',required=True)
        else:s.add_argument('--url',required=True);s.add_argument('--site');s.add_argument('--resource')
    project_cli=subs.add_parser('project').add_subparsers(dest='action',required=True)
    project_cli.add_parser('catalog')
    project_cli.add_parser('state')
    project_cli.add_parser('migrate-layout')
    view=project_cli.add_parser('view');view.add_argument('--domain');view.add_argument('--knowledge-base');view.add_argument('--resource');view.add_argument('--type',choices=['all','paper','code','link'],default='all')
    view.add_argument('--page',choices=['library','papers','code','kb','discover','jobs','settings'],default='library')
    domains=subs.add_parser('domains').add_subparsers(dest='action',required=True)
    domains.add_parser('list')
    domain=domains.add_parser('show');domain.add_argument('name');domain.add_argument('--type',choices=['all','paper','code','link'],default='all')
    domain=domains.add_parser('add');domain.add_argument('name');domain.add_argument('--resource',required=True)
    domain=domains.add_parser('create');domain.add_argument('name')
    imp=subs.add_parser('import');imp.add_argument('--path',required=True);target=imp.add_mutually_exclusive_group(required=True);target.add_argument('--domain');target.add_argument('--library',action='store_true');imp.add_argument('--metadata')
    tasks=subs.add_parser('tasks').add_subparsers(dest='action',required=True)
    task=tasks.add_parser('create');task.add_argument('--domain',required=True);task.add_argument('--question',required=True);task.add_argument('--task',default='read_resources');task.add_argument('--type',choices=['all','paper','code'],default='all')
    office=subs.add_parser('office').add_subparsers(dest='action',required=True)
    native=office.add_parser('native');native.add_argument('id')
    native.add_argument('--operation',choices=['equations','prepare','audit','render_word'],required=True)
    native.add_argument('--presentation',required=True);native.add_argument('--manifest')
    for action in ['prepare','build','revise','finish']:
        o=office.add_parser(action);o.add_argument('id')
        if action in {'build','revise'}:o.add_argument('--content',required=True)
        if action=='finish':
            o.add_argument('--reviewed-image',action='append',required=True);o.add_argument('--if-revision',type=int,required=True)
            o.add_argument('--manifest-only',action='store_true')
    word=subs.add_parser('word').add_subparsers(dest='action',required=True)
    word.add_parser('sessions')
    w=word.add_parser('sources');w.add_argument('--domain',required=True)
    w=word.add_parser('open');w.add_argument('--document',required=True);w.add_argument('--hidden',action='store_true')
    w=word.add_parser('new');w.add_argument('--name',required=True);w.add_argument('--text-file');w.add_argument('--hidden',action='store_true')
    for command in ['inspect','bibliography','refresh','save','close','cite','style','format']:
        w=word.add_parser(command);w.add_argument('--session',required=True);w.add_argument('--operation-id')
        if command=='cite':
            w.add_argument('--domain',required=True);w.add_argument('--resource',action='append',required=True)
            where=w.add_mutually_exclusive_group(required=True);where.add_argument('--paragraph',type=int);where.add_argument('--selection',action='store_true')
            w.add_argument('--if-text-hash',required=True)
        elif command=='style':w.add_argument('--name',choices=['IEEE_SUPERSCRIPT','IEEE','APA','GB7714'],required=True)
        elif command=='format':
            w.add_argument('--font');w.add_argument('--size',type=float);w.add_argument('--spacing',type=float)
    resource = subs.add_parser('resources').add_subparsers(dest='action', required=True)
    listing = resource.add_parser('list')
    listing.add_argument('--type', choices=['paper', 'code', 'link'])
    show = resource.add_parser('show')
    show.add_argument('id')
    show.add_argument('--version')
    update=resource.add_parser('update');update.add_argument('id');update.add_argument('--metadata',required=True);update.add_argument('--if-revision',type=int,required=True)
    for command in ['knowledge-bases', 'groups', 'jobs', 'papers', 'relations']:
        sub = subs.add_parser(command).add_subparsers(dest='action', required=True)
        if command in ['knowledge-bases', 'jobs']:
            sub.add_parser('list')
            s = sub.add_parser('show'); s.add_argument('id')
        if command == 'knowledge-bases':
            s = sub.add_parser('create'); s.add_argument('--name', required=True); s.add_argument('--selection', required=True); s.add_argument('--layers')
            s = sub.add_parser('query'); s.add_argument('id'); s.add_argument('question')
            s = sub.add_parser('assemble'); s.add_argument('id'); s.add_argument('--job',required=True); s.add_argument('--if-revision',type=int,required=True)
            s = sub.add_parser('cards'); s.add_argument('id')
            s = sub.add_parser('add-resources');s.add_argument('id');s.add_argument('--resource',action='append',required=True);s.add_argument('--if-revision',type=int,required=True)

        elif command == 'jobs':
            s = sub.add_parser('create'); s.add_argument('--spec', required=True)
            s = sub.add_parser('ingest'); s.add_argument('id'); s.add_argument('--manifest', required=True); s.add_argument('--if-revision', type=int, required=True)
            for action in ['claim', 'fail', 'run']:
                s = sub.add_parser(action); s.add_argument('id'); s.add_argument('--if-revision', type=int, required=True)
                if action == 'fail':s.add_argument('--reason', required=True)
        elif command == 'groups':
            s = sub.add_parser('create'); s.add_argument('--name', required=True)
            s = sub.add_parser('add'); s.add_argument('--resource', required=True); s.add_argument('--group', required=True); s.add_argument('--if-revision', type=int, required=True)
        elif command == 'papers':
            s = sub.add_parser('rename-plan'); s.add_argument('--selection', required=True)
            s = sub.add_parser('rename'); s.add_argument('--spec', required=True)
        else:
            s = sub.add_parser('propose'); s.add_argument('--spec', required=True)
    args = parser.parse_args()
    from .layout import project_root,identity
    from .safety import contained
    args.project=str(project_root(args.project))
    if '--port' not in sys.argv:
        from .layout import data_path
        config_file=data_path(args.project,'.knowledge/config.json')
        if config_file.is_file():
            configured_port=json.loads(config_file.read_text('utf-8')).get('port')
            if isinstance(configured_port,int) and 1024<=configured_port<=65535:
                args.port=configured_port
        elif args.command in {'serve','agent'}:
            from desktop_entry import connection
            _,args.port=connection(Path(args.project))
    if args.command=='agent':
        from .agent_worker import run as agent_run
        try:print(json.dumps(agent_run(args),ensure_ascii=False,indent=2));return
        except Exception as exc:
            print(json.dumps({'code':getattr(exc,'code','agent_connection_failed')},ensure_ascii=False),file=sys.stderr);sys.exit(1)
    if args.command=='project' and args.action=='migrate-layout':
        from .migrate_layout import run as migrate
        print(json.dumps(migrate(args.project),ensure_ascii=False,indent=2));return
    if args.command=='word':
        # Document operations use their own isolated Word worker, never a model/API bridge.
        from . import word_bridge
        from .word_sources import domain_sources
        from .safety import contained
        try:
            project=Path(args.project).resolve()
            if args.action=='sessions':result=word_bridge.sessions(project)
            elif args.action=='sources':result=domain_sources(project,args.domain)
            elif args.action=='open':result=word_bridge.start(project,document=args.document,visible=not args.hidden)
            elif args.action=='new':result=word_bridge.start(project,name=args.name,text=contained(project,args.text_file).read_text('utf-8-sig') if args.text_file else '',visible=not args.hidden)
            else:
                params={}
                if args.action=='cite':
                    params={'sources':domain_sources(project,args.domain,args.resource)['sources'],
                            'paragraph':args.paragraph,'selection':args.selection,'if_text_hash':args.if_text_hash}
                elif args.action=='style':params={'name':args.name}
                elif args.action=='format':params={'formatting':{key:getattr(args,key) for key in ['font','size','spacing'] if getattr(args,key) is not None}}
                result=word_bridge.request(project,args.session,args.action,operation_id=args.operation_id,**params)
            print(json.dumps(result,ensure_ascii=False,indent=2));return
        except DomainError as exc:
            print(json.dumps({'code':exc.code,'params':exc.params},ensure_ascii=False),file=sys.stderr);sys.exit(1)
    # Agent reads work even when the visual app is closed. This is a published snapshot,
    # never a second writer to SQLite.
    if args.command=='project' and args.action in {'catalog','state'} or args.command=='domains' and args.action in {'list','show'}:
        try:
            data=read_catalog(args.project)
            if args.command=='project':
                result=data if args.action=='catalog' else json.loads(contained(args.project,'workspace/view.json').read_text('utf-8'))
            elif args.action=='list':
                result=data['domains']
            else:
                g=resolve(data['domains'],args.name,'group')
                result={**g,'resources':[r for r in data['resources'] if r['id'] in g['resource_ids'] and (args.type=='all' or r['type']==args.type)],'catalog_sequence':data['event_sequence']}
            print(json.dumps(result,ensure_ascii=False,indent=2));return
        except DomainError as exc:
            print(json.dumps({'code':exc.code,'params':exc.params},ensure_ascii=False),file=sys.stderr);sys.exit(1)
    if args.command == 'serve':
        import msvcrt
        lock_dir = contained(project_root(args.serve_project or args.project),'.knowledge',False)
        lock_dir.mkdir(parents=True,exist_ok=True)
        instance_lock = (lock_dir / 'server.lock').open('a+b')
        instance_lock.seek(0)
        instance_lock.write(b'0')
        instance_lock.flush()
        instance_lock.seek(0)
        try:
            msvcrt.locking(instance_lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            print('A workbench instance is already running for this project.', file=sys.stderr)
            sys.exit(1)
        from .app import create_app
        import uvicorn
        from .retention import logging_config
        import logging.config
        logs=logging_config(lock_dir);logging.config.dictConfig(logs)
        uvicorn.run(create_app(args.serve_project or args.project, args.resource_root,ui_root=args.ui_root), host='127.0.0.1', port=args.port, workers=1,access_log=False,log_config=logs)
        return
    base = 'http://127.0.0.1:' + str(args.port) + '/api/v1'
    def request(path, body=None, method=None):
        headers = {'Content-Type': 'application/json'}
        if body is not None:
            headers['X-KW-Token'] = token
            body.setdefault('operation_id', uid('op'))
        req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None, headers, method=method)
        with urllib.request.urlopen(req, timeout=360 if path.startswith('/institutional/') else 180) as resp:
            return json.load(resp)
    def load(path):
        file=Path(path)
        if not file.is_absolute() and not file.exists():file=contained(args.project,path)
        return json.loads(file.read_text('utf-8-sig'))
    try:
        # Verify the connected server owns this project before any reads or writes.
        import hashlib
        health=request('/health')
        if health.get('project_id')!=identity(args.project):
            raise DomainError('project_mismatch',409)
        token = request('/session')['token']
        if args.command=='citations':
            if args.action=='list':result=request('/paper-records')
            elif args.action=='export':result=request('/paper-records/'+args.id+'/export',{'job_id':args.job,'consent':args.consent,'format':args.format})
            else:
                domain=resolve(request('/groups'),args.domain,'group')['id'] if args.domain else None
                result=request('/paper-records/resolve',{'doi':args.doi,'arxiv_id':args.arxiv,'job_id':args.job,'domain_id':domain,'consent':args.consent,'resource_id':args.resource,'pdf_identity':load(args.pdf_identity) if args.pdf_identity else None})
        elif args.command=='institutional':
            if args.action=='status':
                state=request('/institutional')
                result={k:state.get(k) for k in ['state','online','reason','tested_at','tested_site']}
                result['configured']=bool(state.get('config') or state.get('sites'))
                result['approved_sites']=[urllib.parse.urlsplit(u).hostname for u in (state.get('config') or {}).get('allowed_origins',[])]
                result['sites']=[{k:site.get(k) for k in ['id','name','hostname','state','online','task_ready','login_reported_at','verified_pdf']} for site in state.get('sites',[])]
            elif args.action=='candidates':result=request('/institutional/candidates',{'job_id':args.job})
            elif args.action=='lookup':result=request('/institutional/lookup',{'job_id':args.job,'url':args.url,'site_id':args.site,'resource_id':args.resource})
            else:
                papers=load(args.manifest)
                if isinstance(papers,dict):papers=papers.get('papers',[papers])
                if not isinstance(papers,list) or not 1<=len(papers)<=10:raise DomainError('institution_manifest_required')
                result=acquire_manifest(request,args.job,papers)
        elif args.command=='office':
            if args.action=='native':
                result=request('/jobs/'+args.id+'/office-native',{'operation':args.operation,'presentation':args.presentation,'manifest':args.manifest})
                print(json.dumps(result,ensure_ascii=False,indent=2));return
            from . import office_extract
            project=Path(args.project).resolve()
            current=request('/jobs/'+args.id)
            if args.action in {'prepare','build','revise'}:
                params={'base_revision':current['revision']}
                if args.action in {'build','revise'}:params['content']=args.content
                result=request('/jobs/'+args.id+'/office-extract/'+args.action,params)
                print(json.dumps(result,ensure_ascii=False,indent=2));return
            if current['revision']!=args.if_revision:raise DomainError('revision_conflict',409)
            if current['status']=='completed':raise DomainError('office_output_exists')
            result_manifest,file=office_extract.finish(project,args.id,args.reviewed_image)
            if args.manifest_only:
                result={'id':args.id,'manifest':str(file),'ready_for_bridge':True,'native_equations':result_manifest['office_fragment']['native_equations']}
                print(json.dumps(result,ensure_ascii=False,indent=2));return
            result=request('/jobs/'+args.id+'/ingest',{'manifest':result_manifest,'base_revision':args.if_revision})
            timing=office_extract.mark_ingested(project,args.id,result['revision'])
            result={'id':result['id'],'status':result['status'],'revision':result['revision'],'manifest':str(file),
                    'native_equations':result['result']['office_fragment']['native_equations'],'timing':timing}
        elif args.command=='project':
            result=request('/project/view',{'route':'domain' if args.domain else 'kb' if args.knowledge_base else args.page,'domain':args.domain,'knowledge_base':args.knowledge_base,'resource':args.resource,'type':args.type})
        elif args.command=='domains':
            if args.action=='create':
                result=request('/groups',{'name':args.name})
            else:
                g=resolve(request('/groups'),args.name,'group')
                result=request('/groups/'+g['id']+'/members',{'base_revision':g['revision'],'resource_ids':list(dict.fromkeys(g['resource_ids']+[args.resource]))},'PUT')
        elif args.command=='import':
            result=request('/project/import',{'path':args.path,'domain':args.domain,'destination':'library' if args.library else 'domain','metadata':load(args.metadata) if args.metadata else {}})
        elif args.command=='tasks':
            result=request('/project/jobs',{'domain':args.domain,'question':args.question,'task':args.task,'type':args.type})
        elif args.command == 'doctor':
            result = request('/health')
            result.update({'codex_installed': bool(__import__('shutil').which('codex')), 'claude_installed': bool(__import__('shutil').which('claude')), 'python': sys.version, 'project': args.project})
            from .skills import inventory
            result['installed_skills']=inventory(args.project)
        elif args.command in {'scan', 'backup'}:
            result = request('/' + args.command, {})
        elif args.command == 'resources':
            if args.action=='update':
                result=request('/resources/'+args.id,{**load(args.metadata),'base_revision':args.if_revision},'PATCH')
            else:
                result = request('/resources' + ('?type=' + args.type if args.action == 'list' and args.type else '') if args.action == 'list' else '/resources/' + args.id)
            if args.action == 'show' and args.version:
                result['requested_version'] = next((v for v in result['versions'] if v['id'] == args.version), None)
        elif args.action == 'list':
            result = request('/' + args.command)
        elif args.action == 'show':
            result = request('/' + args.command + '/' + args.id)
        elif args.command == 'knowledge-bases':
            if args.action=='add-resources':result=request('/knowledge-bases/'+args.id+'/add-resources',{'resource_ids':args.resource,'base_revision':args.if_revision})
            elif args.action=='assemble':result=request('/knowledge-bases/'+args.id+'/assemble',{'job_id':args.job,'base_revision':args.if_revision})
            elif args.action=='cards':result=request('/knowledge-bases/'+args.id+'/cards')
            elif args.action == 'query':
                kb=request('/knowledge-bases/'+args.id)
                result = request('/knowledge-bases/' + args.id + '/query?q=' + urllib.parse.quote(args.question)+'&kb_revision='+str(kb['revision']))
            else:
                selection = load(args.selection)
                result = request('/knowledge-bases', {'name': args.name, 'resource_ids': selection if isinstance(selection, list) else selection['resource_ids'],**({'layers':load(args.layers)} if args.layers else {})})
        elif args.command == 'jobs':
            if args.action == 'create':
                result = request('/jobs', load(args.spec))
            elif args.action in {'claim', 'fail', 'run'}:
                result = request('/jobs/' + args.id + '/' + args.action, {'base_revision': args.if_revision, **({'reason': args.reason} if args.action == 'fail' else {})})
            else:
                result = request('/jobs/' + args.id + '/ingest', {'manifest': load(args.manifest), 'base_revision': args.if_revision})
        elif args.command == 'groups':
            if args.action == 'create':
                result = request('/groups', {'name': args.name})
            else:
                groups = request('/groups')
                g = next(g for g in groups if g['id'] == args.group)
                result = request('/groups/' + args.group + '/members', {'resource_ids': list(dict.fromkeys(g['resource_ids'] + [args.resource])), 'base_revision': args.if_revision}, 'PUT')
        elif args.command == 'papers':
            if args.action == 'rename-plan':
                selection = load(args.selection)
                result = request('/papers/rename-plan', {'resource_ids': selection if isinstance(selection, list) else selection['resource_ids'],**({'layers':load(args.layers)} if args.layers else {})})
            else:
                spec = load(args.spec)
                result = request('/resources/' + spec['resource_id'] + '/rename', spec)
        else:
            result = request('/relations', load(args.spec))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except DomainError as exc:
        print(json.dumps({'code':exc.code,'params':exc.params},ensure_ascii=False),file=sys.stderr)
        sys.exit(1)
    except urllib.error.HTTPError as exc:
        print(exc.read().decode(), file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError:
        print(json.dumps({'code': 'service_unavailable', 'hint': 'Run start-workbench.cmd first'}), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    run()
