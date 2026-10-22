import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from .runtime import ROOT, machine_identity, platform_binary, require_execution_mode
from .common import tree_manifest, write_json
from .process import supervise


def doctor():
    client = shutil.which('codex')
    binary = platform_binary(False)
    version = subprocess.run([client, '--version'], capture_output=True, text=True, timeout=15).stdout.strip() if client else None
    return {'python': sys.version.split()[0], 'os': platform.system(), 'codex': client,
            'codex_version': version, 'platform_binary': binary,
            'platform_installed': bool(binary and Path(binary).is_file()),
            'auth_seed_present': (Path.home()/'.codex/auth.json').is_file(),
            'machine': machine_identity(),
            'execution_scope': 'Codex only; portable harness=none',
            'outer_sandbox_verified': False,
            'note': 'doctor checks prerequisites, not 1C licensing, sandbox correctness or model access'}


def selftest():
    with tempfile.TemporaryDirectory(prefix='exam-selftest-') as td:
        root = Path(td)
        child = 'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]);time.sleep(30)'
        ok = supervise([sys.executable, '-c', 'import sys;print(sys.stdin.read());print("err",file=sys.stderr)'], root,
                       dict(os.environ), 'READY', 5, .2, root/'ok')
        timeout = supervise([sys.executable, '-c', child], root, dict(os.environ), '', .5, .2, root/'timeout')
        if ok['status'] != 'completed' or b'READY' not in (root/'ok/stdout.jsonl').read_bytes() or not ok['stop_confirmed']:
            raise RuntimeError('Process output self-test failed')
        if timeout['status'] != 'timeout' or not timeout['stop_confirmed']:
            raise RuntimeError('Process tree timeout self-test failed')
        return {'status': 'passed', 'output_capture': True, 'timeout_tree_stop': True, 'model_requests': 0}


def probe_codex(args):
    from .codex import start
    from .materials import delivery_metadata
    from .report import save
    require_execution_mode()
    if not args.client or not Path(args.client).is_file():
        raise ValueError('Pass --client with the Codex executable path')
    if not Path(args.auth_seed).is_file():
        raise ValueError('Codex auth.json missing: run codex login first')
    if not args.model.startswith('gpt-') or not 0 < args.timeout <= 300:
        raise ValueError('Use an exact gpt- model ID and timeout 1..300 seconds')
    if not args.run_id or not all(c.isalnum() or c in '-_' for c in args.run_id):
        raise ValueError('Invalid run ID')
    version = subprocess.run([args.client, '--version'], capture_output=True, text=True, check=True, timeout=15).stdout.strip()
    if not version.startswith('codex-cli '):
        raise ValueError('Expected a Codex CLI executable')
    task = ROOT/'tasks/1c-platform-official-sample'
    plan = {'schema_version': 1, 'run_id': args.run_id, 'client': 'codex',
            'client_version': version.removeprefix('codex-cli '), 'model': args.model,
            'billing_channel': 'subscription', 'harness': 'none', 'solve_timeout_seconds': args.timeout,
            'stop_grace_seconds': 3, 'purpose': 'integration_probe_not_exam_attempt',
            'acceptance_profile': 'not_applicable_probe', 'delegation': 'native_disabled',
            'machine': machine_identity(), **delivery_metadata(task), 'public_inputs': tree_manifest(task/'public')}
    run = ROOT/'.local/runs'/args.run_id
    starter = ROOT/'.local/probe-starter'; starter.mkdir(parents=True, exist_ok=True)
    result = start(plan, run, starter, task, args.client, args.auth_seed,
                   prompt='Read worker.json. Create out/probe.txt containing exactly READY. Do not open exam materials. End the session.')
    ready = (run/'artifacts/probe.txt').is_file() and (run/'artifacts/probe.txt').read_bytes() == b'READY'
    save(result, run/'report.md')
    receipt = {'run_id': args.run_id, 'status': result['process']['status'], 'ready': ready,
               'stop_confirmed': result['process']['stop_confirmed'], 'isolation_verified': result['isolation_verified']}
    write_json(run/'probe.json', receipt)
    if not ready or receipt['status'] != 'completed' or not receipt['stop_confirmed']:
        raise RuntimeError('Codex probe failed; see ' + str(run/'probe.json'))
    return receipt
