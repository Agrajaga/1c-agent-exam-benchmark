#!/usr/bin/env python3
"""Run pinned attempts sequentially, continuing independently of the chat UI."""
import argparse
import fcntl
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from exam_bench.common import digest, tree_manifest, utc, write_json
from exam_bench.preflight import main_gates
from tools.compare_harness_runs import compare, load_attempt


def execute(campaign):
    campaign = Path(campaign).resolve()
    config = json.loads((campaign/'campaign.json').read_text())
    if (campaign/'state.json').exists():
        raise ValueError('Campaign already started; no implicit model retry')
    # Hold across solving and grading, so another campaign cannot contend for 1C.
    with (ROOT/'.local/campaigns/.execution.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for entry in config['runs']:
            plan = json.loads((ROOT/entry['plan_ref']).read_text())
            if digest(ROOT/entry['plan_ref']) != entry['plan_sha256']:
                raise ValueError('Pinned campaign plan changed')
            if (ROOT/'.local/runs'/entry['run_id']).exists():
                raise FileExistsError(entry['run_id'])
            main_gates(plan, ROOT/config['task_ref'], entry.get('client', config.get('client')), ROOT/config['starter_ref'],
                       ROOT/config['passport_ref'], ROOT/config['calibration_ref'])
        plans = [json.loads((ROOT/e['plan_ref']).read_text()) for e in config['runs']]
        # Time series and their limits are separate cohorts (owner decision A09): one campaign, one series.
        if len({(p.get('time_series'), p['solve_timeout_seconds']) for p in plans}) != 1:
            raise ValueError('A campaign must use one time series and one solve limit')
        state = {'schema_version': 1, 'campaign_id': config['campaign_id'],
                 'status': 'running', 'execution': 'sequential', 'started_at': utc(),
                 'model': config.get('model'), 'input_revision': config['input_revision'],
                 'time_series': plans[0].get('time_series'), 'timeout_seconds_per_run': plans[0]['solve_timeout_seconds'],
                 'runs': [{'run_id': r['run_id'], 'harness': r['harness'], 'client': r.get('client_kind', 'codex'), 'status': 'queued'}
                          for r in config['runs']]}
        def save():
            write_json(campaign/'state.json', state)
        save()
        for entry, row in zip(config['runs'], state['runs']):
            run = ROOT/'.local/runs'/entry['run_id']
            row.update(status='running', started_at=utc());save()
            print('START ' + row['run_id'], flush=True)
            argv = [sys.executable, '-m', 'exam_bench.cli', 'start',
                    '--plan', str(ROOT/entry['plan_ref']), '--evidence', str(run),
                    '--starter', str(ROOT/config['starter_ref']),
                    '--task', str(ROOT/config['task_ref']), '--client', entry.get('client', config.get('client')),
                    '--auth-seed', entry.get('auth_seed', config.get('auth_seed')), '--passport', str(ROOT/config['passport_ref']),
                    '--calibration', str(ROOT/config['calibration_ref']),
                    '--starter-dt', str(ROOT/config['starter_dt_ref']),
                    '--tariff', str(ROOT/config['tariff_ref'])]
            with (campaign/(row['run_id']+'.launcher.log')).open('wb') as log:
                process = subprocess.Popen(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
                row['launcher_pid'] = process.pid;save()
                exit_code = process.wait()
            row.update(exit_code=exit_code, finished_at=utc(),
                       status='completed' if exit_code == 0 else 'launcher_failed')
            result_file = run/'result.json'
            if result_file.is_file():
                result = json.loads(result_file.read_text())
                row.update(process_status=result['process']['status'],
                           solve_ms=result['time']['solve_ms'],
                           tokens=result['metrics']['tokens']['total'],
                           grade_status=result['grade']['status'])
                # The main grader observes any information-register analog pair itself; no supplemental normalizer step.
                if (run/'artifact-manifest.json').exists():
                    row['frozen_artifacts_unchanged'] = tree_manifest(run/'artifacts') == json.loads((run/'artifact-manifest.json').read_text())
            save()
            print('END ' + row['run_id'] + ': ' + row['status'], flush=True)
        state.update(status='completed' if all(r['exit_code'] == 0 for r in state['runs'])
                     else 'completed_with_launcher_errors', finished_at=utc())
        save()
        completed = [ROOT/'.local/runs'/r['run_id'] for r in state['runs']
                     if (ROOT/'.local/runs'/r['run_id']/'artifact-manifest.json').exists()]
        if len(completed) >= 2:
            write_json(campaign/'comparison.json', compare([load_attempt(r) for r in completed]))
        print('CAMPAIGN ' + state['status'], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', required=True)
    execute(parser.parse_args().campaign)


if __name__ == '__main__':
    main()
