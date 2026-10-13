"""Active bounded retention used by the single writer.
Only exact generated intermediate/cache files are eligible; no recursive removal.
"""
import json,logging,re,sqlite3
from contextlib import closing
from pathlib import Path
from .safety import contained,DomainError,atomic_json
from .storage import POLICY,BoundedLog,trim,log_summary
LIMITS={'source_cache_bytes':64*1024*1024,'discovery_cache_bytes':16*1024*1024,'failed_source_bytes':64*1024*1024,
        'failed_detailed_jobs':20,'vector_cache_rows':4096,'operation_full_results':128,'event_rows':2048,'server_log_bytes':1048576}
class CappedFileHandler(logging.Handler):
    def __init__(self,filename,limit=1048576):
        super().__init__();self.log=BoundedLog(filename,limit,reset=False)
    def emit(self,record):
        try:self.log.write(self.format(record)+'\n')
        except Exception:self.handleError(record)
def logging_config(state):
    return {'version':1,'disable_existing_loggers':False,'formatters':{'plain':{'format':'%(asctime)s %(levelname)s %(message)s'}},
        'handlers':{'bounded':{'class':'backend.retention.CappedFileHandler','filename':str(Path(state)/'server.log'),'limit':LIMITS['server_log_bytes'],'formatter':'plain'}},
        'loggers':{name:{'handlers':['bounded'],'level':'WARNING' if name.endswith('access') else 'INFO','propagate':False} for name in ['uvicorn','uvicorn.error','uvicorn.access']}}
def budgets(store):
    return {**LIMITS,**store.config.get('storage_budgets',{})}

def validate_budgets(value):
    ranges={'source_cache_bytes':(1048576,536870912),'discovery_cache_bytes':(1048576,134217728),'vector_cache_rows':(128,32768)}
    if not isinstance(value,dict) or set(value)-set(ranges):raise DomainError('invalid_setting')
    for key,v in value.items():
        if isinstance(v,bool) or not isinstance(v,int) or not ranges[key][0]<=v<=ranges[key][1]:raise DomainError('invalid_setting')
    return value

def bound_vectors(conn,store=None):
    limit=budgets(store)['vector_cache_rows'] if store else LIMITS['vector_cache_rows']
    before=conn.execute('SELECT count(*) FROM vectors').fetchone()[0]
    conn.execute('DELETE FROM vectors WHERE rowid NOT IN (SELECT rowid FROM vectors ORDER BY rowid DESC LIMIT ?)',(limit,))
    return max(0,before-limit)
