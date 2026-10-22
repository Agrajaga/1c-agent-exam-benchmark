"""Pinned native harness packages, separate from historical macOS profiles.

Each package must pass a local capability probe before an exam can use it.
Published skills are copied unchanged, and all state stays inside the worker.
"""
import json
import os
import shutil
import sys
import subprocess
import time
from pathlib import Path
from .common import digest, tree_manifest, write_json

ROOT = Path(__file__).resolve().parents[1]
_daemons = {}


def registry(root=None):
    path = (root or ROOT) / '.local/harnesses/portable.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


def available(name):
    return name in registry()


def entry(name):
    value = registry().get(name)
    if value is None:
        raise ValueError('Native harness is not installed: ' + name)
    return value


def profile(name, root=None):
    """The sealed profile of this machine's installation. It lives next to the package, never in Git:
    package bytes differ between machines, so one machine's seal must not replace another's."""
    root = root or ROOT
    local = root / '.local/harnesses' / name / 'profile.json'
    if not local.is_file():
        # Installations sealed before profiles moved out of Git keep working: adopt the tracked
        # profile when it describes exactly this installation.
        tracked = root / 'profiles' / (name + '-portable.json')
        manifest = root / '.local/harnesses' / name / 'package-manifest.json'
        if tracked.is_file() and manifest.is_file():
            data = json.loads(tracked.read_text(encoding='utf-8'))
            if data.get('package_manifest_sha256') == digest(manifest) and data.get('configuration') == registry(root).get(name):
                shutil.copyfile(tracked, local)
    return local


def verify(name, require_probe=True):
    value = entry(name)
    root = ROOT / '.local/harnesses' / name
    policy = json.loads(profile(name).read_text(encoding='utf-8'))
    if policy.get('configuration') != value:
        raise ValueError('Native harness registration differs from pinned profile: ' + name)
    if digest(root / 'package-manifest.json') != policy['package_manifest_sha256']:
        raise ValueError('Native harness manifest differs from pinned profile: ' + name)
    if tree_manifest(root / 'package') != json.loads((root / 'package-manifest.json').read_text(encoding='utf-8')):
        raise ValueError('Native harness package changed: ' + name)
    if require_probe:
        receipt = json.loads((root / 'capability.json').read_text(encoding='utf-8'))
        if not receipt.get('accepted') or receipt['profile_sha256'] != digest(profile(name)):
            raise ValueError('Native harness capability has not been proved: ' + name)
    return root


def format_values(ws, runtime, package):
    return {'workspace': str(ws), 'src': str(ws / 'out/src'), 'tmp': str(ws / 'tmp'),
            'runtime': str(runtime), 'package': str(package), 'python': sys.executable, 'python_bin': str(Path(sys.executable).parent),
            'platform': __import__('exam_bench.runtime', fromlist=['platform_binary']).platform_binary(False) or ''}


def spec(name, ws, runtime, package):
    value = entry(name)
    values = format_values(ws, runtime, package)
    command = value['command'].format(**values)
    args = [arg.format(**values) for arg in value.get('args', [])]
    env = {key: val.format(**values) for key, val in value.get('env', {}).items()}
    env.update({'PYTHONDONTWRITEBYTECODE': '1', 'TMPDIR': str(ws / 'tmp'), 'TMP': str(ws / 'tmp'), 'TEMP': str(ws / 'tmp')})
    return command, args, env


