"""Windows download-marker regression; no installed application or user data needed."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'StartKnowline.ps1'
POWERSHELL = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
REQUIRED = [
    'app/Knowline/Knowline.exe', 'app/dist/index.html',
    'app/Knowline/_internal/pythonnet/runtime/Python.Runtime.dll',
    'app/Knowline/_internal/webview/lib/Microsoft.Web.WebView2.Core.dll',
    'app/Knowline/_internal/webview/lib/Microsoft.Web.WebView2.WinForms.dll',
]


@unittest.skipUnless(os.name == 'nt', 'NTFS download-marker tests require Windows')
class DownloadedStartup(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='Knowline startup ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / '中文目录 (download) & test'
        self.entries = []
        for relative in REQUIRED:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('fixture: ' + relative).encode())
            self.entries.append(dict(path=relative, bytes=path.stat().st_size,
                                     sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            self.mark(path)
        self.unlisted = self.root / 'app/Knowline/_internal/unlisted.dll'
        self.user_file = self.root / 'resource/incoming/user.dll'
        for path in (self.unlisted, self.user_file):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'user-supplied file')
            self.mark(path)
        self.save_manifest()

    def mark(self, path):
        Path(str(path) + ':Zone.Identifier').write_text('[ZoneTransfer]\nZoneId=3\n')

    def marked(self, path):
        return Path(str(path) + ':Zone.Identifier').exists()

    def save_manifest(self):
        path = self.root / 'app/docs/RELEASE_MANIFEST.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(release='test', files=self.entries)), encoding='utf-8')

    def prepare(self):
        return subprocess.run([str(POWERSHELL), '-NoProfile', '-ExecutionPolicy', 'Bypass',
                               '-File', str(SCRIPT), '-ProjectRoot', str(self.root), '-PrepareOnly'],
                              capture_output=True, timeout=30)

    def test_verified_dlls_only_and_repeat_launch(self):
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        for relative in REQUIRED:
            self.assertEqual(self.marked(self.root / relative), not relative.endswith('.dll'))
        self.assertTrue(self.marked(self.unlisted))
        self.assertTrue(self.marked(self.user_file))
        self.assertEqual(self.prepare().returncode, 0)

    def test_corrupt_dll_leaves_all_markers_intact(self):
        (self.root / REQUIRED[-1]).write_bytes(b'incomplete download')
        self.mark(self.root / REQUIRED[-1])
        result = self.prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'incomplete or changed', result.stderr)
        for relative in REQUIRED:
            self.assertTrue(self.marked(self.root / relative))

    def test_missing_runtime_is_reported(self):
        (self.root / REQUIRED[-1]).unlink()
        self.assertNotEqual(self.prepare().returncode, 0)
        self.assertTrue(self.marked(self.root / REQUIRED[2]))

    def test_manifest_cannot_escape_installation(self):
        self.entries.append(dict(path='app/Knowline/_internal/../../../outside.dll',
                                 bytes=0, sha256='0' * 64))
        self.save_manifest()
        result = self.prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'Invalid runtime path', result.stderr)
        self.assertTrue(self.marked(self.root / REQUIRED[2]))

    def test_required_assembly_cannot_be_omitted_from_manifest(self):
        self.entries.pop()
        self.save_manifest()
        result = self.prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'Missing or duplicate', result.stderr)
        self.assertTrue(self.marked(self.root / REQUIRED[2]))


if __name__ == '__main__':
    unittest.main()
