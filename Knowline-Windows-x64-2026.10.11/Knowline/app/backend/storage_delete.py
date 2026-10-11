"""Exact-file deletion executor, currently not attached to any public API.

Read-only proofs cover isolated shared PDFs and all 59/3 current objects.
No recursive removal. Only files from a previously constructed ownership plan
inside the managed data tree are eligible. Surviving references are rechecked.
"""
import json
from .safety import contained,DomainError
from .storage_ownership import plan,walk_files

def execute(store,ownership):
    guard=plan(store,'resource',[])
    protected=[contained(store.project,p,False) for p in guard['protected_paths']]
    removed=[];retained=[];failures=[];released=0
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
    return {'state':'pending' if failures else 'shared_references_retained' if retained else 'complete','released_bytes':released,'removed_files':removed,'retained_shared_paths':retained,'errors':failures}

def enqueue(store,value):
    files=value['exclusive_files']+[{'path':p,'bytes':0} for p in value['retained_shared_paths']]
    key='storage_delete:'+value['kind']+':'+','.join(value['ids'])
    store.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps({'exclusive_files':files},ensure_ascii=False)))

def drain(store):
    reports=[]
    for row in store.rows("SELECT key,value FROM settings WHERE key LIKE 'storage_delete:%'"):
        ownership=json.loads(row['value']);report=execute(store,ownership);reports.append(report)
        pending=set(report['retained_shared_paths']+[v['path'] for v in report['errors']])
        if pending:
            ownership['exclusive_files']=[v for v in ownership['exclusive_files'] if v['path'] in pending]
            store.db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(ownership,ensure_ascii=False),row['key']))
        else:store.db.execute('DELETE FROM settings WHERE key=?',(row['key'],))
    store.db.commit()
    return {'state':'pending' if any(r['errors'] for r in reports) else 'shared_references_retained' if any(r['retained_shared_paths'] for r in reports) else 'complete',
            'released_bytes':sum(r['released_bytes'] for r in reports),'reports':reports,'retry_endpoint':'/api/v1/maintenance/storage'}
