"""Remove managed objects while retaining immutable evidence and source files."""
from .safety import DomainError, json_text
from .store import now


def resources(store, entries):
    if not isinstance(entries,list) or not entries or len(entries)>200 or any(not isinstance(e,dict) for e in entries):
        raise DomainError('invalid_request')
    if len({e.get('id') for e in entries})!=len(entries):raise DomainError('invalid_request')
    chosen=[store.resource(e.get('id','')) for e in entries]
    for r,e in zip(chosen,entries):store.check(r,e)
    from .storage_ownership import plan
    from .storage_delete import enqueue
    ownership=plan(store,'resource',[r['id'] for r in chosen])
    for r in chosen:
        store.invalidate(r['id'])
        for group in store.rows('SELECT group_id FROM group_members WHERE resource_id=?',(r['id'],)):
            store.db.execute('UPDATE groups SET revision=revision+1 WHERE id=?',(group['group_id'],))
        for kb in store.rows('SELECT kb_id FROM kb_members WHERE resource_id=?',(r['id'],)):
            store.db.execute('UPDATE knowledge_bases SET revision=revision+1,member_revision=member_revision+1 WHERE id=?',(kb['kb_id'],))
        store.db.execute('DELETE FROM group_members WHERE resource_id=?',(r['id'],))
        store.db.execute('DELETE FROM kb_members WHERE resource_id=?',(r['id'],))
        store.db.execute("UPDATE resources SET state='deleted',revision=revision+1,updated_at=? WHERE id=?",(now(),r['id']))
        for idea in store.ideas():
            if r['id'] in idea['resource_ids']:
                store.db.execute('UPDATE proposal_ideas SET resource_ids=?,revision=revision+1,updated_at=? WHERE id=?',(json_text([i for i in idea['resource_ids'] if i!=r['id']]),now(),idea['id']))
        store.event('resource',r['id'],r['revision']+1)
    enqueue(store,ownership)
    return {'deleted':[r['id'] for r in chosen],'shared_evidence_preserved':True,'exclusive_file_deletion_queued':True}


def idea(store,id,body):
    value=store.idea(id);store.check(value,body)
    store.db.execute('DELETE FROM proposal_ideas WHERE id=?',(id,))
    store.event('proposal_idea',id,value['revision']+1)
    return {'id':id,'state':'deleted'}


def group(store,id,body):
    value=next((g for g in store.groups() if g['id']==id),None)
    if not value:raise DomainError('group_not_found',404)
    store.check(value,body)
    store.db.execute('DELETE FROM group_members WHERE group_id=?',(id,))
    store.db.execute('DELETE FROM groups WHERE id=?',(id,))
    store.event('group',id,value['revision']+1)
    return {'id':id,'state':'deleted','resources_preserved':True}


def clear_deleted_content(store,body):
    """Finish an explicitly requested empty-instance reset through the writer.

    Public entity deletion must happen first. Freeze exact local files before
    changing records; the usual retry queue handles files held open by Office.
    Connection settings, runtime, models and other projects are never candidates.
    """
    from .safety import contained
    from .layout import app_dir
    from .storage_ownership import walk_files
    if body.get('confirm')!='clear_deleted_content':raise DomainError('reset_confirmation_required',409)
    for table in ['jobs','knowledge_bases','groups','proposal_ideas']:
        if store.one('SELECT 1 FROM '+table+' LIMIT 1'):raise DomainError('reset_requires_empty_workspace',409)
    if store.resources():raise DomainError('reset_requires_empty_workspace',409)
    roots=[store.root,contained(store.project,'outputs',False),contained(store.project,'workspace/knowledge',False)]
    roots.extend(store.state/name for name in ['versions','exports','jobs','cache','text','figures','knowledge-index','knowledge-source-cache','metadata-sources'])
    files=set();directories=set()
    program=app_dir(store.project)
    if store.root==store.state or store.root in store.state.parents:raise DomainError('reset_scope_invalid',409)
    for root in roots:
        root=contained(store.project,root,False)
        if root==store.project or program!=store.project and (root==program or program in root.parents or root in program.parents):raise DomainError('reset_scope_invalid',409)
        files.update(walk_files(root,directories))
    directories.difference_update(roots)
    for name in ['knowledge-vector-cache.sqlite','knowledge-vector-cache.sqlite-wal','knowledge-vector-cache.sqlite-shm','output-directories.json','retention-status.json']:
        files.update(walk_files(contained(store.project,store.state/name,False)))
    ownership={'exclusive_files':[{'path':p.relative_to(store.project).as_posix(),'bytes':p.stat().st_size} for p in sorted(files)],
               'directories':[p.relative_to(store.project).as_posix() for p in sorted(directories)],'resources_only':True}
    # Foreign-key order matters, including residual soft-deleted resources.
    for table in ['kb_chunks','group_members','kb_members','annotations','relations','nodes','chunks_fts','chunks','versions','resources','paper_records']:
        store.db.execute('DELETE FROM '+table)
    for row in store.rows('SELECT key FROM settings'):
        if row['key'].startswith(('kb_','pdf_annotations_synced:','storage_delete:','research_','proposal_')):
            store.db.execute('DELETE FROM settings WHERE key=?',(row['key'],))
    store.db.execute('DELETE FROM operations WHERE id<>?',(body['operation_id'],))
    store.db.execute('DELETE FROM events')
    store.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('ui_navigation',json_text({'route':'library'})))
    store.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('storage_delete:reset:'+body['operation_id'],json_text(ownership)))
    for kind in ['resource','job','knowledge_base','group','relation','navigation']:store.event(kind,'reset',1)
    store.zip_cache.clear()
    return {'state':'cleared','file_cleanup_queued':True,'queued_files':len(files),'connection_and_preferences_preserved':True}
