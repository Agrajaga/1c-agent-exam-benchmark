"""Single-tool harnesses served as stdio MCP servers over the solver's sources (owner request 2026-10-13).

Each harness is exactly one published tool, pinned by release digest and copied into the worker: BSL Language Server
(its built-in MCP mode), bsl-analyzer (workspace MCP profile, offline), rlm-tools-bsl (with its second-LLM helpers
disabled: the solver's model stays the only model) and code-index-mcp (bsl-indexer; the stand runs its indexing
daemon, the MCP server only reads). The server processes inherit the solver's outer sandbox.
"""
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from .common import tree_manifest, utc, write_json
from .isolation import wrapped

JAVA = '/opt/homebrew/opt/openjdk@21/bin/java'
HARNESSES = {
    'bsl-ls-1.1.0-rc.6': {'server': 'bsl-language-server', 'tool': 'BSL Language Server 1.1.0-rc.6', 'probe_tool': 'analyze_file'},
    'bsl-analyzer-0.3.2': {'server': 'bsl-analyzer', 'tool': 'bsl-analyzer 0.3.2', 'probe_tool': 'metadata'},
    'rlm-tools-bsl-1.43.0': {'server': 'rlm-tools-bsl', 'tool': 'rlm-tools-bsl 1.43.0', 'probe_tool': 'rlm_execute'},
    'code-index-1.9.0': {'server': 'code-index', 'tool': 'code-index-mcp (bsl-indexer) 1.9.0', 'probe_tool': 'get_object_structure'},
}


def is_stdio_harness(name):
    return name in HARNESSES


def server_spec(name, ws):
    """command, args and env of the MCP server inside the worker."""
    package = ws / 'harness' / name
    src = str(ws / 'out/src')
    if name == 'bsl-ls-1.1.0-rc.6':
        return JAVA, ['-Xmx4g', '-jar', str(package / 'bsl-language-server-1.1.0-rc.6-exec.jar'), 'mcp'], {'TMPDIR': str(ws / 'tmp')}
    if name == 'bsl-analyzer-0.3.2':
        # No platform connection, embeddings or external help token: the offline workspace profile only.
        return str(package / 'bsl-analyzer'), ['mcp', 'serve', '--profile', 'workspace', '--mode', 'stdio', '-s', src], \
            {'BSL_MCP_BROKER': '0', 'BSL_CACHE_DIR': str(ws / 'tmp/bsl-analyzer-cache'), 'TMPDIR': str(ws / 'tmp')}
    if name == 'rlm-tools-bsl-1.43.0':
        # Empty keys and no .env loading switch off llm_query/llm_query_batched (a second model).
        return str(package / 'venv/bin/python'), ['-c', 'import sys; from rlm_tools_bsl.server import main; sys.exit(main())'], \
            {'_RLM_SERVICE_NO_ENV': '1', 'ANTHROPIC_API_KEY': '', 'RLM_LLM_BASE_URL': '', 'RLM_LLM_MODEL': '', 'OPENAI_API_KEY': '',
             'RLM_CONFIG_FILE': str(ws / 'tmp/rlm/service.json'), 'RLM_INDEX_DIR': str(ws / 'tmp/rlm/index'),
             'PYTHONDONTWRITEBYTECODE': '1', 'TMPDIR': str(ws / 'tmp')}
    if name == 'code-index-1.9.0':
        return str(package / 'bsl-indexer'), ['serve', '--path', src], {'CODE_INDEX_HOME': str(ws / 'tmp/code-index-home'), 'TMPDIR': str(ws / 'tmp')}
    raise ValueError('Unsupported harness: ' + name)


def configure(name, ws, runtime, run, client):
    from .harness import verify_package
    root = verify_package(name)
    shutil.copytree(root / 'package', ws / 'harness' / name, symlinks=True)
    write_json(run / 'harness-package-manifest.json', tree_manifest(ws / 'harness' / name))
    command, args, env = server_spec(name, ws)
    meta = HARNESSES[name]
    harness = {'name': name, 'tool': meta['tool'], 'mcp_servers': [meta['server']], 'additional_skills': [],
               'registration': 'the published tool as a stdio MCP server over out/src; nothing else added',
               'source_commit': json.loads((root / 'provenance.json').read_text(encoding='utf-8'))['commit']}
    if name == 'code-index-1.9.0':
        home = ws / 'tmp/code-index-home'
        home.mkdir(parents=True)
        (home / 'daemon.toml').write_text('[[paths]]\npath = %s\nlanguage = "bsl"\n' % json.dumps(str(ws / 'out/src')), encoding='utf-8')
        harness['index'] = ('the stand runs the indexing daemon over out/src for the whole solve; '
                            'the index folder out/src/.code-index is removed before the submission is frozen')
    write_json(run / 'harness-mcp-registration.json', {'command': command, 'args': args, 'env': env})
    if client == 'codex':
        return harness, None
    write_json(runtime / 'mcp.json', {'mcpServers': {meta['server']: {'type': 'stdio', 'command': command, 'args': args, 'env': env}}})
    return harness, runtime / 'mcp.json'