def maintain(store,dry_run=False):
    limits=budgets(store)
    jobs=[store.job(r['id']) for r in store.rows('SELECT id FROM jobs ORDER BY updated_at DESC')]
    active=[j for j in jobs if j['status'] in {'queued','running'}]
    protected={contained(store.project,a['path'],False) for j in jobs for a in (j.get('result') or {}).get('artifacts',[])}
    hashes={r['sha256'] for j in active for r in j['context'].get('resources',[])}
    removed=[];released=0;trimmed=0;failures=[];failed_count=0;failed_size=0
    def remove(file,scope):
        nonlocal released
        try:
            if file.is_symlink() or file.exists() and getattr(file.stat(follow_symlinks=False),'st_file_attributes',0)&0x400:raise DomainError('unsafe_link')
            file=contained(scope,file,False)
            if not file.exists() or file in protected:return
            if not file.is_file():raise DomainError('retention_requires_exact_file')
            size=file.stat().st_size
            if not dry_run:file.unlink()
            released+=size;removed.append(file.relative_to(store.project).as_posix())
        except (OSError,DomainError) as exc:failures.append({'path':str(file),'error':getattr(exc,'code',type(exc).__name__)})
    for j in jobs:
        if j in active:continue
        scope=contained(store.project,store.state/'jobs'/j['id'],False)
        failed=j['status'] in {'failed','interrupted','partial'}
        if failed:failed_count+=1
        log=scope/'codex-events.jsonl';summary=log_summary(log)
        if summary and not dry_run:atomic_json(scope/'execution-summary.json',summary)
        cap=POLICY['failed_event_log_bytes'] if failed and failed_count<=limits['failed_detailed_jobs'] else POLICY['successful_event_log_bytes']
        for file,limit in [(log,cap),(scope/'codex-stderr.log',POLICY['stderr_bytes'])]:
            if file not in protected and not dry_run:trimmed+=trim(file,limit)
        for source in j['context'].get('knowledge_build',{}).get('prepared_sources',[]):
            file=contained(store.project,source['path'],False)
            if file.parent!=scope or not re.fullmatch(r'r_[A-Za-z0-9-]+-source\.json',file.name):continue
            size=file.stat().st_size if file.exists() else 0
            if j['status']=='completed' or failed and (failed_count>limits['failed_detailed_jobs'] or failed_size+size>limits['failed_source_bytes']):remove(file,scope)
            else:failed_size+=size
    for folder,pattern,limit in [('knowledge-source-cache','*.json',limits['source_cache_bytes']),('cache','discovery-*.json',limits['discovery_cache_bytes'])]:
        scope=store.state/folder;used=0
        for file in sorted(scope.glob(pattern),key=lambda p:p.stat().st_mtime,reverse=True):
            if folder=='knowledge-source-cache' and not re.fullmatch(r'[0-9a-f]{64}\.json',file.name):continue
            if file.stem in hashes or used+file.stat().st_size<=limit:used+=file.stat().st_size
            else:
                remove(file,scope)
                if folder=='knowledge-source-cache':remove(file.with_suffix('.sha256'),scope)
    # Rejected semantic indexes have no published owner. Current/history indexes
    # and registered artifacts stay protected; a live job defers this cleanup.
    indexes=set()
    for row in store.rows("SELECT value FROM settings WHERE key LIKE 'kb_cards:%' OR key LIKE 'kb_cards_history:%'"):
        info=json.loads(row['value']).get('retrieval') or {}
        if info.get('path'):indexes.add(contained(store.project,info['path'],False))
    if not active:
        scope=store.state/'knowledge-index'
        for file in scope.glob('kb_*/*.sqlite'):
            if file in indexes or not re.fullmatch(r'b_[A-Za-z0-9-]+-[0-9a-f]{8}\.sqlite',file.name):continue
            remove(file,scope);remove(file.with_suffix('.manifest.json'),scope)
    vector_rows=0
    vector_path=store.state/'knowledge-vector-cache.sqlite'
    if not active and vector_path.exists():
        with closing(sqlite3.connect(f'file:{vector_path.as_posix()}?mode='+('ro' if dry_run else 'rw'),uri=True)) as conn:
            if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='vectors'").fetchone():
                vector_rows=max(0,conn.execute('SELECT count(*) FROM vectors').fetchone()[0]-limits['vector_cache_rows'])
                if not dry_run:bound_vectors(conn,store);conn.commit()
    # Compact large operation responses to tiny idempotency markers; don't erase
    # operation identities. Expired response replay will explicitly be refused.
    if not dry_run:maintain_records(store)
    report={'limits':limits,'preview':dry_run,'removed_files':removed,'released_bytes':released,'vector_rows_to_remove':vector_rows if dry_run else 0,'vector_rows_removed':0 if dry_run else vector_rows,'trimmed_log_bytes':trimmed,'errors':failures,
            'active_jobs_preserved':[j['id'] for j in active],'registered_outputs_preserved':True,'source_files_and_indexes_untouched':True}
    if not dry_run:atomic_json(store.state/'retention-status.json',report)
    return report

def maintain_records(store):
    store.db.execute("UPDATE operations SET payload=NULL,result=? WHERE state='committed' AND payload IS NOT NULL AND id NOT IN (SELECT id FROM operations WHERE state='committed' ORDER BY created_at DESC,rowid DESC LIMIT ?)",(json.dumps({'operation_result_expired':True}),LIMITS['operation_full_results']))
    store.db.execute('DELETE FROM events WHERE sequence NOT IN (SELECT sequence FROM events ORDER BY sequence DESC LIMIT ?)',(LIMITS['event_rows'],))
