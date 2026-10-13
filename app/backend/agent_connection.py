"""Bounded local connection setup; never changes providers or tool permissions."""
import json
import os
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
from .safety import DomainError

CONNECT_SECONDS = 180
PROBE_SECONDS = 100
LOCAL_REQUEST_SECONDS = 5
ERROR_MESSAGES = {
    'agent_command_file_required': '首次连接需要本地执行客户端的适配配置。',
    'agent_command_invalid': '连接配置格式错误，请重新生成本机适配配置。',
    'agent_command_missing': '未找到已选客户端的可执行文件，请安装客户端后重新连接。',
    'agent_command_conflict': '客户端启动参数互相冲突，请修正适配配置。',
    'agent_client_unsupported': '已安装客户端不支持配置中的启动参数，请更新客户端或适配配置。',
    'agent_login_required': '本地客户端尚未登录或登录已失效，请在该客户端登录后重新连接。',
    'agent_client_unavailable': '本地客户端启动检查失败，请检查客户端安装。',
    'agent_binding_unreadable': '无法读取连接配置，请检查本机文件权限并重新连接。',
    'agent_connection_in_progress': '此项目已有连接操作进行中，请等待该操作返回。',
    'agent_binding_changed': '连接配置已被另一操作更换，请重新连接。',
    'agent_service_unavailable': '知序本地服务未能启动，请检查本实例端口。',
    'agent_request_timeout': '知序本地服务响应超时，请检查服务状态。',
    'agent_worker_start_failed': '本地执行桥启动失败，请检查客户端与文件权限。',
    'agent_execution_failed': '本地客户端执行失败；本次连接未完成。',
    'agent_execution_timeout': '本地客户端未在握手时限内完成执行，请检查登录及网络。',
    'agent_probe_timeout': '本次连接在三分钟内未完成，请检查客户端登录、网络和权限后重连。',
    'agent_probe_failed': '客户端未正确完成文件读写握手，连接未建立。',
    'agent_probe_expired': '连接握手已过期，请重新连接。',
    'project_mismatch': '当前端口属于另一知序实例，请使用本项目配置的端口。',
}
TERMINAL_ERRORS = frozenset({
    'agent_command_invalid', 'agent_command_missing', 'agent_command_conflict',
    'agent_client_unsupported', 'agent_login_required', 'agent_binding_unreadable',
})


def read_adapter(path):
    try:
        value = json.loads(Path(path).read_text('utf-8-sig'))
    except OSError as exc:
        raise DomainError('agent_binding_unreadable', 409) from exc
    except (ValueError, UnicodeError) as exc:
        raise DomainError('agent_command_invalid', 409) from exc
    if not isinstance(value, dict):
        raise DomainError('agent_command_invalid', 409)
    argv = value.get('argv')
    if (not isinstance(argv, list) or not argv or
            any(not isinstance(arg, str) or not arg or len(arg) > 10000 or '\0' in arg for arg in argv)):
        raise DomainError('agent_command_invalid', 409)
    return value


def prepare_adapter(config, project, check_client=False):
    config = dict(config)
    command = list(config['argv'])
    explicit_codex = config.get('builtin') == 'codex'
    if explicit_codex and '--approve-for-me' in command and any(
            arg in {'--sandbox', '-s'} or arg.startswith('--sandbox=') for arg in command):
        raise DomainError('agent_command_conflict', 409)
    executable = command[0].replace('{project}', str(project))
    if not Path(executable).is_absolute() and ('/' in executable or '\\' in executable):
        executable = str(Path(project) / executable)
    resolved = shutil.which(executable)
    if not resolved and Path(executable).is_file():
        resolved = str(Path(executable).resolve())
    if not resolved and explicit_codex:
        # Only repair the same explicitly selected client; never pick a provider.
        from .codex_runner import executable as find_codex
        resolved = find_codex()
    if not resolved:
        raise DomainError('agent_command_missing', 409)
    if os.name == 'nt' and Path(resolved).suffix.lower() in {'.cmd', '.bat'}:
        raise DomainError('agent_client_unsupported', 409)
    command[0] = str(resolved)
    config['argv'] = command
    if explicit_codex and check_client:
        def inspect(args):
            try:
                return subprocess.run([command[0], *args], capture_output=True, text=True,
                                      encoding='utf-8', errors='replace', timeout=8,
                                      creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise DomainError('agent_client_unavailable', 409) from exc
        help_result = inspect(['exec', '--help'])
        if help_result.returncode:
            raise DomainError('agent_client_unavailable', 409)
        for flag in ('--approve-for-me', '--sandbox', '--skip-git-repo-check'):
            if flag in command and flag not in help_result.stdout:
                raise DomainError('agent_client_unsupported', 409)
        login = inspect(['login', 'status'])
        if login.returncode or 'Logged in' not in login.stdout + login.stderr:
            raise DomainError('agent_login_required', 409)
    return config


def same_adapter(left, right):
    return all(left.get(key) == right.get(key) for key in ('argv', 'builtin'))


@contextmanager
def connect_lock(folder):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'connect.lock').open('a+b') as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise DomainError('agent_connection_in_progress', 409) from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
