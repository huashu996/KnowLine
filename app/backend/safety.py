"""File inputs are data. Never execute code or follow links found in resources."""
import hashlib
import json
import os
import re
import stat
import time
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath


class DomainError(Exception):
    def __init__(self, code, status=422, **params):
        self.code, self.status, self.params = code, status, params
        super().__init__(code)


def digest(path):
    h = hashlib.sha256()
    with open(io_path(path), 'rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(data)
    return h.hexdigest()


def hash_bytes(data):
    return hashlib.sha256(data).hexdigest()


def io_path(path):
    absolute = str(Path(path).absolute())
    if os.name == 'nt' and not absolute.startswith('\\\\?\\'):
        return '\\\\?\\' + absolute if not absolute.startswith('\\\\') else '\\\\?\\UNC\\' + absolute[2:]
    return absolute


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w', encoding='utf-8') as stream:
        stream.write(json_text(value))
        stream.flush()
        os.fsync(stream.fileno())
    for attempt in range(6):
        try:
            os.replace(tmp,path)
            break
        except PermissionError:
            if attempt==5:raise
            time.sleep(.01*2**attempt)


def contained(root, relative, must_exist=True):
    root = Path(root).resolve()
    # Only project-root aliases apply; frozen snapshots and nested scopes never broaden.
    if any((root/name/'project-layout.json').is_file() for name in ['app','软件平台']):
        from .layout import relative as resolve_relative
        relative=resolve_relative(root,relative)
    path = root / relative
    try:
        Path(io_path(path)).resolve(strict=must_exist).relative_to(Path(io_path(root)).resolve())
    except (ValueError, OSError):
        raise DomainError('path_outside_scope')
    # Reject *all* reparse points, including junctions, even inside the root.
    for part in [path, *path.parents]:
        if part == root:
            break
        checked = Path(io_path(part))
        if checked.exists() and (checked.is_symlink() or getattr(checked.stat(follow_symlinks=False), 'st_file_attributes', 0) & 0x400):
            raise DomainError('unsafe_link')
    return path


DEVICES = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)', re.I)
IGNORED = {'.git', 'node_modules', '.venv', 'venv', 'dist', 'build', '__pycache__', '.knowledge', '.claude', '.agents'}
CONFIG_FILES = {'agents.md', 'claude.md', '.mcp.json', '.gitmodules'}


def exclusion(name):
    parts = PurePosixPath(name).parts
    if any(p in IGNORED for p in parts):
        return 'dependency_or_control_directory'
    base = parts[-1].lower() if parts else ''
    if base.startswith('.env') or base in {'id_rsa', 'id_ed25519', 'credentials', 'secrets.json'} or base.endswith(('.pem', '.key', '.p12', '.pfx')):
        return 'secret_file'
    if base in CONFIG_FILES:
        return 'untrusted_agent_configuration'
    if base.endswith(('.ipynb', '.exe', '.dll', '.so', '.bin', '.pt', '.pth', '.onnx', '.zip', '.tar', '.gz', '.7z')):
        return 'binary_or_nested_archive'
    return None


def member_name(raw):
    if '\\' in raw or '\x00' in raw or ':' in raw or raw.startswith('/'):
        raise DomainError('zip_unsafe_path', file=raw)
    pieces = raw.rstrip('/').split('/')
    if not pieces or any(not p or p in {'.', '..'} or p.endswith((' ', '.')) or DEVICES.match(p) or re.search(r'[<>"|?*\x00-\x1f]', p) for p in pieces):
        raise DomainError('zip_unsafe_path', file=raw)
    return '/'.join(pieces)


