"""Minimal persistent storage with protected outputs and bounded disposable state.

All mutation runs inside the public service's single writer. Source/version files,
registered artifacts, current indexes and active task scopes are never swept.
"""
import json,os,shutil,stat
from collections import deque
from pathlib import Path
from .safety import atomic_json,contained,digest,DomainError

POLICY={'full_data_backups':False,'successful_event_log_bytes':65536,'failed_event_log_bytes':262144,
        'active_event_log_bytes':1048576,'stderr_bytes':65536,'failed_detailed_logs':20,
        'source_cache_bytes':64*1024*1024,'vector_cache_rows':4096,
        'retry_archives':0,'previous_result_manifests':1,'zip_memory_entries':24,'evidence_page_entries':2048}

class BoundedLog:
    """Overwrite the oldest diagnostic bytes, never resource or output files."""
    def __init__(self,path,limit,reset=True):
        self.path=Path(path);self.limit=limit;self.path.parent.mkdir(parents=True,exist_ok=True)
        if reset:self.path.write_bytes(b'')
    def write(self,text):
        data=text.encode('utf-8') if isinstance(text,str) else text
        with self.path.open('ab') as stream:stream.write(data[-self.limit:])
        if self.path.stat().st_size>self.limit:trim(self.path,self.limit)

def checkpoint(store):
    from .store import now
    path=store.state/'storage-checkpoint.json'
    value={'mode':'metadata_only','created_at':now(),'event_sequence':store.sequence(),'policy':POLICY,
           'resources':[{'id':r['id'],'version_id':r['version_id'],'sha256':r['sha256']} for r in store.resources()],
           'knowledge_bases':[{'id':k['id'],'revision':k['revision'],'build_id':k['build_id']} for k in store.kbs()],
           'warning':'仅必要状态记录，不复制数据库、原文、版本或成果；不是整库恢复备份。'}
    atomic_json(path,value)
    return {'mode':'metadata_only','path':path.relative_to(store.project).as_posix(),'bytes':path.stat().st_size,
            'full_data_copies':0,'overwrites_single_checkpoint':True,'warning':value['warning']}

def compact_event(event):
    result={k:v for k,v in event.items() if k!='item'}
    item=event.get('item')
    if isinstance(item,dict):
        result['item']={k:(v[:1800] if isinstance(v,str) else v) for k,v in item.items() if k in {'id','type','status','exit_code','command','text','aggregated_output'}}
    return result

def prepare_retry(store,job,manifest):
    """One prior manifest and one small attempt summary, never PDF/output copies."""
    if not manifest.exists():return
    from .store import now
    protected={contained(store.project,a['path'],False) for row in store.rows('SELECT id FROM jobs') for a in (store.job(row['id']).get('result') or {}).get('artifacts',[])}
    previous=manifest.parent/'result.previous.json'
    if manifest in protected or previous in protected:raise DomainError('retry_artifact_in_use',409)
    if manifest.stat().st_size>32*1024*1024:raise DomainError('file_too_large')
    atomic_json(store.state/'jobs'/job['id']/'last-attempt.json',{'at':now(),'previous_manifest_sha256':digest(manifest),'copies_of_source_files':0})
    os.replace(manifest,previous)

def trim(path,limit):
    if not path.is_file() or path.stat().st_size<=limit:return 0
    before=path.stat().st_size
    with path.open('rb') as stream:
        stream.seek(max(0,before-limit));data=stream.read(limit)
    if b'\n' in data:data=data.split(b'\n',1)[1]
    path.write_bytes(data)
    return before-len(data)

def log_summary(path):
    if not path.is_file():return {}
    counts={};usage={};commands=0;first=None;last=None
    with path.open(encoding='utf-8',errors='replace') as stream:
        for line in stream:
            try:event=json.loads(line)
            except ValueError:continue
            kind=event.get('type','unknown');counts[kind]=counts.get(kind,0)+1
            if kind=='item.completed' and event.get('item',{}).get('type')=='command_execution':commands+=1
            if event.get('usage'):usage=event['usage']
            stamp=event.get('received_at')
            if stamp:first=first or stamp;last=stamp
    return {'events':counts,'completed_commands':commands,'usage':usage,'first_received_at':first,'last_received_at':last,
            'timestamps_available':bool(first),'full_tool_outputs_not_retained':True}

