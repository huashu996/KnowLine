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
