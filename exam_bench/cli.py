"""Codex benchmark CLI. Import execution adapters only for execution commands."""
import argparse
import json
import shutil
from pathlib import Path


def main():
    p = argparse.ArgumentParser(prog='exam-bench', description='Codex benchmark on Windows, Linux and macOS')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor', help='Inspect machine prerequisites; never contact a model')
    sub.add_parser('selftest', help='Check process supervision without a model or 1C')
    site = sub.add_parser('site', help='Serve public results or an empty task catalogue')
    site.add_argument('--port', type=int, default=8879)
    site.add_argument('--catalogue-only', action='store_true')
    probe = sub.add_parser('probe', help='Run a short Codex-only live probe, without 1C or exam solving')
    probe.add_argument('--model', required=True)
    probe.add_argument('--client', default=shutil.which('codex'))
    probe.add_argument('--auth-seed', default=str(Path.home()/'.codex/auth.json'))
    probe.add_argument('--run-id', required=True)
    probe.add_argument('--timeout', type=int, default=60)
    e = sub.add_parser('prepare')
    for name in ('binary', 'starter', 'evidence'):
        e.add_argument('--'+name, required=True)
    calibration = sub.add_parser('calibrate', help='Calibrate the grader in real 1C; does not contact models')
    for name in ('starter-source', 'starter-dt', 'binary', 'evidence'):
        calibration.add_argument('--'+name, required=True)
    r = sub.add_parser('start')
    for name in ('plan', 'evidence', 'starter', 'task', 'client', 'auth-seed'):
        r.add_argument('--'+name, required=True)
    r.add_argument('--probe', action='store_true')
    for name in ('passport', 'calibration', 'starter-dt', 'tariff'):
        r.add_argument('--'+name)
    q = sub.add_parser('report'); q.add_argument('result'); q.add_argument('output')
    a = p.parse_args()
    import signal
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt('SIGTERM')))
    if a.command == 'doctor':
        from .portable import doctor
        print(json.dumps(doctor(), ensure_ascii=False, indent=2)); return
    if a.command == 'selftest':
        from .portable import selftest
        print(json.dumps(selftest(), indent=2)); return
    if a.command == 'site':
        from tools.serve_result_site import serve
        serve(a.port, catalogue_only=a.catalogue_only); return
    if a.command == 'probe':
        from .portable import probe_codex
        print(json.dumps(probe_codex(a), ensure_ascii=False, indent=2)); return
    from .report import save
    if a.command == 'report':
        save(json.loads(Path(a.result).read_text(encoding='utf-8')), a.output); return
    if a.command == 'prepare':
        from .platform import prepare_environment, verify_runtime_and_reset
        prepare_environment(a.binary, a.starter, a.evidence)
        pp = verify_runtime_and_reset(a.binary, a.starter, a.evidence)
        print(json.dumps({'state': pp['state'], 'runtime': pp['runtime_probe_verified'], 'reset': pp['reset_verified']})); return
    if a.command == 'calibrate':
        from .calibrate import calibrate
        summary = calibrate(a.starter_source, a.starter_dt, a.binary, a.evidence)
        print(json.dumps({'accepted': summary['accepted'], 'evidence': a.evidence})); return
    from .codex import start
    plan = json.loads(Path(a.plan).read_text(encoding='utf-8'))
    if plan.get('client', 'codex') != 'codex':
        raise SystemExit('This CLI runs Codex only')
    checks = None
    if not a.probe:
        from .preflight import main_gates
        from .common import digest
        if not all((a.passport, a.calibration, a.starter_dt)):
            raise SystemExit('Main attempt requires passport, calibration and starter-dt')
        checks = main_gates(plan, a.task, a.client, a.starter, a.passport, a.calibration)
        if plan.get('starter_dt_sha256') != digest(a.starter_dt):
            raise ValueError('Starter DT differs from pinned plan')
    result = start(plan, a.evidence, a.starter, a.task, a.client, a.auth_seed,
                   prompt='Read worker.json. Create out/probe.txt containing exactly READY. Do not solve the exam. End the session.' if a.probe else None,
                   starter_dt=a.starter_dt)
    if not a.probe:
        from .common import write_json
        from .finalize import finalize
        from .runtime import platform_binary
        write_json(Path(a.evidence)/'preflight.json', checks)
        result = finalize(a.evidence, a.task, a.starter_dt, platform_binary(), a.tariff)
    save(result, Path(a.evidence)/'report.md')
    print(json.dumps({'run_id': result['run_id'], 'status': result['process']['status'], 'tokens': result['metrics']['tokens']}))


if __name__ == '__main__':
    main()