def configure(name, ws, runtime, run, require_probe=True):
    source = verify(name, require_probe)
    value = entry(name)
    package = ws / 'harness' / ('unica' if name.startswith('unica-') else name)
    shutil.copytree(source / 'package', package)
    skills = []
    if value.get('skills'):
        skills_root = package / value['skills']
        # Copy the full skill tree so relative references retain author layout.
        shutil.copytree(skills_root, runtime / 'skills' / name)
        skills = sorted(p.parent.name for p in skills_root.glob('*/SKILL.md'))
        for directory in value.get('skill_siblings', []):
            shutil.copytree(skills_root.parent / directory, runtime / 'skills' / directory)
    if name == 'shirokov-skills':
        shutil.copytree(package / '.codex', ws / '.codex')
        from .runtime import platform_binary
        write_json(ws / '.v8-project.json', {'v8path': platform_binary(), 'databases': [
            {'id': 'origin', 'name': 'Benchmark worker', 'type': 'file', 'path': str(ws / 'ib'),
             'aliases': ['origin', 'dev'], 'configSrc': str(ws / 'out/src')}]})
    if name == 'code-index-1.9.0':
        home = ws / 'tmp/code-index-home'
        home.mkdir(parents=True, exist_ok=True)
        (home / 'daemon.toml').write_text('[[paths]]\npath = ' + json.dumps(str(ws / 'out/src')) + '\nlanguage = "bsl"\n', encoding='utf-8')
    config = ''
    if value.get('server'):
        command, args, env = spec(name, ws, runtime, package)
        key = 'mcp_servers.' + value['server']
        config = '\n[' + key + ']\n' + ''.join(k + ' = ' + json.dumps(v) + '\n' for k, v in
            [('command', command), ('args', args), ('cwd', str(ws)), ('startup_timeout_sec', 120), ('tool_timeout_sec', 600)])
        config += '[' + key + '.env]\n' + ''.join(k + ' = ' + json.dumps(v) + '\n' for k, v in env.items())
    worker_env = {}
    if value.get('worker_env'):
        values = format_values(ws, runtime, package)
        worker_env = {key: val.format(**values) for key, val in value['worker_env'].items()}
        if 'PATH' in worker_env:
            worker_env['PATH'] += os.pathsep + os.environ.get('PATH', '')
    write_json(run / 'portable-harness-manifest.json', tree_manifest(package))
    harness = {'name': name, 'version': value['version'], 'mcp_servers': [value['server']] if value.get('server') else [],
               'additional_skills': skills, 'registration': value['registration'], 'worker_env': worker_env,
               'portable': True, 'package_path': str(package), 'profile_sha256': digest(profile(name))}
    write_json(run / 'portable-harness.json', harness)
    return harness, config


def integrity(ws, run):
    meta = json.loads((run / 'portable-harness.json').read_text(encoding='utf-8'))
    package = Path(meta['package_path'])
    return tree_manifest(package) == json.loads((run / 'portable-harness-manifest.json').read_text(encoding='utf-8'))


def codex_overrides(harness, ws, runtime):
    value = entry(harness['name'])
    if not value.get('server'):
        return []
    command, args, env = spec(harness['name'], ws, runtime, Path(harness['package_path']))
    key = 'mcp_servers.' + value['server']
    argv = []
    for field, data in [('command', command), ('args', args), ('cwd', str(ws)),
                        ('startup_timeout_sec', 120), ('tool_timeout_sec', 600)]:
        argv += ['-c', key + '.' + field + '=' + json.dumps(data)]
    for field, data in env.items():
        argv += ['-c', key + '.env.' + field + '=' + json.dumps(data)]
    return argv


def launch(ws, env, run, timeout=90):
    meta = json.loads((run / 'portable-harness.json').read_text(encoding='utf-8'))
    if meta['name'] != 'code-index-1.9.0':
        return
    command, _, extra = spec(meta['name'], ws, ws / 'client-home', Path(meta['package_path']))
    child_env = {**env, **extra}
    options = {'creationflags': 0x4 | subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
    with (run / 'code-index-daemon.log').open('wb') as log:
        process = subprocess.Popen([command, 'daemon', 'run'], cwd=ws, env=child_env, stdout=log, stderr=log, **options)
    job = None
    if os.name == 'nt':
        from .windows_job import Job
        try:
            job = Job(process)
        except BaseException:
            process.kill(); process.wait(); raise
    _daemons[str(ws)] = (process, job)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and (job.active() if job else process.poll() is None):
        status = subprocess.run([command, 'daemon', 'status', '--json'], env=child_env, capture_output=True, timeout=10)
        try:
            data = json.loads(status.stdout)
            if data.get('paths') and all(p.get('status') == 'ready' for p in data['paths']):
                write_json(run / 'code-index-ready.json', data)
                return
        except ValueError:
            pass
        time.sleep(.5)
    stop(ws)
    reason=(run/'code-index-daemon.log').read_text(encoding='utf-8',errors='replace')[-1000:]
    raise RuntimeError('Native code-index daemon did not become ready: '+reason)


def stop(ws):
    process, job = _daemons.pop(str(ws), (None, None))
    if process is None:
        return {'stop_confirmed': True}
    try:
        if job:
            job.terminate()
        elif process.poll() is None:
            import signal
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
        if job:
            deadline = time.monotonic() + 5
            while job.active() and time.monotonic() < deadline:
                time.sleep(.05)
        return {'stop_confirmed': not job.active() if job else process.poll() is not None}
    finally:
        if job:
            job.close()
        shutil.rmtree(Path(ws) / 'out/src/.code-index', ignore_errors=True)
