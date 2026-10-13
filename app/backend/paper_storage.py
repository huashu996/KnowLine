"""One physical file for equal managed PDFs; readonly links protect evidence."""
import os,stat,uuid
from .safety import digest,DomainError,contained
def link_source(store,source,snapshot):
 source=contained(store.root,source);snapshot=contained(store.state/'versions',snapshot)
 if os.path.samefile(source,snapshot):return 0
 if digest(source)!=digest(snapshot):raise DomainError('hash_conflict',409)
 size=source.stat().st_size;temporary=source.with_name('.kw-share-'+str(uuid.uuid4())+'.pdf')
 try:
  os.link(snapshot,temporary)
  os.chmod(source,stat.S_IREAD|stat.S_IWRITE)
  os.replace(temporary,source)
 finally:
  if temporary.exists():
   os.chmod(temporary,stat.S_IREAD|stat.S_IWRITE);temporary.unlink()
  os.chmod(snapshot,stat.S_IREAD)
 return size
def replace_current(store,candidate,path,resource):
 old=store.snapshot(resource)
 try:
  os.chmod(path,stat.S_IREAD|stat.S_IWRITE)
  os.replace(candidate,path)
 finally:os.chmod(old,stat.S_IREAD)
def coalesce(store):
 if store.one("SELECT id FROM jobs WHERE status IN ('running','queued')"):raise DomainError('active_tasks_preserved',409)
 shared=[];released=0
 for resource in store.resources():
  if resource['type']!='paper' or resource['state']!='ready':continue
  source=store.current_path(resource);snapshot=store.snapshot(resource)
  if source.resolve().is_relative_to(store.root.resolve()):
   saved=link_source(store,source,snapshot)
   if saved:shared.append(resource['id']);released+=saved
 return {'physical_bytes_released':released,'shared_resource_count':len(shared),'resource_ids_versions_and_paths_unchanged':True,'strategy':'readonly_ntfs_hardlinks'}
def unlink_file(store,path):
 anchors=[]
 if path.suffix.lower()=='.pdf':
  candidates=[row['snapshot_path'] for row in store.rows('SELECT DISTINCT snapshot_path FROM versions')]+[r['path'] for r in store.resources()]
  for value in candidates:
   other=contained(store.project,value,False)
   if other!=path and other.is_file() and os.path.samefile(path,other):anchors.append(other)
 os.chmod(path,stat.S_IREAD|stat.S_IWRITE);path.unlink()
 for other in anchors:
  if other.exists():os.chmod(other,stat.S_IREAD)