class SafeZip:
    MAX_ENTRIES = 10000
    MAX_TOTAL = 256 * 1024 * 1024
    MAX_FILE = 16 * 1024 * 1024
    MAX_PREVIEW = 2 * 1024 * 1024
    MAX_RATIO = 300

    def __init__(self, path):
        self.path = path
        self._manifest = None

    def manifest(self):
        if self._manifest is not None:
            return self._manifest
        result, seen, total = [], {}, 0
        try:
            with zipfile.ZipFile(self.path) as z:
                items = z.infolist()
                if len(items) > self.MAX_ENTRIES:
                    raise DomainError('zip_limit')
                for item in items:
                    name = member_name(item.orig_filename)
                    key = unicodedata.normalize('NFC', name).casefold()
                    if key in seen:
                        raise DomainError('zip_collision', file=name)
                    seen[key] = item.is_dir()
                    mode = item.external_attr >> 16
                    if mode and stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}:
                        raise DomainError('zip_link_or_special', file=name)
                    if item.flag_bits & 1:
                        raise DomainError('zip_encrypted')
                    total += item.file_size
                    if item.file_size > self.MAX_FILE or total > self.MAX_TOTAL or item.file_size / max(1, item.compress_size) > self.MAX_RATIO:
                        raise DomainError('zip_limit', file=name)
                    result.append({'path': name, 'size': item.file_size, 'directory': item.is_dir(), 'excluded': exclusion(name), 'language': language(name)})
                for key in seen:
                    for ancestor in PurePosixPath(key).parents:
                        if str(ancestor) in seen and not seen[str(ancestor)]:
                            raise DomainError('zip_collision', file=key)
        except (zipfile.BadZipFile, OSError):
            raise DomainError('zip_invalid')
        self._manifest = result
        return result

    def read(self, name, limit=None):
        manifest = self.manifest()
        entry = next((f for f in manifest if f['path'] == name and not f['directory']), None)
        if not entry:
            raise DomainError('file_not_found', 404)
        if entry['excluded']:
            raise DomainError('file_excluded', reason=entry['excluded'])
        limit = limit or self.MAX_PREVIEW
        if entry['size'] > limit:
            raise DomainError('file_too_large')
        with zipfile.ZipFile(self.path) as z, z.open(name) as stream:
            data = stream.read(limit + 1)
            if len(data) > limit:
                raise DomainError('zip_limit')
            return data

    def extract(self, target):
        entries = self.manifest()
        target = Path(target)
        target.mkdir(parents=True, exist_ok=False)
        total = 0
        try:
            with zipfile.ZipFile(self.path) as z:
                for entry in entries:
                    if entry['directory'] or entry['excluded']:
                        continue
                    output = contained(target, entry['path'], False)
                    Path(io_path(output)).parent.mkdir(parents=True, exist_ok=True)
                    count = 0
                    with z.open(entry['path']) as source, open(io_path(output), 'xb') as dest:
                        while data := source.read(65536):
                            count += len(data)
                            total += len(data)
                            if count > self.MAX_FILE or total > self.MAX_TOTAL:
                                raise DomainError('zip_limit')
                            dest.write(data)
            atomic_json(target / '_manifest.json', entries)
        except Exception:
            # Do not publish this directory as usable. Keep forensic marker.
            atomic_json(target / '_FAILED.json', {'code': 'extract_failed'})
            raise
        return entries


def text_projection(data, encoding='utf-8-sig'):
    if encoding not in {'utf-8-sig', 'utf-8', 'gb18030', 'latin-1'}:
        raise DomainError('unsupported_encoding')
    if b'\x00' in data:
        raise DomainError('binary_file')
    try:
        return data.decode(encoding).replace('\r\n', '\n').replace('\r', '\n')
    except UnicodeError:
        raise DomainError('encoding_required')


def language(name):
    return {'.cpp': 'C++', '.hpp': 'C++', '.h': 'C/C++', '.c': 'C', '.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript', '.rs': 'Rust', '.md': 'Markdown', '.yaml': 'YAML', '.yml': 'YAML', '.xml': 'XML', '.json': 'JSON', '.sh': 'Shell', '.txt': 'Text', '.cmake': 'CMake'}.get(Path(name).suffix.lower(), 'Text')


def directory_manifest(root):
    root = Path(root).resolve()
    result = []
    total = 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in list(dirs):
            path = Path(directory, name)
            rel = path.relative_to(root).as_posix()
            contained(root, rel)
            reason = exclusion(rel + '/placeholder')
            if reason:
                result.append({'path': rel, 'directory': True, 'size': 0, 'excluded': reason, 'language': 'Text'})
                dirs.remove(name)
        for name in names:
            path = Path(directory, name)
            rel = path.relative_to(root).as_posix()
            member_name(rel)
            contained(root, rel)
            size = path.stat().st_size
            reason = exclusion(rel) or ('file_too_large' if size > SafeZip.MAX_FILE else None)
            sha = None if reason else digest(path)
            total += 0 if reason else size
            if len(result) >= SafeZip.MAX_ENTRIES or total > SafeZip.MAX_TOTAL:
                raise DomainError('directory_limit')
            result.append({'path': rel, 'directory': False, 'size': size, 'excluded': reason, 'language': language(rel), 'sha256': sha})
    return sorted(result, key=lambda f:f['path'])


def directory_digest(manifest):
    return hash_bytes(json_text(manifest).encode())


def filename(year, title, venue, short_id, directory, locale='zh'):
    def clean(value):
        value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', ' ', str(value)).strip(' .')
        value = re.sub(r'\s+', ' ', value)
        if DEVICES.match(value):
            value = '_' + value
        return value
    en=locale=='en'
    year, title, venue = clean(year or ('Unverified Year' if en else '待核实年份')), clean(title or ('Untitled Paper' if en else '待整理题名')), clean(venue or ('Unverified Venue' if en else '待核实刊会'))
    # Conservative per-path budget; never change OS long-path policy.
    budget = max(32, min(180, 238 - len(str(directory))))
    tail = f' - {venue[:50]}'
    head = f'{year} - '
    available = max(12, budget - len(head) - len(tail) - 20)
    title = title[:available].rstrip()
    return f'{head}{title}{tail} [{short_id[:8]}].pdf'
