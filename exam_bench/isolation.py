import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from .runtime import require_execution_mode, child_environment, cache_directory, platform_binary


def linux_wrapped(argv, workspace, grading=False):
    """Private mount/PID namespaces. Never bind the operator home or repo."""
    workspace = Path(workspace).resolve()
    command = [shutil.which('bwrap'), '--die-with-parent', '--unshare-pid', '--unshare-ipc',
               '--unshare-uts', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp']
    if grading:
        command += ['--unshare-net']
    reads = [Path(p) for p in ('/usr', '/bin', '/sbin', '/lib', '/lib64', '/etc') if Path(p).exists()]
    reads += [Path(argv[0]).resolve().parent, Path(sys.base_prefix).resolve()]
    binary = platform_binary(False)
    if binary:
        reads.append(Path(binary).parent)
    reads += [p for p in (Path.home()/'.1cv8', Path.home()/'.1C') if p.exists()]
    for path in sorted(set(reads), key=lambda p: len(p.parts)):
        command += ['--ro-bind', str(path), str(path)]
    cache = cache_directory()
    if grading and cache.exists():
        command += ['--bind', str(cache), str(cache)]
    elif not grading and (workspace/'platform-cache-grant.json').is_file():
        grant=json.loads((workspace/'platform-cache-grant.json').read_text(encoding='utf-8'))
        for value in grant['paths']:
            path=Path(value)
            if path.is_symlink() or path.resolve().parent!=cache.resolve():
                raise ValueError('Invalid worker cache namespace')
            command += ['--bind', str(path.resolve()), str(path.resolve())]
    command += ['--bind', str(workspace), str(workspace), '--chdir', str(workspace), '--', *map(str, argv)]
    return command


# Launchers that hand a command to launchd/LaunchServices, outside the sandbox and the supervised process group.
ESCAPE_TOOLS = ('/usr/bin/open', '/usr/bin/osascript', '/bin/launchctl')


def profile(workspace, executable, platform_binary=None):
    if platform.system() != 'Darwin':
        raise ValueError('Only the verified macOS worker is supported yet')
    workspace = Path(workspace).resolve()
    allowed_read = ['/System', '/usr', '/bin', '/sbin', '/Library', '/opt', '/private/etc', '/private/var/db', '/dev', str(Path(executable).resolve().parent), str(Path(sys.base_prefix).resolve())]
    # 1C licensing/settings are read-only. No project/curator directories are granted.
    allowed_read += [str(Path.home()/'.1cv8'), str(Path.home()/'Library/Application Support/1C'), str(Path.home()/'Library/Preferences')]
    rw = [str(workspace), '/dev/null', '/dev/tty']
    grant=workspace/'platform-cache-grant.json'
    if grant.is_file():
        data=json.loads(grant.read_text(encoding='utf-8'))
        cache_parent=(Path.home()/'.1cv82/1C/1Cv82').resolve()
        for value in data['paths']:
            path=Path(value).resolve()
            if path.parent!=cache_parent or path.is_symlink():raise ValueError('Invalid worker cache namespace')
            rw.append(str(path))
    lines = ['(version 1)', '(deny default)', '(allow process*)', '(allow sysctl-read)', '(allow mach-lookup)', '(allow ipc-posix*)', '(allow signal (target same-sandbox))', '(allow network*)', '(allow file-read-metadata)', '(allow user-preference-read)', '(allow file-read* (literal "/"))']
    for path in allowed_read:
        lines.append(f'(allow file-read* (subpath {json.dumps(path)}))')
    # Unica opens each directory component with O_NOFOLLOW. Only the named
    # ancestors are readable; their other children remain outside the policy.
    for path in workspace.parents:
        lines.append(f'(allow file-read* (literal {json.dumps(str(path))}))')
    lines.append(f'(allow file-read* (literal {json.dumps(str(Path.home()/".1C/1cestart/ibases.v8i"))}))')
    lines.append(f'(allow file-read* (literal {json.dumps(str(Path.home()/".1cv82/1C/1Cv82/1cv8u.pfl"))}))')
    lines.append(f'(allow file-read* (literal {json.dumps(str(Path.home()/".1cv82/1C/1Cv82"))}))')
    for path in rw:
        lines.append(f'(allow file-read* file-write* (subpath {json.dumps(path)}))')
    lines.append(f'(allow file-read-metadata (literal {json.dumps(str(workspace.parent))}))')
    for tool in ESCAPE_TOOLS:
        lines.append(f'(deny process-exec (literal {json.dumps(tool)}))')
    result = workspace/'sandbox.sb'
    result.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return result


def grading_profile(root, executable):
    """Untrusted submitted code runs inside 1C during grading: no network, writes only to its case root."""
    if platform.system() != 'Darwin':
        raise ValueError('Only the verified macOS worker is supported yet')
    root = Path(root).resolve()
    allowed_read = ['/System', '/usr', '/bin', '/sbin', '/Library', '/private/etc', '/private/var/db', '/dev', str(Path(executable).resolve().parent)]
    allowed_read += [str(Path.home()/'.1cv8'), str(Path.home()/'Library/Application Support/1C'), str(Path.home()/'Library/Preferences')]
    # Platform cache and the 1C start list hold no curator data; a new infobase allocates its own namespace there.
    rw = [str(root), str(Path.home()/'.1cv82'), str(Path.home()/'.1C'), '/dev/null', '/dev/tty']
    lines = ['(version 1)', '(deny default)', '(allow process*)', '(allow sysctl-read)', '(allow mach-lookup)', '(allow ipc-posix*)', '(allow signal (target same-sandbox))', '(allow network* (local unix))', '(allow file-read-metadata)', '(allow user-preference-read)', '(allow file-read* (literal "/"))']
    for path in allowed_read:
        lines.append(f'(allow file-read* (subpath {json.dumps(path)}))')
    for path in root.parents:
        lines.append(f'(allow file-read* (literal {json.dumps(str(path))}))')
    for path in rw:
        lines.append(f'(allow file-read* file-write* (subpath {json.dumps(path)}))')
    for tool in ESCAPE_TOOLS:
        lines.append(f'(deny process-exec (literal {json.dumps(tool)}))')
    result = root/'grading-sandbox.sb'
    result.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return result


def grading_environment(root):
    """Never pass the operator environment (tokens, proxies) to graded code."""
    if require_execution_mode() == 'macos':
        env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'en_US.UTF-8', 'TMPDIR': str(Path(root).resolve()/'tmp')}
    else:
        env = child_environment(root)
    for key in ('HOME', 'USER', 'LOGNAME'):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def wrapped(argv, workspace):
    argv = [str(Path(argv[0]).resolve()), *argv[1:]]
    if require_execution_mode() == 'dedicated-host':
        return argv
    if require_execution_mode() == 'bubblewrap':
        return linux_wrapped(argv, workspace)
    policy = profile(workspace, argv[0])
    return ['/usr/bin/sandbox-exec', '-f', str(policy), *argv]


