"""Exercise the published Windows MCP processing in a disposable 1C infobase."""
import json
import shutil
import os
import tempfile
import urllib.request
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from exam_bench.common import digest, write_json, utc
from exam_bench.runtime import platform_binary, child_environment
from exam_bench.platform import OneC
from exam_bench import mcp_toolkit as toolkit
from exam_bench import portable_harnesses as native
from tools.check_native_harnesses import seal, payload


def grant_platform_cache(ws, evidence, starter_dt):
    """Restore the probe base as the exam does: outside the sandbox, then grant only its new cache namespace.

    The sandboxed 1C client must write its platform cache; without the grant it stops at once.
    """
    from exam_bench.locking import file_lock
    from exam_bench.runtime import cache_directory, settings
    cache_parent = cache_directory()
    cache_parent.mkdir(parents=True, exist_ok=True)
    with file_lock(cache_parent / '.exam-benchmark-bootstrap.lock'):
        before = set(cache_parent.iterdir())
        adapter = OneC(platform_binary(), ws / 'restore', 180)
        adapter.restore(ws / 'ib', starter_dt)
        adapter.export(ws / 'ib', ws / 'bootstrap-export')
        paths = [str(p.resolve()) for p in set(cache_parent.iterdir()) - before if p.is_dir()]
    if settings()['isolation'] != 'dedicated-host' and len(paths) != 1:
        raise ValueError('Cannot uniquely identify the probe platform cache namespace')
    write_json(ws / 'platform-cache-grant.json', {'paths': paths, 'owner': 'toolkit probe only'})
    write_json(evidence / 'cache-allocation.json', {'new_directories': paths})
    shutil.rmtree(ws / 'bootstrap-export')


def check(timeout=120):
    name = toolkit.NAME
    root = ROOT / '.local/harnesses' / name
    cfg = json.loads((ROOT / '.local/demo/config.json').read_text(encoding='utf-8'))
    os.environ['EXAM_BENCH_CONFIG'] = str(ROOT / cfg['machine_config'])
    native.verify(name, require_probe=False)
    evidence = root / ('probe-' + utc().replace(':', '').replace('.', '').replace('+', '-'))
    evidence.mkdir()
    transcript = []
    try:
        with tempfile.TemporaryDirectory(prefix='mt-') as td:
            ws = Path(td).resolve(); (ws / 'tmp').mkdir(); (ws / 'client-home/skills').mkdir(parents=True)
            grant_platform_cache(ws, evidence, ROOT / cfg['starter_dt'])
            toolkit.configure(ws, ws / 'client-home', evidence, 'codex', require_probe=False)
            session = None
            counter = 0
            def rpc(method, params=None):
                nonlocal session, counter
                counter += 1
                headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
                if session:
                    headers['Mcp-Session-Id'] = session
                request = urllib.request.Request(toolkit.URL, json.dumps({'jsonrpc': '2.0', 'id': counter,
                    'method': method, 'params': params or {}}).encode(), headers)
                with urllib.request.urlopen(request, timeout=30) as response:
                    session = response.headers.get('Mcp-Session-Id', session)
                    body = response.read().decode('utf-8')
                if body.startswith('event:') or body.startswith('data:'):
                    body = '\n'.join(line[5:].strip() for line in body.splitlines() if line.startswith('data:'))
                value = json.loads(body)
                transcript.append({'method': method, 'params': params, 'response': value})
                if value.get('error'):
                    raise ValueError('Toolkit RPC error: ' + str(value['error']))
                return value.get('result')
            try:
                toolkit.launch(ws, child_environment(ws), evidence, timeout=timeout)
                rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'exam-bench', 'version': '1'}})
                tools = rpc('tools/list')['tools']
                write_json(root / 'tool-surface.json', tools)
                query = next(t for t in tools if t['name'] == 'execute_query')
                schema = query['inputSchema']
                key = next(k for k in schema['properties'] if 'query' in k.lower())
                response = rpc('tools/call', {'name': 'execute_query', 'arguments': {key: 'ВЫБРАТЬ 1 КАК Проверка'}})
                result = payload(response)
                if not isinstance(result, dict) or result.get('success') is not True:
                    raise ValueError('Toolkit query was not successful')
            finally:
                cleanup = toolkit.stop(ws)
                write_json(evidence / 'cleanup.json', cleanup)
                if not cleanup['stop_confirmed'] or not cleanup['port_released']:
                    raise ValueError('Toolkit session did not stop or port was not released')
        write_json(evidence / 'transcript.json', transcript)
        receipt = {'accepted': True, 'created_at': utc(), 'profile_sha256': digest(native.profile(name)),
                   'model_requests': 0, 'scope': 'Проверен SQL-запрос через MCP в отдельной 1С 8.3.27; экзаменационный прогон ещё не выполнялся.'}
    except Exception as error:
        write_json(evidence / 'transcript.json', transcript)
        receipt = {'accepted': False, 'created_at': utc(), 'profile_sha256': digest(native.profile(name)),
                   'model_requests': 0, 'reason': str(error)[:500]}
    write_json(root / 'capability.json', receipt)
    print(json.dumps(receipt, ensure_ascii=False), flush=True)
    return receipt['accepted']


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout',type=int,default=120,choices=range(1,601))
    args=parser.parse_args()
    raise SystemExit(0 if check(args.timeout) else 1)
