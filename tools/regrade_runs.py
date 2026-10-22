#!/usr/bin/env python3
"""Re-evaluate frozen submissions with the current calibrated grader.

The original result.json and grade/ stay untouched: each re-evaluation is a new
evaluation directory that references the frozen artifact and the calibration used.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from exam_bench.common import digest, tree_manifest, utc, write_json, grading_fingerprint
from exam_bench.grader import grade, PROFILE
from exam_bench.gates import check_all, starter_for
from exam_bench.penalties import assess
from exam_bench.preflight import verify_calibration
from exam_bench.submission import canonical_ledger, check_bindings, extra_sections, UnsupportedBindings


def main():
    p = argparse.ArgumentParser()
    p.add_argument('run_ids', nargs='+')
    p.add_argument('--evaluation-id', required=True, help='new directory name under .local/assessments/<run>/')
    p.add_argument('--calibration', required=True)
    p.add_argument('--starter-dt', required=True)
    p.add_argument('--binary', default='/opt/1cv8/8.3.27.2074/1cv8')
    args = p.parse_args()
    verify_calibration(json.loads(Path(args.calibration).read_text()))
    summary = {}
    for run_id in args.run_ids:
        run = ROOT/'.local/runs'/run_id
        target = ROOT/'.local/assessments'/run_id/args.evaluation_id
        if target.exists():
            raise SystemExit('Evaluation already exists: '+str(target))
        manifest = json.loads((run/'artifact-manifest.json').read_text())
        if tree_manifest(run/'artifacts') != manifest:
            raise SystemExit('Frozen artifact changed: '+run_id)
        previous = json.loads((run/'result.json').read_text())['grade']
        ready = run/'artifacts/submission.ready.json'
        try:
            signalled = json.loads(ready.read_text()).get('status') == 'ready'
        except (OSError, ValueError):
            signalled = False
        if not signalled or not (run/'artifacts/binding.json').is_file():
            # An interrupted attempt (no readiness signal or no binding) is not re-evaluated, as at solve time.
            record = {'schema_version': 1, 'run_id': run_id, 'evaluation_id': args.evaluation_id, 'created_at': utc(), 'profile': PROFILE['id'],
                      'grading_fingerprint': grading_fingerprint(), 'calibration_ref': args.calibration, 'calibration_sha256': digest(args.calibration),
                      'artifact_manifest_sha256': digest(run/'artifact-manifest.json'), 'previous_grade_status': previous.get('status'),
                      'whole_ticket': 'not_evaluated', 'status': 'invalid_submission', 'reason': 'No readiness signal' if not signalled else 'No frozen binding.json', 'rules': []}
            write_json(target/'evaluation.json', record)
            summary[run_id] = {'previous': record['previous_grade_status'], 'now': record['status'], 'rules': {}, 'errors': []}
            print(run_id, json.dumps(summary[run_id], ensure_ascii=False), flush=True)
            continue
        binding = json.loads((run/'artifacts/binding.json').read_text())
        record = {'schema_version': 1, 'run_id': run_id, 'evaluation_id': args.evaluation_id, 'created_at': utc(),
                  'profile': PROFILE['id'], 'grading_fingerprint': grading_fingerprint(),
                  'calibration_ref': args.calibration, 'calibration_sha256': digest(args.calibration),
                  'artifact_manifest_sha256': digest(run/'artifact-manifest.json'),
                  'previous_grade_status': previous.get('status'), 'whole_ticket': 'not_evaluated',
                  'ignored_binding_sections': extra_sections(binding)}
        # The same normalization the calibrated grader applies before its own binding check.
        binding, expanded = canonical_ledger(run/'artifacts/src', binding)
        record['expanded_binding_names'] = expanded
        try:
            check_bindings(run/'artifacts/src', binding)
        except UnsupportedBindings as exc:
            record.update(status='adapter_inconclusive', reason=str(exc), rules=[])
        except ValueError as exc:
            record.update(status='invalid_submission', reason=str(exc), rules=[])
        else:
            gates, ticket_verdict, may_grade = check_all(run/'artifacts/src', binding, args.starter_dt, args.binary, target/'gates')
            record['gates'] = gates
            if not may_grade:
                record.update(status=ticket_verdict['reason'] if ticket_verdict else 'infrastructure_error', rules=[],
                              whole_ticket=ticket_verdict['verdict'] if ticket_verdict else 'not_evaluated', ticket_verdict=ticket_verdict)
                write_json(target/'evaluation.json', record)
                summary[run_id] = {'previous': record['previous_grade_status'], 'now': record['status'], 'rules': {}, 'errors': []}
                print(run_id, json.dumps(summary[run_id], ensure_ascii=False), flush=True)
                continue
            g = grade(run/'artifacts/src', binding, args.starter_dt, args.binary, target/'grade')
            autofilled = sorted({x for o in g['observations'].values() for x in o.get('autofilled') or []})
            record.update(status=g['status'], rules=g['rules'], errors=g['errors'], autofilled_fixture_attributes=autofilled,
                          evidence_ref='grade/grade.json')
            task = ROOT/'tasks/1c-platform-official-sample'
            record['assessment'] = assess(g['rules'], run/'artifacts/src', binding,
                                          json.loads((task/'checks.json').read_text())['requirements'],
                                          starter_for(args.starter_dt),
                                          json.loads((task/'private/official-assessment-mapping.json').read_text()),
                                          json.loads((task/'private/owner-scoring-policy.json').read_text()),
                                          gates, g['observations'])
        write_json(target/'evaluation.json', record)
        summary[run_id] = {'previous': record['previous_grade_status'], 'now': record['status'],
                           'rules': {r['id']: r['verdict'] for r in record['rules']}, 'errors': list(record.get('errors', {}))}
        print(run_id, json.dumps(summary[run_id], ensure_ascii=False), flush=True)
    return summary


if __name__ == '__main__':
    main()
