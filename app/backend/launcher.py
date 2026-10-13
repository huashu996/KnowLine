"""Start one hidden local service, wait for health, then open the UI."""
import json
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
import hashlib
from pathlib import Path


def main():
    from .layout import project_root,app_dir,data_path,identity
    project = project_root(Path(__file__).resolve().parent.parent)
    if not (app_dir(project) / 'dist' / 'index.html').exists():
        print('Frontend build missing. Run install-workbench.cmd first.')
        return 1
    state = data_path(project,'.knowledge')
    state.mkdir(exist_ok=True)
    config = json.loads((state / 'config.json').read_text('utf-8')) if (state / 'config.json').exists() else {}
    port = config.get('port', 8765)
    url = f'http://127.0.0.1:{port}'
    def health():
        try:
            with urllib.request.urlopen(url + '/api/v1/health', timeout=1) as response:
                data = json.load(response)
            if data.get('app') == 'local-knowledge-workbench' and data.get('project_id') == identity(project):
                return True
        except Exception:
            pass
        return False
    if not health():
        probe = socket.socket()
        try:
            probe.bind(('127.0.0.1', port))
        except OSError:
            print(f'Port {port} is occupied. Change port in .knowledge/config.json. No process was stopped.')
            return 1
        finally:
            probe.close()
        with (state / 'server.log').open('ab') as log:
            process = subprocess.Popen([sys.executable, '-m', 'backend.cli', '--port', str(port), 'serve'], cwd=app_dir(project), stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for _ in range(120):
            if health():
                break
            if process.poll() is not None:
                print('Service failed. Read .knowledge/server.log for details.')
                return 1
            time.sleep(.5)
        else:
            print('Service health timeout. Read .knowledge/server.log.')
            return 1
    print(url)
    if '--no-browser' not in sys.argv:
        webbrowser.open(url)
    return 0


if __name__ == '__main__':
    sys.exit(main())
