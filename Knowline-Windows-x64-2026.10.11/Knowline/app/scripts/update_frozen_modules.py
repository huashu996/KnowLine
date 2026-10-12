"""Stage a targeted update to an unsigned Python 3.12 PyInstaller runtime.

Use the project's .build-tools PyInstaller package. Preserve compressed bytes
of every unchanged module and verify both archive layers before deployment.
This script never replaces the running executable or edits project data.
"""
import hashlib
import importlib.util
import io
import json
import marshal
from pathlib import Path
import struct
import sys
import zlib

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / '.build-tools'))
from PyInstaller.archive.readers import CArchiveReader
from PyInstaller.archive.writers import CArchiveWriter
import pefile


def stage(modules):
    original = APP / 'Knowline/Knowline.exe'
    destination = original.with_name('Knowline.updated.exe')
    raw = original.read_bytes()
    pe = pefile.PE(data=raw)
    security = pe.OPTIONAL_HEADER.DATA_DIRECTORY[4]
    if security.Size:
        raise RuntimeError('Signed executables require the normal signing build.')
    archive = CArchiveReader(str(original))
    cookie = struct.unpack(archive._COOKIE_FORMAT, raw[archive._end_offset - archive._COOKIE_LENGTH:archive._end_offset])
    if cookie[4] != sys.version_info.major * 100 + sys.version_info.minor:
        raise RuntimeError('Build Python must match the frozen runtime.')
    old_pyz = archive.extract('PYZ.pyz')
    assert old_pyz[:8] == b'PYZ\0' + importlib.util.MAGIC_NUMBER
    table = dict(marshal.loads(old_pyz[struct.unpack('!i', old_pyz[8:12])[0]:]))
    assert set(modules) <= table.keys()
    output = io.BytesIO(old_pyz[:17])
    output.seek(17)
    new_table = []
    changed = {}
    for name, (kind, offset, length) in table.items():
        payload = old_pyz[offset:offset + length]
        if name in modules:
            assert kind == 0
            source = APP / (name.replace('.', '/') + '.py')
            code = compile(source.read_bytes(), name.replace('.', '/') + '.py', 'exec')
            payload = zlib.compress(marshal.dumps(code), 6)
            changed[name] = hashlib.sha256(source.read_bytes()).hexdigest()
        new_table.append((name, (kind, output.tell(), len(payload))))
        output.write(payload)
    toc_at = output.tell()
    output.write(marshal.dumps(new_table))
    output.seek(8)
    output.write(struct.pack('!i', toc_at))
    new_pyz = output.getvalue()

    package = io.BytesIO()
    toc = []
    for name, (offset, length, size, compressed, kind) in archive.toc.items():
        payload = raw[archive._start_offset + offset:archive._start_offset + offset + length]
        if name == 'PYZ.pyz':
            size = len(new_pyz)
            payload = zlib.compress(new_pyz, 9) if compressed else new_pyz
        toc.append((package.tell(), len(payload), size, compressed, kind, name))
        package.write(payload)
    toc.extend((package.tell(), 0, 0, 0, 'o', option) for option in archive.options)
    toc_offset = package.tell()
    toc_bytes = CArchiveWriter._serialize_toc(toc)
    package.write(toc_bytes)
    package.write(struct.pack(archive._COOKIE_FORMAT, cookie[0], package.tell() + archive._COOKIE_LENGTH,
                              toc_offset, len(toc_bytes), cookie[4], cookie[5]))
    updated = raw[:archive._start_offset] + package.getvalue() + raw[archive._end_offset:]
    updated_pe = pefile.PE(data=updated)
    updated_pe.OPTIONAL_HEADER.CheckSum = updated_pe.generate_checksum()
    destination.write_bytes(updated_pe.write())

    check = CArchiveReader(str(destination))
    assert check.options == archive.options and check.toc.keys() == archive.toc.keys()
    for name in archive.toc:
        if name != 'PYZ.pyz':
            assert check.extract(name) == archive.extract(name), name
    checked_pyz = check.extract('PYZ.pyz')
    checked_table = dict(marshal.loads(checked_pyz[struct.unpack('!i', checked_pyz[8:12])[0]:]))
    assert checked_table.keys() == table.keys()
    for name, (kind, offset, length) in checked_table.items():
        payload = checked_pyz[offset:offset + length]
        if name not in modules:
            old_kind, old_offset, old_length = table[name]
            assert kind == old_kind and payload == old_pyz[old_offset:old_offset + old_length], name
        else:
            code = marshal.loads(zlib.decompress(payload))
            assert code.co_filename == name.replace('.', '/') + '.py'
    report = {'modules': changed, 'preserved_modules': len(table) - len(changed),
              'original_sha256': hashlib.sha256(raw).hexdigest(),
              'staged_sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}
    (APP / 'runtime-update.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    stage(sys.argv[1:])