def compact(store):
    from .store import now
    jobs=[store.job(r['id']) for r in store.rows('SELECT id FROM jobs ORDER BY updated_at DESC')]
    active=[j for j in jobs if j['status'] in {'queued','running'}]
    protected=set()
    for r in store.resources():
        protected.add(contained(store.project,r['path'],False))
        for v in r['versions']:protected.add(contained(store.project,v['snapshot_path'],False))
    for job in jobs:
        for a in (job.get('result') or {}).get('artifacts',[]):protected.add(contained(store.project,a['path'],False))
    for job in active:
        protected.add(contained(store.project,job['context']['output_dir'],False))
        protected.add(store.state/'jobs'/job['id'])
    removed=[];bytes_removed=0;trimmed=0
    def remove(path):
        nonlocal bytes_removed
        path=Path(path)
        if not path.exists():return
        resolved=contained(store.project,path)
        if any(resolved==p or resolved in p.parents or p in resolved.parents for p in protected):return
        entries=[resolved]
        if resolved.is_dir():entries.extend(resolved.rglob('*'))
        if any(p.is_symlink() or getattr(p.stat(follow_symlinks=False),'st_file_attributes',0)&0x400 for p in entries):raise DomainError('storage_link_rejected')
        size=sum(p.stat().st_size for p in entries if p.is_file())
        if resolved.is_dir():shutil.rmtree(resolved)
        else:resolved.unlink()
        bytes_removed+=size;removed.append(resolved.relative_to(store.project).as_posix())
    failed_detail=0
    for job in jobs:
        if job in active:continue
        folder=store.state/'jobs'/job['id'];log=folder/'codex-events.jsonl'
        summary=log_summary(log)
        if summary:atomic_json(folder/'execution-summary.json',summary)
        failed=job['status'] in {'failed','interrupted','partial'}
        if failed:failed_detail+=1
        trimmed+=trim(log,POLICY['failed_event_log_bytes'] if failed and failed_detail<=POLICY['failed_detailed_logs'] else POLICY['successful_event_log_bytes'])
        trimmed+=trim(folder/'codex-stderr.log',POLICY['stderr_bytes'])
        for attempt in folder.glob('attempt-*'):remove(attempt)
        output=contained(store.project,job['context']['output_dir'],False)
        if output.exists():
            for attempt in output.glob('attempt-*'):remove(attempt)
            previous=sorted(output.glob('result.previous*'),key=lambda p:p.stat().st_mtime,reverse=True)
            for p in previous[1:]:remove(p)
            for p in output.glob('*.tmp'):remove(p)
    # Old unpublished index attempts can be regenerated; all current indexes stay.
    keep_indexes=set()
    for row in store.rows("SELECT value FROM settings WHERE key LIKE 'kb_cards:%' OR key LIKE 'kb_cards_history:%'"):
        value=json.loads(row['value']);info=value.get('retrieval') or {}
        if info.get('path'):keep_indexes.add(contained(store.project,info['path'],False))
    if not active:
        for path in (store.state/'knowledge-index').glob('*/*.sqlite'):
            if path not in keep_indexes:remove(path);remove(path.with_suffix('.manifest.json'))
    # A single parsed text cache per immutable source, protected during active jobs.
    active_hashes={r['sha256'] for j in active for r in j['context'].get('resources',[])}
    cache=store.state/'knowledge-source-cache';files=sorted(cache.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True);used=0
    for path in files:
        size=path.stat().st_size
        if used+size<=POLICY['source_cache_bytes'] or path.stem in active_hashes:used+=size
        else:remove(path);remove(path.with_suffix('.sha256'))
    for name in ['desktop-server.log','desktop-server-codex.log','desktop-server-codex-error.log']:
        path=store.state/name
        # Windows open service handles may prohibit trimming. Retry next startup.
        try:trimmed+=trim(path,1024*1024)
        except PermissionError:pass
    report={'at':now(),'policy':POLICY,'removed':removed,'removed_bytes':bytes_removed,'trimmed_log_bytes':trimmed,
            'active_jobs_protected':[j['id'] for j in active],'registered_artifacts_protected':True,
            'source_and_versions_untouched':True,'full_data_backups_created':0}
    atomic_json(store.state/'storage-maintenance.json',report)
    return report
