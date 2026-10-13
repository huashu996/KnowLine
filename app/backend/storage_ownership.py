"""Read-only ownership plan. Never removes or modifies a file or database row."""
import json
from pathlib import Path
from .safety import contained,DomainError

def walk_files(root,directories=None):
    if root.is_symlink() or root.exists() and getattr(root.stat(follow_symlinks=False),'st_file_attributes',0)&0x400:raise DomainError('unsafe_link')
    if not root.exists():return []
    if root.is_file():return [root]
    if directories is not None:directories.add(root)
    return [p for child in root.iterdir() for p in walk_files(child,directories)]

def plan(store,kind,ids,*,resources_only=False):
    resources_only=resources_only or kind=='job'
    ids=set(ids);jobs=[store.job(r['id']) for r in store.rows('SELECT id FROM jobs')]
    owned_jobs={j['id'] for j in jobs if kind=='job' and j['id'] in ids or kind=='knowledge_base' and j['context']['scope'].get('kb_id') in ids}
    candidates=set();directories=set();protected=set();versions=set()
    def refs(value):
        if isinstance(value,dict):
            for k,v in value.items():
                if k=='version_id' and isinstance(v,str):versions.add(v)
                if k in {'path','snapshot_path','output_dir','annotations_path','manifest_path','context_path','document','source_document','paper_graph_artifact','report_path','analysis_path','retrieval_path','preview_path'} and isinstance(v,str):
                    try:protected.add(contained(store.project,v,False))
                    except DomainError:pass
                refs(v)
        elif isinstance(value,list):
            for v in value:refs(v)
    def own(path):
        path=contained(store.project,path,False)
        allowed=[store.root,store.state,contained(store.project,'outputs',False),contained(store.project,'workspace',False)/'knowledge']
        if not any(p in path.parents for p in allowed):raise DomainError('storage_delete_outside_ownership')
        candidates.update(walk_files(path,directories))
    for r in store.resources():
        if kind=='resource' and r['id'] in ids:
            own(r['path'])
            for v in r['versions']:own(v['snapshot_path']);own(Path(v['snapshot_path']).with_suffix('.manifest.json'))
        else:
            protected.add(contained(store.project,r['path'],False))
            for v in r['versions']:protected.add(contained(store.project,v['snapshot_path'],False))
    for j in jobs:
        if j['id'] in owned_jobs:
            output=contained(store.project,j['context']['output_dir'],False)
            state=contained(store.project,store.state/'jobs'/j['id'],False)
            if output.parent!=contained(store.project,'outputs',False) or state.parent!=store.state/'jobs':raise DomainError('storage_delete_outside_ownership')
            own(output);own(state)
        elif not resources_only:refs(j['context']);refs(j.get('result') or {})
    for row in store.rows("SELECT key,value FROM settings WHERE key LIKE 'kb_cards:%' OR key LIKE 'kb_cards_history:%'"):
        if resources_only:continue
        kb_id=row['key'].split(':')[1]
        if kind=='knowledge_base' and kb_id in ids:continue
        refs(json.loads(row['value']))
    for path in (store.state/'word').glob('*/config.json'):
        if resources_only:continue
        refs(json.loads(path.read_text('utf-8')))
    for vid in versions:
        v=store.one('SELECT snapshot_path FROM versions WHERE id=?',(vid,))
        if v:protected.add(contained(store.project,v['snapshot_path'],False))
    if kind=='knowledge_base':
        for id in ids:
            own(store.state/'knowledge-index'/id)
            own(contained(store.project,'workspace',False)/'knowledge'/(id+'.json'))
    exclusive=[];shared=[]
    for p in sorted(candidates):
        rel=p.relative_to(store.project).as_posix()
        if any(p==ref or ref in p.parents for ref in protected):shared.append(rel)
        else:exclusive.append({'path':rel,'bytes':p.stat().st_size})
    return {'kind':kind,'ids':sorted(ids),'owned_jobs':sorted(owned_jobs),'exclusive_files':exclusive,'directories':[p.relative_to(store.project).as_posix() for p in sorted(directories)],'protected_paths':[p.relative_to(store.project).as_posix() for p in protected],
            'retained_shared_paths':shared,'exclusive_bytes':sum(p['bytes'] for p in exclusive),'read_only':True}
