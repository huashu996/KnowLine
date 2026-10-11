"""Explicit offline single-writer path migration, preserving identities and artifact bytes."""
import json
import shutil
import sqlite3
from pathlib import Path
from .layout import project_root,relative,data_path,app_dir,identity
from .safety import atomic_json,digest,DomainError


PATH_KEYS={'path','snapshot_path','manifest_path','annotations_path','output_dir','paper_graph_artifact','document','source_document','context_path','report_path','analysis_path','retrieval_path'}


def remap(project,value,key=None):
    if isinstance(value,dict):
        result={k:remap(project,v,k) for k,v in value.items()}
        if isinstance(value.get('artifacts'),list):result['artifacts']=[{**a,'path':relative(project,a['path'])} for a in value['artifacts']]
        if isinstance(value.get('figure'),dict) and 'path' in value['figure']:result['figure']['path']=relative(project,value['figure']['path'])
        if isinstance(value.get('office_fragment'),dict) and 'path' in value['office_fragment']:result['office_fragment']['path']=relative(project,value['office_fragment']['path'])
        if isinstance(value.get('image'),dict) and 'path' in value['image']:result['image']['path']=relative(project,value['image']['path'])
        return result
    if isinstance(value,list):return [remap(project,v,key) for v in value]
    return relative(project,value) if key in PATH_KEYS and isinstance(value,str) else value


def run(project):
    import msvcrt
    project=project_root(project)
    marker=app_dir(project)/'project-layout.json'
    if not marker.exists():raise DomainError('layout_mapping_required')
    state=data_path(project,'.knowledge')
    with (state/'server.lock').open('a+b') as lock:
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise DomainError('project_service_running')
        db=sqlite3.connect(state/'library.sqlite');db.row_factory=sqlite3.Row
        file_backups={}
        def write_managed(path,value):
            file_backups.setdefault(path,path.read_bytes() if path.exists() else None)
            atomic_json(path,value)
        try:
            previous=db.execute("SELECT value FROM settings WHERE key='app_resource_layout_v2'").fetchone()
            if previous:return json.loads(previous[0])
            # User explicitly forbids backup copies. This is an in-place SQLite
            # transaction; only small managed JSON values are held in memory.
            identities=[dict(r) for r in db.execute('SELECT id,resource_id,sha256,snapshot_path FROM versions')]
            for version in identities:
                if digest(project/relative(project,version['snapshot_path']))!=version['sha256']:raise DomainError('snapshot_corrupt')
            db.execute('BEGIN IMMEDIATE')
            for table,column in [('resources','path'),('versions','snapshot_path')]:
                for row in db.execute(f'SELECT id,{column} FROM {table}').fetchall():db.execute(f'UPDATE {table} SET {column}=? WHERE id=?',(relative(project,row[column]),row['id']))
            for row in db.execute('SELECT id,context,result FROM jobs').fetchall():
                context=remap(project,json.loads(row['context']));result=remap(project,json.loads(row['result'])) if row['result'] else None
                db.execute('UPDATE jobs SET context=?,result=? WHERE id=?',(json.dumps(context,ensure_ascii=False),json.dumps(result,ensure_ascii=False) if result else None,row['id']))
            for row in db.execute("SELECT key,value FROM settings WHERE key LIKE 'kb_cards%' OR key LIKE 'kb_build_options:%'").fetchall():
                db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(remap(project,json.loads(row['value'])),ensure_ascii=False),row['key']))
            config=json.loads((state/'config.json').read_text('utf-8'))
            config['resource_root']=relative(project,config['resource_root']);config['code_roots']=[relative(project,p) for p in config.get('code_roots',[])]
            write_managed(state/'config.json',config)
            # Job scope files are managed state, not user-authored hashed output artifacts.
            for path in (state/'jobs').glob('*/*.json'):
                if path.name in {'context.json','result.json','result-template.json'}:write_managed(path,remap(project,json.loads(path.read_text('utf-8'))))
            for path in (state/'word').glob('*/config.json') if (state/'word').exists() else []:
                write_managed(path,remap(project,json.loads(path.read_text('utf-8'))))
            report={'schema_version':1,'resource_count':db.execute('SELECT count(*) FROM resources').fetchone()[0],'version_count':len(identities),'preserved_versions':[{'id':v['id'],'resource_id':v['resource_id'],'sha256':v['sha256']} for v in identities],'artifact_bytes_changed':False,'project_identity_path':str(project)}
            config['backup_retention']='disabled';config['project_id']=identity(project);write_managed(state/'config.json',config)
            db.execute("INSERT INTO settings VALUES('app_resource_layout_v2',?)",(json.dumps(report,ensure_ascii=False),));db.commit()
            atomic_json(state/'layout-migration.json',report)
        except Exception:
            db.rollback()
            for path,original in file_backups.items():
                if original is not None:path.write_bytes(original)
            raise
        finally:db.close()
    from .store import Store
    store=Store(project)
    if any(store.current_digest(r)!=r['sha256'] for r in store.resources() if r['state']=='ready'):raise DomainError('hash_conflict')
    store.export();store.db.close()
    return report
