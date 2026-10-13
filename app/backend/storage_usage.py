"""Metadata-only file accounting. Hardlinks share one physical allocation."""
import os,ctypes,sqlite3
from contextlib import closing
from pathlib import Path
from .safety import contained,DomainError

def allocated(path,info):
    if os.name=='nt':
        kernel=ctypes.windll.kernel32
        # GetCompressedFileSize returns logical length for ordinary files.
        # StandardInfo accounts for their allocated clusters/resident streams.
        if getattr(info,'st_file_attributes',0)&(0x800|0x200):
            high=ctypes.c_ulong();api=kernel.GetCompressedFileSizeW
            api.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_ulong)];api.restype=ctypes.c_ulong
            kernel.SetLastError(0);low=api(str(path),ctypes.byref(high))
            if low==0xffffffff and kernel.GetLastError():raise OSError('allocation unavailable')
            return (high.value<<32)|low
        class Standard(ctypes.Structure):
            _fields_=[('allocation',ctypes.c_longlong),('length',ctypes.c_longlong),('links',ctypes.c_ulong),('pending',ctypes.c_ubyte),('directory',ctypes.c_ubyte)]
        create=kernel.CreateFileW;create.argtypes=[ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p];create.restype=ctypes.c_void_p
        handle=create(str(path),0x80,7,None,3,0x200000,None)
        if handle==ctypes.c_void_p(-1).value:raise OSError('allocation unavailable')
        query=kernel.GetFileInformationByHandleEx;query.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_ulong];query.restype=ctypes.c_int
        close=kernel.CloseHandle;close.argtypes=[ctypes.c_void_p]
        try:
            value=Standard()
            if not query(handle,1,ctypes.byref(value),ctypes.sizeof(value)):raise OSError('allocation unavailable')
            return value.allocation
        finally:close(handle)
    return info.st_blocks*512

def usage(store):
    scopes=[('sources',store.root),('versions',store.state/'versions'),('derived',store.state/'knowledge-index'),('derived',store.state/'knowledge-source-cache'),('derived',store.state/'cache'),('derived',store.state/'text'),('derived',store.state/'figures'),('task_state',store.state/'jobs'),('published',store.state/'exports'),('published',contained(store.project,'workspace',False)),('outputs',contained(store.project,'outputs',False))]
    paths=set();physical=set();errors=[];groups={}
    def add(kind,path):
        if path in paths:return
        paths.add(path)
        try:
            info=path.stat(follow_symlinks=False)
            if path.is_symlink() or getattr(info,'st_file_attributes',0)&0x400:return
            key=(info.st_dev,info.st_ino);size=allocated(path,info);shared=key in physical;physical.add(key)
            group=groups.setdefault(kind,{'logical_bytes':0,'allocated_unique_bytes':0,'shared_allocated_bytes':0,'files':0})
            group['logical_bytes']+=info.st_size;group['allocated_unique_bytes']+=0 if shared else size;group['shared_allocated_bytes']+=size if shared else 0;group['files']+=1
        except OSError as e:errors.append({'category':kind,'error':type(e).__name__})
    def walk(kind,folder):
        if not folder.exists() or folder.is_symlink() or getattr(folder.stat(follow_symlinks=False),'st_file_attributes',0)&0x400:return
        for path in folder.iterdir():
            if path.is_dir():walk(kind,path)
            elif path.is_file():add(kind,path)
    for kind,folder in scopes:walk(kind,folder)
    for path in store.state.iterdir():
        if path.is_file():add('database' if path.name.startswith(('library.sqlite','knowledge-vector-cache.sqlite')) else 'metadata',path)
        elif path.name not in {'versions','knowledge-index','knowledge-source-cache','cache','text','figures','jobs','exports'}:walk('metadata',path)
    return {'categories':groups,'logical_bytes':sum(g['logical_bytes'] for g in groups.values()),'allocated_unique_bytes':sum(g['allocated_unique_bytes'] for g in groups.values()),'hardlinks_deduplicated':True,'allocation_method':'FileStandardInfo + compressed/sparse size' if os.name=='nt' else 'st_blocks','errors':errors,'complete':not errors,'warning':'File stream allocation only; filesystem metadata and software dependencies are excluded. Active database and WAL are never removed.'}

def compact_vectors(store):
    if store.one("SELECT id FROM jobs WHERE status IN ('queued','running')"):return {'compacted':False,'reason':'active_jobs'}
    path=store.state/'knowledge-vector-cache.sqlite'
    if not path.exists():return {'compacted':False,'reason':'no_cache'}
    with closing(sqlite3.connect(path)) as db:
        size=db.execute('PRAGMA page_size').fetchone()[0];pages=db.execute('PRAGMA page_count').fetchone()[0];free=db.execute('PRAGMA freelist_count').fetchone()[0]
        if free*size<8*1024*1024 or free/max(1,pages)<.25:return {'compacted':False,'reason':'below_threshold','free_bytes':free*size}
        db.execute('VACUUM')
    return {'compacted':True,'free_bytes_before':free*size}