def verify(workspace, protected, readonly_secrets=()):
    """Real denials under the same outer solver policy: curator files, secrets, signals and launchd escapes."""
    workspace = Path(workspace).resolve()
    if require_execution_mode() == 'dedicated-host':
        return {'backend': 'dedicated-host', 'verified': False,
                'reason': 'No outer sandbox: use only a dedicated test account or VM; no comparison eligibility'}
    script = workspace/'isolation-check.py'
    script.write_text('''import json,os,pathlib,signal,subprocess,sys
result={}
for action in ('read','write'):
 try:
  p=pathlib.Path(sys.argv[1])
  p.read_bytes() if action=='read' else p.open('ab').close()
  result[action+'_denied']=False
 except (PermissionError,OSError): result[action+'_denied']=True
for index,secret in enumerate(sys.argv[3:]):
 try:
  path=pathlib.Path(secret)
  path.read_bytes() if path.is_file() else list(path.iterdir())
  result['secret_%d_read_denied'%index]=False
 except (PermissionError,OSError): result['secret_%d_read_denied'%index]=True
try:
 os.kill(int(sys.argv[2]),0);result['outside_signal_denied']=False
except PermissionError: result['outside_signal_denied']=True
except ProcessLookupError: result['outside_signal_denied']=LINUX_PID_NAMESPACE
for tool in ESCAPE_TOOLS:
 try:
  denied=subprocess.run([tool,'-h'],capture_output=True).returncode==126
 except PermissionError: denied=True
 result['exec_denied_'+pathlib.Path(tool).name]=denied
pathlib.Path('permitted.txt').write_text('ok')
result['workspace_writable']=True
print(json.dumps(result))
'''.replace('ESCAPE_TOOLS', repr(ESCAPE_TOOLS if platform.system()=='Darwin' else ())).replace('LINUX_PID_NAMESPACE',repr(platform.system()=='Linux')), encoding='utf-8')
    python = sys.executable
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(workspace/'tmp'))
    (workspace/'tmp').mkdir(exist_ok=True)
    secrets = [str(Path(x).resolve()) for x in readonly_secrets if Path(x).exists()]
    # The controller itself is the outside process the solver must not be able to signal.
    p = subprocess.run(wrapped([python, str(script), str(Path(protected).resolve()), str(os.getpid()), *secrets], workspace), cwd=workspace, env=env, capture_output=True, text=True)
    if p.returncode != 0:
        raise ValueError(f'Isolation probe exit {p.returncode}: '+p.stderr[:500])
    result = json.loads(p.stdout)
    result['secret_paths_checked'] = secrets
    if not all(v for k, v in result.items() if k != 'secret_paths_checked'):
        raise ValueError('Solver sandbox does not deny: '+', '.join(k for k, v in result.items() if v is False))
    return result
