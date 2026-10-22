"""1C MCP Toolkit (ROCTUP, v1.9.0): an external processing that serves MCP from inside a 1C:Enterprise client session.

Unlike the other harnesses the tools live in a running 1C client, so the stand opens that session on the worker
infobase before the solve and closes every session of that infobase afterwards. The client runs under the same outer
sandbox as the solver: code the solver sends through execute_code is confined like its shell.
"""
import json
import os
import sys
import shutil
import signal
import socket
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from .common import tree_manifest, utc, write_json
from .isolation import wrapped

NAME = 'mcp-toolkit-1.9.0'
PORT = 6003  # the processing's default embedded-server port; attempts run one at a time
URL = 'http://127.0.0.1:%d/mcp' % PORT
PLATFORM = '/opt/1cv8/8.3.27.2074/1cv8'
EPF = 'MCP_Toolkit.epf' if os.name=='nt' else 'MCP_Toolkit_macos.epf' if sys.platform=='darwin' else 'MCP_Toolkit_linux.epf'
_jobs = {}
# Owner decision 2026-10-13, the author's maximum: automatic approval of the two keywords the processing can approve
# without a person; every other dangerous keyword is blocked with an error instead of waiting for a dialog nobody answers.
DANGER = {'danger_auto_write': True, 'danger_auto_priv': True, 'danger_confirm': False}


def configure(ws, runtime, run, client, require_probe=True):
    """Copy the pinned processing and the author's skills; register the MCP server for the client."""
    from .harness import verify_package
    if not require_probe:
        from .portable_harnesses import verify
        source=verify(NAME,require_probe=False)/'package'
    else:source = verify_package(NAME) / 'package'
    package = ws / 'harness/mcp-toolkit'
    shutil.copytree(source, package)
    skills = sorted(p.parent.name for p in (package / 'skills').glob('*/SKILL.md'))
    for skill in skills:
        shutil.copytree(package / 'skills' / skill, runtime / 'skills' / skill)
    write_json(run / 'mcp-toolkit-package-manifest.json', tree_manifest(package))
    harness = {'name': NAME, 'version': '1.9.0', 'mcp_servers': ['onec'], 'additional_skills': skills,
               'registration': 'published processing in a 1C:Enterprise client session opened by the stand; MCP over streamable HTTP',
               'mcp_url': URL, 'processing': str(package / EPF),
               'session': {'infobase': str(ws / 'ib'), 'opened_by_stand_before_solve': True,
                           'dangerous_operations': 'Записать/Write and УстановитьПривилегированныйРежим/SetPrivilegedMode approved '
                                                   'automatically; other dangerous keywords are blocked'}}
    if client == 'codex':
        harness['codex_config'] = '\n[mcp_servers.onec]\nurl = %s\nstartup_timeout_sec = 60\ntool_timeout_sec = 600\n' % json.dumps(URL)
        return harness, None
    write_json(runtime / 'mcp.json', {'mcpServers': {'onec': {'type': 'http', 'url': URL}}})
    return harness, runtime / 'mcp.json'


def port_free():
    with socket.socket() as s:
        return s.connect_ex(('127.0.0.1', PORT)) != 0


