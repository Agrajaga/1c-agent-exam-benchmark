"""Machine settings; no account secrets belong in this file."""
import json
import os
import platform
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def settings():
    path = Path(os.environ.get('EXAM_BENCH_CONFIG', ROOT / '.local/machine.json'))
    data = json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else {}
    unknown = set(data) - {'platform_binary', 'platform_version', 'platform_cache', 'isolation'}
    if unknown:
        raise ValueError('Unknown machine settings: ' + ', '.join(sorted(unknown)))
    default = 'macos' if platform.system() == 'Darwin' else 'bubblewrap' if platform.system() == 'Linux' and shutil.which('bwrap') else 'required'
    mode = data.get('isolation', default)
    if mode not in ('macos', 'bubblewrap', 'dedicated-host', 'required'):
        raise ValueError('isolation must be macos, bubblewrap, dedicated-host or required')
    return {**data, 'isolation': mode}


def platform_binary(required=True):
    value = settings().get('platform_binary') or shutil.which('1cv8')
    if value is None and platform.system() == 'Darwin':
        value = '/opt/1cv8/8.3.27.2074/1cv8'
    if value is None:
        if required:
            raise ValueError('Set platform_binary in .local/machine.json to the installed 1cv8 executable')
        return None
    return str(Path(value).expanduser().resolve())


def cache_directory():
    value = settings().get('platform_cache')
    if value:
        return Path(value).expanduser().resolve()
    if os.name == 'nt':
        return Path(os.environ['LOCALAPPDATA']) / '1C/1cv8'
    return Path.home() / '.1cv82/1C/1Cv82'


def machine_identity():
    return {**settings(), 'os': platform.system(), 'architecture': platform.machine(),
            'platform_binary': platform_binary(False)}


def child_environment(root):
    """Explicit allowlist: keep executable search/system variables, omit tokens."""
    root = Path(root)
    keys = ('PATH', 'HOME', 'USER', 'LOGNAME', 'USERPROFILE', 'SystemRoot', 'SYSTEMROOT',
            'WINDIR', 'COMSPEC', 'PATHEXT', 'APPDATA', 'LOCALAPPDATA',
            'ProgramData', 'ALLUSERSPROFILE', 'PUBLIC',
            'CommonProgramFiles', 'CommonProgramFiles(x86)', 'CommonProgramW6432',
            'COMPUTERNAME', 'HOMEDRIVE', 'HOMEPATH', 'SYSTEMDRIVE', 'USERNAME',
            'USERDOMAIN', 'USERDOMAIN_ROAMINGPROFILE', 'NUMBER_OF_PROCESSORS',
            'PROCESSOR_ARCHITECTURE', 'PROCESSOR_IDENTIFIER', 'PROCESSOR_LEVEL', 'PROCESSOR_REVISION',
            'ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432', 'DISPLAY', 'XAUTHORITY',
            'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR')
    env = {key: os.environ[key] for key in keys if key in os.environ}
    env.update(LANG='en_US.UTF-8', PYTHONUTF8='1', TMPDIR=str(root/'tmp'),
               TMP=str(root/'tmp'), TEMP=str(root/'tmp'), TMPPREFIX=str(root/'tmp/zsh'))
    return env


def require_execution_mode():
    mode = settings()['isolation']
    if mode == 'required':
        raise ValueError('No outer sandbox configured on this OS. On a dedicated test machine/VM only, '
                         'set isolation to dedicated-host in .local/machine.json. This grants host access; '
                         'these runs are not isolation-verified or eligible for comparison.')
    if mode == 'macos' and platform.system() != 'Darwin':
        raise ValueError('The macos isolation backend requires macOS')
    if mode == 'bubblewrap' and (platform.system() != 'Linux' or not shutil.which('bwrap')):
        raise ValueError('The bubblewrap backend requires Linux and bwrap installed')
    return mode
