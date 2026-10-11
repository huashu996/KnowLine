"""Directly readable project catalog; model execution belongs to the host agent."""
import json
import unicodedata
from pathlib import Path
from .safety import DomainError, atomic_json, contained, digest
from .layout import relative, project_root
from .paper_bibliography import rows as paper_records


def normalized(value):
    return ''.join(unicodedata.normalize('NFKC',str(value)).casefold().split())


def resolve(entries, name, kind='entity'):
    matches=[entry for entry in entries if name==entry['id'] or
             normalized(name) in {normalized(entry.get('name','')),*(normalized(a) for a in entry.get('aliases',[]))}]
    if not matches:
        raise DomainError(kind+'_not_found',404,name=name)
    if len(matches)!=1:
        raise DomainError('name_ambiguous',409,kind=kind,name=name,
                          matches=[{'id':entry['id'],'name':entry.get('name','')} for entry in matches])
    return matches[0]


def catalog(store):
    resources=store.resources()
    domains=[]
    for group in store.groups():
        members=[r for r in resources if r['id'] in group['resource_ids']]
        domains.append({**group,'aliases':store.config.get('domain_aliases',{}).get(group['id'],[]),
            'counts':{kind:sum(r['type']==kind for r in members) for kind in ['paper','code','link']}})
    return {'schema_version':1,'project_name':store.config.get('workspace_name','知序个人空间'),
        'event_sequence':store.sequence(),'resource_root':store.config['resource_root'],
        'resources':resources,'domains':domains,'knowledge_bases':[
            {**kb,'snapshot_path':relative(store.project,'workspace/knowledge/'+kb['id']+'.json')} for kb in store.kbs()],
        'proposal_ideas':store.ideas(),
        'paper_records':paper_records(store),
        'jobs':[store.job(j['id']) for j in store.rows('SELECT id FROM jobs ORDER BY created_at DESC')],
        'relations':store.rows('SELECT * FROM relations'),
        'paths':{'incoming':relative(store.project,'incoming'),'outputs':relative(store.project,'outputs'),'reference_knowledge_base':
                 relative(store.project,'SLAM_RAG_Knowledge_Base') if contained(store.project,'SLAM_RAG_Knowledge_Base',False).is_dir() else None}}


def publish_view(store):
    folder=contained(store.project,'workspace',False);folder.mkdir(exist_ok=True)
    state=store.one("SELECT value FROM settings WHERE key='ui_navigation'")
    value=json.loads(state['value']) if state else {'route':'library'}
    path=folder/'view.json'
    if not path.exists() or json.loads(path.read_text('utf-8'))!=value:atomic_json(path,value)


def publish(store, changes=None):
    folder=contained(store.project,'workspace',False)
    folder.mkdir(exist_ok=True)
    data=catalog(store)
    knowledge=contained(store.project,'workspace/knowledge',False)
    knowledge.mkdir(exist_ok=True)
    previous=json.loads((folder/'catalog.json').read_text('utf-8')) if (folder/'catalog.json').exists() else {}
    prior={kb['id']:kb for kb in previous.get('knowledge_bases',[])}
    dirty={id for kind,id in (changes or []) if kind=='knowledge_base'}
    resource_ids={id for kind,id in (changes or []) if kind=='resource'}
    for kind,id in changes or []:
        if kind=='job':
            try:
                job=store.job(id);scope=job['context'].get('scope',{})
                if scope.get('kb_id'):dirty.add(scope['kb_id'])
            except DomainError:pass
    for kb in data['knowledge_bases']:
        target=knowledge/(kb['id']+'.json');old=prior.get(kb['id'],{})
        if changes is not None and kb['id'] not in dirty and not resource_ids.intersection(kb['resource_ids']) and target.exists() and old.get('snapshot_sha256'):
            kb.update(snapshot_sha256=old['snapshot_sha256'],snapshot_event_sequence=old['snapshot_event_sequence'])
            continue
        nodes=store.rows('SELECT * FROM nodes WHERE kb_id=?',(kb['id'],))
        chunks=store.rows('SELECT c.* FROM chunks c JOIN kb_chunks kc ON kc.chunk_id=c.id WHERE kc.kb_id=?',(kb['id'],)) if kb['index_state']=='ready' else []
        for node in nodes:
            node['evidence']=json.loads(node['evidence']) if node['evidence'] else []
        for chunk in chunks:
            chunk['locator']=json.loads(chunk['locator']) if chunk['locator'] else {}
        from .knowledge import cards
        value={**kb,'cards':cards(store,kb),'schema_version':1,'event_sequence':data['event_sequence'],'nodes':nodes,'chunks':chunks}
        before=json.loads(target.read_text('utf-8')) if target.exists() else None
        if before and {k:v for k,v in before.items() if k!='event_sequence'}=={k:v for k,v in value.items() if k!='event_sequence'}:
            value=before
        else:atomic_json(target,value)
        kb.update(snapshot_sha256=digest(target),snapshot_event_sequence=value['event_sequence'])
    atomic_json(folder/'catalog.json',data)
    publish_view(store)
    return data


def verified_snapshot(store,kb):
    """Validate the published per-KB sequence/hash and current content boundary.

    UI events advance the event stream, never the knowledge publication boundary.
    A partially published transaction fails closed until startup export repairs it.
    """
    data=read(store.project)
    latest=store.one("SELECT max(sequence) AS value FROM events WHERE kind NOT IN ('view_state','navigation')")['value'] or 0
    if latest>data['event_sequence']:raise DomainError('knowledge_snapshot_stale',409)
    entry=next((k for k in data['knowledge_bases'] if k['id']==kb['id']),None)
    if not entry:raise DomainError('knowledge_snapshot_stale',409)
    target=contained(store.project,entry['snapshot_path'])
    value=json.loads(target.read_text('utf-8'))
    sequence=entry.get('snapshot_event_sequence',data['event_sequence'])
    if value.get('event_sequence')!=sequence:raise DomainError('knowledge_snapshot_stale',409)
    if entry.get('snapshot_sha256') and digest(target)!=entry['snapshot_sha256']:raise DomainError('snapshot_corrupt',409)
    for key in ['id','revision','member_revision','build_id','index_state','resource_ids']:
        if value.get(key)!=kb.get(key):raise DomainError('knowledge_snapshot_stale',409)
    return value


def read(project):
    path=contained(project_root(project),'workspace/catalog.json',False)
    if not path.is_file():
        raise DomainError('project_catalog_missing',404)
    return json.loads(path.read_text('utf-8'))