def initialize():
    body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
        'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'exam-bench', 'version': '1'}}}).encode()
    request = urllib.request.Request(URL, body, {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'})
    with urllib.request.urlopen(request, timeout=10) as response:
        return 'serverInfo' in response.read().decode('utf-8', 'replace')


def launch(ws, env, run, timeout=120):
    """Open the 1C client with the processing through its own autostart file (the only way to pass the approval flags)."""
    if not port_free():
        raise RuntimeError('MCP Toolkit port %d is already in use' % PORT)
    folder = ws / 'tmp/mcp-toolkit-autostart'
    folder.mkdir(parents=True)
    (folder / 'nonce').write_text('', encoding='utf-8')
    params = {'signal_path': str(folder / 'signal'), 'mappings_path': '', 'mcp_sessions': [], 'nonce_path': str(folder / 'nonce'),
              'claimed_path': str(folder / 'claimed'), 'restart_password': '', 'automatic_recovery': False, **DANGER}
    (folder / 'params.json').write_text(json.dumps(params), encoding='utf-8')
    from .runtime import platform_binary
    argv = [platform_binary(), 'ENTERPRISE', '/F', str(ws / 'ib'), '/Execute', str(ws / 'harness/mcp-toolkit' / EPF),
            '/C', 'autostart;%s;%s' % (datetime.now().strftime('%Y%m%d%H%M%S'), folder / 'params.json'),
            '/DisableStartupMessages', '/DisableStartupDialogs', '/Out', str(run/'mcp-toolkit.platform.log')]
    log = run / 'mcp-toolkit'
    log.mkdir()
    started = time.monotonic()
    options={'creationflags':0x4|subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}
    with (log/'client.log').open('wb') as output:
        process = subprocess.Popen(wrapped(argv, ws), cwd=ws, env=env, stdout=output, stderr=subprocess.STDOUT, **options)
    if os.name=='nt':
        from .windows_job import Job
        try:_jobs[str(Path(ws).resolve())]=(Job(process),process)
        except BaseException:
            process.kill();process.wait();raise
    ready = False
    while time.monotonic() - started < timeout and (_jobs[str(Path(ws).resolve())][0].active() if os.name=='nt' else process.poll() is None):
        signal_file = folder / 'signal'
        if signal_file.is_file() and signal_file.read_text(encoding='utf-8-sig').strip().startswith('failed'):
            break
        try:
            ready = initialize()
        except OSError:
            ready = False
        if ready:
            break
        time.sleep(1)
    state = (folder / 'signal').read_text(encoding='utf-8-sig').strip() if (folder / 'signal').is_file() else None
    evidence = {'argv': argv, 'pid': process.pid, 'url': URL, 'ready': ready, 'autostart_signal': state,
                'elapsed_ms': round((time.monotonic() - started) * 1000), 'approval_flags': DANGER, 'started_at': utc()}
    write_json(log / 'launch.json', evidence)
    if not ready:
        stop(ws)
        raise RuntimeError('1C MCP Toolkit did not start: signal %s' % state)
    return evidence


def sessions(ws):
    """1C:Enterprise clients of this worker infobase, including the ones restart_1c_session relaunched."""
    marker = str(Path(ws).resolve() / 'ib')
    output = subprocess.run(['ps', '-axo', 'pid=,args='], capture_output=True, text=True, check=True).stdout
    found = []
    for line in output.splitlines():
        pid, _, args = line.strip().partition(' ')
        if ' ENTERPRISE' in args and marker in args:
            found.append(int(pid))
    return found


def stop(ws, grace=3):
    if os.name=='nt':
        owned=_jobs.pop(str(Path(ws).resolve()),None)
        if owned is None:return {'sessions':[],'stop_confirmed':True,'port_released':port_free()}
        job,process=owned
        try:
            job.terminate();process.wait(timeout=grace+2)
            deadline=time.monotonic()+grace
            while job.active() and time.monotonic()<deadline:time.sleep(.05)
            stopped=not job.active()
        finally:job.close()
        return {'sessions':[process.pid],'stop_confirmed':stopped,'port_released':port_free()}
    initial = sessions(ws)
    for pid in initial:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and sessions(ws):
        time.sleep(0.2)
    killed = []
    for pid in sessions(ws):
        try:
            os.kill(pid, signal.SIGKILL)
            killed.append(pid)
        except ProcessLookupError:
            pass
    time.sleep(0.5)
    return {'sessions': initial, 'killed': killed, 'stop_confirmed': not sessions(ws), 'port_released': port_free()}


def call_succeeded(events, tool, client):
    """A successful call of the toolkit tool in the native stream: the payload text is JSON with success = true."""
    def ok(text):
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            return False
        return isinstance(payload, dict) and payload.get('success') is True
    if client == 'claude':
        names = {'mcp__onec__' + tool}
        ids = {b.get('id') for e in events if e.get('type') == 'assistant' for b in (e.get('message') or {}).get('content') or []
               if isinstance(b, dict) and b.get('type') == 'tool_use' and b.get('name') in names}
        for e in events:
            for b in (e.get('message') or {}).get('content') or [] if e.get('type') == 'user' else []:
                if isinstance(b, dict) and b.get('type') == 'tool_result' and b.get('tool_use_id') in ids and not b.get('is_error'):
                    content = b.get('content')
                    texts = [content] if isinstance(content, str) else [c.get('text') for c in content or [] if isinstance(c, dict)]
                    if any(ok(t) for t in texts):
                        return True
        return False
    for e in events:
        item = e.get('item') or {}
        if e.get('type') != 'item.completed' or item.get('type') != 'mcp_tool_call' or item.get('server') != 'onec' or item.get('tool') != tool:
            continue
        if item.get('status') != 'completed' or item.get('error') is not None:
            continue
        result = item.get('result') or {}
        if any(isinstance(c, dict) and ok(c.get('text')) for c in result.get('content') or []):
            return True
    return False
