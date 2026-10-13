"""Retryable exact-file deletion after committed object removal.

Only planned files and empty directories within managed roots are eligible.
Surviving references are rechecked before each cleanup; no recursive removal.
"""
import json
from .safety import contained,DomainError
from .storage_ownership import plan,walk_files

def execute(store,ownership):
    guard=plan(store,'resource',[],resources_only=ownership.get('resources_only',False))
    protected=[contained(store.project,p,False) for p in guard['protected_paths']]
    removed=[];retained=[];failures=[];released=0;removed_directories=[];pending_directories=[]
    for item in ownership['exclusive_files']:
        raw=item['path']
        try:
            path=contained(store.project,raw,False)
            allowed=[store.root,store.state,contained(store.project,'outputs',False),contained(store.project,'workspace',False)/'knowledge']
            if not any(p in path.parents for p in allowed):raise DomainError('storage_delete_outside_ownership')
            if any(path==p or p in path.parents for p in protected):retained.append(raw);continue
            if not path.exists():continue
            if not path.is_file():raise DomainError('storage_delete_requires_exact_file')
            walk_files(path)
            from .paper_storage import unlink_file
            size=path.stat().st_size;unlink_file(store,path);released+=size;removed.append(raw)
        except (OSError,DomainError) as exc:failures.append({'path':raw,'error':getattr(exc,'code',type(exc).__name__)})
    for raw in sorted(ownership.get('directories',[]),key=lambda p:len(p.split('/')),reverse=True):
        try:
            path=contained(store.project,raw,False)
            allowed=[store.root,store.state,contained(store.project,'outputs',False),contained(store.project,'workspace',False)/'knowledge']
            if path in allowed or not any(p in path.parents for p in allowed):raise DomainError('storage_delete_outside_ownership')
            if not path.exists():continue
            if any(path==p or p in path.parents or path in p.parents for p in protected):pending_directories.append(raw);continue
            if not path.is_dir():raise DomainError('storage_delete_requires_directory')
            # Never remove unplanned/new files, even if a writer raced with cancellation.
            path.rmdir();removed_directories.append(raw)
        except (OSError,DomainError) as exc:
            pending_directories.append(raw);failures.append({'path':raw,'error':getattr(exc,'code',type(exc).__name__)})
    return {'state':'pending' if failures else 'shared_references_retained' if retained or pending_directories else 'complete','released_bytes':released,'removed_files':removed,'removed_directories':removed_directories,'pending_directories':pending_directories,'retained_shared_paths':retained,'errors':failures}

def enqueue(store,value):
    files=value['exclusive_files']+[{'path':p,'bytes':0} for p in value['retained_shared_paths']]
    key='storage_delete:'+value['kind']+':'+','.join(value['ids'])
    store.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps({'exclusive_files':files,'directories':value.get('directories',[]),'resources_only':value['kind']=='job'},ensure_ascii=False)))

def drain(store):
    reports=[]
    for row in store.rows("SELECT key,value FROM settings WHERE key LIKE 'storage_delete:%'"):
        ownership=json.loads(row['value'])
        if row['key'].startswith('storage_delete:job:'):ownership['resources_only']=True
        report=execute(store,ownership);reports.append(report)
        pending=set(report['retained_shared_paths']+[v['path'] for v in report['errors']])
        if pending or report['pending_directories']:
            ownership['exclusive_files']=[v for v in ownership['exclusive_files'] if v['path'] in pending]
            ownership['directories']=report['pending_directories']
            store.db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(ownership,ensure_ascii=False),row['key']))
        else:store.db.execute('DELETE FROM settings WHERE key=?',(row['key'],))
    store.db.commit()
    return {'state':'pending' if any(r['errors'] for r in reports) else 'shared_references_retained' if any(r['retained_shared_paths'] or r['pending_directories'] for r in reports) else 'complete',
            'released_bytes':sum(r['released_bytes'] for r in reports),'reports':reports,'retry_endpoint':'/api/v1/maintenance/storage'}
