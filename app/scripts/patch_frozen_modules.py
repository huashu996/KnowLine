"""Update selected modules in this distribution without rebuilding dependencies.

Archive format reference: PyInstaller/archive/readers.py and writers.py.
All untouched compressed entries and the executable bootloader are preserved.
The result is staged; this utility never replaces a running executable.
"""
import argparse
import hashlib
import importlib.util
import marshal
from pathlib import Path
import struct
import zlib

COOKIE = struct.Struct('!8sIIII64s')
ENTRY = struct.Struct('!IIIIBc')
MAGIC = b'MEI\x0c\x0b\x0a\x0b\x0e'


def read_archive(path):
    data = Path(path).read_bytes()
    at = data.rfind(MAGIC)
    if at < 0:
        raise ValueError('Not a PyInstaller executable')
    cookie = COOKIE.unpack_from(data, at)
    if at + COOKIE.size != len(data):
        raise ValueError('Refusing executable with an unrecognized trailer/signature')
    start = at + COOKIE.size - cookie[1]
    cursor, end = start + cookie[2], start + cookie[2] + cookie[3]
    entries = []
    while cursor < end:
        size, offset, length, unpacked, compressed, kind = ENTRY.unpack_from(data, cursor)
        if size < ENTRY.size or cursor + size > end:
            raise ValueError('Invalid archive table')
        name = data[cursor + ENTRY.size:cursor + size].rstrip(b'\0').decode('utf-8')
        entries.append((name, unpacked, compressed, kind, data[start + offset:start + offset + length]))
        cursor += size
    return data[:start], cookie, entries


def read_pyz(blob):
    if blob[:4] != b'PYZ\0' or blob[4:8] != importlib.util.MAGIC_NUMBER:
        raise ValueError('Use the same Python version as the packaged application')
    offset = struct.unpack_from('!i', blob, 8)[0]
    toc = dict(marshal.loads(blob[offset:]))
    return toc


def modules(path):
    _, _, entries = read_archive(path)
    entry = next(e for e in entries if e[3] == b'z')
    blob = zlib.decompress(entry[4]) if entry[2] else entry[4]
    return blob, read_pyz(blob)


def module_code(path, name):
    blob, toc = modules(path)
    _, offset, size = toc[name]
    return marshal.loads(zlib.decompress(blob[offset:offset + size]))


def patch(source, target, replacements, allow_new_modules=False, preserve_existing_offsets=False):
    source, target = Path(source), Path(target)
    if source.resolve() == target.resolve() or target.exists():
        raise ValueError('Choose a new staging filename')
    prefix, cookie, entries = read_archive(source)
    original_blob, original_toc = modules(source)
    missing = set(replacements) - original_toc.keys()
    if missing and not allow_new_modules:
        raise ValueError(f'Modules missing from distribution: {sorted(missing)}')
    import re
    for name in missing:
        if not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+',name) or name.rsplit('.',1)[0] not in original_toc:
            raise ValueError('New modules require an existing package: '+name)
    if preserve_existing_offsets and next(e for e in entries if e[3]==b'z')[2]:
        raise ValueError('Offset preservation requires an uncompressed PYZ entry')
    # Existing desktop processes may lazily read their cached PYZ offsets from
    # the executable pathname. Keep that data while appending replacements;
    # new processes read the new TOC, existing processes retain valid offsets.
    pyz = bytearray(original_blob if preserve_existing_offsets else original_blob[:min(v[1] for v in original_toc.values())])
    new_toc = []
    for name, (kind, offset, size) in original_toc.items():
        payload = original_blob[offset:offset + size]
        if name in replacements:
            old_code = marshal.loads(zlib.decompress(payload))
            code = compile(Path(replacements[name]).read_bytes(), old_code.co_filename, 'exec', dont_inherit=True)
            payload = zlib.compress(marshal.dumps(code), 6)
        if preserve_existing_offsets and name not in replacements:
            new_toc.append((name,(kind,offset,size)))
        else:
            new_toc.append((name, (kind, len(pyz), len(payload))))
            pyz.extend(payload)
    for name in sorted(missing):
        code=compile(Path(replacements[name]).read_bytes(),name.replace('.','/')+'.py','exec',dont_inherit=True)
        payload=zlib.compress(marshal.dumps(code),6)
        new_toc.append((name,(0,len(pyz),len(payload))));pyz.extend(payload)
    toc_offset = len(pyz)
    pyz.extend(marshal.dumps(new_toc))
    struct.pack_into('!i', pyz, 8, toc_offset)
    payloads, table = bytearray(), bytearray()
    for name, unpacked, compressed, kind, payload in entries:
        if kind == b'z':
            unpacked = len(pyz)
            payload = zlib.compress(pyz, 6) if compressed else bytes(pyz)
        encoded = name.encode('utf-8') + b'\0'
        size = ((ENTRY.size + len(encoded) + 15) // 16) * 16
        table.extend(ENTRY.pack(size, len(payloads), len(payload), unpacked, compressed, kind))
        table.extend(encoded.ljust(size - ENTRY.size, b'\0'))
        payloads.extend(payload)
    new_cookie = COOKIE.pack(MAGIC, len(payloads) + len(table) + COOKIE.size,
                             len(payloads), len(table), cookie[4], cookie[5])
    target.write_bytes(prefix + payloads + table + new_cookie)
    # Verify every untouched compressed module, not just the replacement names.
    check_blob, check_toc = modules(target)
    assert set(original_toc)|missing == set(check_toc)
    for name in missing:module_code(target,name)
    for name, (_, offset, size) in original_toc.items():
        _, new_offset, new_size = check_toc[name]
        if name not in replacements:
            assert original_blob[offset:offset + size] == check_blob[new_offset:new_offset + new_size], name
        else:
            module_code(target, name)
    assert read_archive(target)[0] == prefix
    if preserve_existing_offsets:
        assert check_blob[12:len(original_blob)]==original_blob[12:]
    return {'updated_modules': sorted(set(replacements)-missing),'new_modules':sorted(missing), 'unchanged_modules': len(original_toc) - len(set(replacements)-missing),
            'existing_process_module_offsets_preserved':preserve_existing_offsets,
            'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}


if __name__ == '__main__':
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('target')
    parser.add_argument('modules', nargs='+', help='module=source.py')
    parser.add_argument('--allow-new-modules', action='store_true',help='Explicitly allow new code modules in existing packages')
    parser.add_argument('--preserve-existing-offsets',action='store_true',help='Append replacements while retaining the module bytes needed by existing desktop processes')
    args = parser.parse_args()
    print(json.dumps(patch(args.source, args.target, dict(item.split('=', 1) for item in args.modules),args.allow_new_modules,args.preserve_existing_offsets), indent=2))
