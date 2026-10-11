"""Import picker bytes into immutable, searchable code resources; never execute them."""
import io
import zipfile
from pathlib import Path
from .safety import DomainError, SafeZip, contained, digest, exclusion, hash_bytes, json_text, member_name
from .store import now

SOURCE_SUFFIXES = {'.c','.cc','.cpp','.cxx','.h','.hh','.hpp','.hxx','.py','.pyi','.js','.jsx','.mjs','.cjs','.ts','.tsx','.java','.kt','.kts','.cs','.go','.rs','.rb','.php','.swift','.m','.mm','.scala','.sc','.vue','.svelte','.html','.htm','.css','.scss','.sass','.less','.sql','.sh','.bash','.zsh','.ps1','.bat','.cmd','.r','.jl','.lua','.pl','.pm','.f','.f90','.f95','.cu','.cuh','.v','.sv','.vhd','.vhdl','.proto','.cmake','.json','.yaml','.yml','.toml','.xml','.ini','.cfg','.conf','.md','.rst','.txt','.gradle','.properties','.tex'}
SOURCE_NAMES = {'cmakelists.txt','makefile','dockerfile','containerfile','license','readme','.gitignore','.gitattributes','.editorconfig'}

def source_file(name):
    return Path(name).suffix.lower() in SOURCE_SUFFIXES or Path(name).name.lower() in SOURCE_NAMES

def import_bytes(store, name, kind, body, group=None):
    entries, skipped = [], 0
    if kind == 'code':
        member_name(name)
        if not source_file(name):raise DomainError('code_file_unsupported')
        if exclusion(name):raise DomainError('file_excluded',reason=exclusion(name))
        if len(body)>SafeZip.MAX_FILE:raise DomainError('code_import_limit')
        if b'\0' in body:raise DomainError('binary_file')
        entries = [(name,body)]
    else:
        # Validate every path, collision and special-file flag before filtering.
        try:
            archive = zipfile.ZipFile(io.BytesIO(body))
        except zipfile.BadZipFile:raise DomainError('zip_invalid')
        with archive:
            manifest = SafeZip(io.BytesIO(body)).manifest()
            for item in manifest:
                if item['directory']:continue
                if item['excluded'] or not source_file(item['path']):
                    skipped += 1
                    continue
                try:data = archive.read(item['path'])
                except (zipfile.BadZipFile,RuntimeError,OSError):raise DomainError('zip_invalid')
                if b'\0' in data:
                    skipped += 1
                    continue
                entries.append((item['path'],data))
    if not entries:raise DomainError('code_project_empty')
    # Stable archive bytes make repeated file/project selections deduplicate.
    output = io.BytesIO()
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED) as archive:
        for path,data in sorted(entries):
            item=zipfile.ZipInfo(path,date_time=(1980,1,1,0,0,0))
            item.external_attr=0o100644 << 16
            archive.writestr(item,data)
    payload=output.getvalue();sha=hash_bytes(payload)
    existing=store.one("SELECT id FROM resources WHERE type='code' AND sha256=? AND state NOT IN ('deleted','missing')",(sha,))
    if existing:
        result={'resource':store.resource(existing['id']),'duplicate':True}
    else:
        target=contained(store.root,'code-'+sha[:16]+'.zip',False)
        if target.exists() and digest(target)!=sha:raise DomainError('hash_conflict')
        if not target.exists():target.write_bytes(payload)
        result=store.import_local({'path':target.relative_to(store.project).as_posix()})
        resource=result['resource']
        metadata={**resource['metadata'],'import_kind':'project' if kind=='code-project' else 'source_file','original_name':name,'file_count':len(entries),'skipped_count':skipped}
        title=name[:-4] if kind=='code-project' and name.lower().endswith('.zip') else name
        store.db.execute('UPDATE resources SET title=?,metadata=?,revision=revision+1,updated_at=? WHERE id=?',(title,json_text(metadata),now(),resource['id']))
        store.event('resource',resource['id'],resource['revision']+1)
    resource=result['resource']
    if group and resource['id'] not in group['resource_ids']:
        store.group_members(group['id'],{'base_revision':group['revision'],'resource_ids':group['resource_ids']+[resource['id']]})
    return {**result,'resource':store.resource(resource['id']),'file_count':len(entries),'skipped_count':skipped}