def codex_overrides(name, ws):
    """The registration as -c flags: Codex runs with the user config file ignored."""
    server = HARNESSES[name]['server']
    command, args, env = server_spec(name, ws)
    key = 'mcp_servers.' + server  # bare TOML keys: letters, digits, '-' and '_'
    argv = ['-c', '%s.command=%s' % (key, json.dumps(command)), '-c', '%s.args=%s' % (key, json.dumps(args)),
            '-c', '%s.startup_timeout_sec=120' % key, '-c', '%s.tool_timeout_sec=600' % key]
    for k, v in env.items():
        argv += ['-c', '%s.env.%s=%s' % (key, k, json.dumps(v))]
    return argv


def launch(name, ws, env, run, timeout=120):
    """code-index only: the indexing daemon is the single writer; the MCP server answers daemon_offline without it."""
    if name != 'code-index-1.9.0':
        return None
    binary = ws / 'harness' / name / 'bsl-indexer'
    daemon_env = {**env, 'CODE_INDEX_HOME': str(ws / 'tmp/code-index-home')}
    log = run / 'code-index'
    log.mkdir()
    started = time.monotonic()
    process = subprocess.Popen(wrapped([str(binary), 'daemon', 'run'], ws), cwd=ws, env=daemon_env,
                               stdout=(log / 'daemon.log').open('wb'), stderr=subprocess.STDOUT, start_new_session=True)
    status = None

    def ready():
        return bool(status and status.get('paths') and all(p.get('status') == 'ready' for p in status['paths']))
    while time.monotonic() - started < timeout and process.poll() is None:
        result = subprocess.run([str(binary), 'daemon', 'status', '--json'], env=daemon_env, capture_output=True, text=True)
        try:
            status = json.loads(result.stdout)
        except ValueError:
            status = None
        if ready():
            break
        time.sleep(0.5)
    evidence = {'pid': process.pid, 'ready': ready(), 'status': status, 'elapsed_ms': round((time.monotonic() - started) * 1000), 'started_at': utc()}
    write_json(log / 'launch.json', evidence)
    if not evidence['ready']:
        stop(name, ws, env)
        raise RuntimeError('code-index daemon did not become ready')
    return evidence


def stop(name, ws, env, grace=3):
    """Stop what the stand started and the servers the client left behind; drop the code-index service folder."""
    marker = str(Path(ws).resolve() / 'harness' / name)
    if name == 'code-index-1.9.0':
        subprocess.run([str(Path(marker) / 'bsl-indexer'), 'daemon', 'stop'], env={**env, 'CODE_INDEX_HOME': str(ws / 'tmp/code-index-home')},
                       capture_output=True, timeout=30)

    def owned():
        output = subprocess.run(['ps', '-axo', 'pid=,args='], capture_output=True, text=True, check=True).stdout
        return [int(line.split(None, 1)[0]) for line in output.splitlines() if marker in line]
    initial = owned()
    for pid in initial:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and owned():
        time.sleep(0.2)
    for pid in owned():
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    time.sleep(0.3)
    removed = False
    index = ws / 'out/src/.code-index'
    if name == 'code-index-1.9.0' and index.is_dir() and not index.is_symlink():
        shutil.rmtree(index)
        removed = True
    return {'processes': initial, 'stop_confirmed': not owned(), 'index_folder_removed': removed}


def call_succeeded(events, name, client, tool=None):
    """A completed, non-error call of the harness tool in the native stream."""
    server, tool = HARNESSES[name]['server'], tool or HARNESSES[name]['probe_tool']
    if client == 'claude':
        ids = {b.get('id') for e in events if e.get('type') == 'assistant' for b in (e.get('message') or {}).get('content') or []
               if isinstance(b, dict) and b.get('type') == 'tool_use' and b.get('name') == 'mcp__%s__%s' % (server, tool)}
        return any(isinstance(b, dict) and b.get('type') == 'tool_result' and b.get('tool_use_id') in ids and not b.get('is_error')
                   for e in events if e.get('type') == 'user' for b in (e.get('message') or {}).get('content') or [])
    for e in events:
        item = e.get('item') or {}
        result = item.get('result') or {}
        if (e.get('type') == 'item.completed' and item.get('type') == 'mcp_tool_call' and item.get('server') == server
                and item.get('tool') == tool and item.get('status') == 'completed' and item.get('error') is None
                and not result.get('is_error') and not result.get('isError')):
            return True
    return False
