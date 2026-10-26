"""Reassess a frozen community submission using its verified prior 1C observations.

This is narrowly scoped to the table-parameter query fix. It refuses replay if
scenario-generating code changed, the original score cannot be reproduced, or
the stored XML/grade no longer matches. It never invokes a model or 1C.
"""
import argparse
import copy
import hashlib
import json
import subprocess
import types
from pathlib import Path

from exam_bench import penalties, queries
from exam_bench.common import digest, grading_fingerprint, tree_manifest, utc, write_json
from exam_bench.gates import starter_for
from exam_bench.submission import canonical_ledger, check_bindings, strip_extras
from tools.community_results import ROOT, check_id, read, validate_bundle
from tools import owner_verification

# Scenario/observer code and all other policy inputs must remain identical.
ALLOWED_CHANGES = {'queries.py', 'penalties.py', 'common.py', 'calibrate.py', 'calibration_query.py',
                   'smoke_check.py', 'replay_calibration.py', 'rules/1c-specialist-platform/rules.json'}


def check_input_changes(old, current):
    changed = {k for k in old.keys() | current.keys() if old.get(k) != current.get(k)}
    unexpected = changed - ALLOWED_CHANGES
    if unexpected:
        raise ValueError('Scenario or other grading inputs changed: ' + ', '.join(sorted(unexpected)))
    return sorted(changed)


def git_file(root, revision, path):
    p = subprocess.run(['git', 'show', revision + ':' + path], cwd=root, capture_output=True, check=True)
    return p.stdout


def historical_modules(root, revision, fingerprint):
    for name, expected in fingerprint.items():
        path = 'exam_bench/' + name if '/' not in name else name
        raw = git_file(root, revision, path)
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('Historical revision does not match previous grading input: ' + name)
    def load(name):
        module = types.ModuleType('exam_bench.historical_' + name)
        module.__package__ = 'exam_bench'
        source = git_file(root, revision, 'exam_bench/' + name + '.py')
        exec(compile(source, 'historical_' + name + '.py', 'exec'), module.__dict__)
        return module
    old_queries, old_penalties = load('queries'), load('penalties')
    old_penalties.queries = old_queries
    return old_queries, old_penalties


def verify_scope(previous, current, source, observations):
    """Replay only the specifically established query-parameter change."""
    checked, _ = queries.verdicts(source, observations.get(queries.CASE))
    unresolved = {'code.query.%s:%d' % (q['file'], q['line']) for q in checked
                  if q['status'] == 'unresolved_parameter_schema'}
    encode = lambda f: json.dumps(f, ensure_ascii=False, sort_keys=True)
    old = {encode(f): f for f in previous['findings']}
    new = {encode(f): f for f in current['findings']}
    if new.keys() - old.keys():
        raise ValueError('Replay introduced findings outside the table-parameter fix')
    removed = [old[k] for k in old.keys() - new.keys()]
    if any(f['penalty_id'] != 'F1C-GEN12' or f['defect_id'] not in unresolved for f in removed):
        raise ValueError('Replay removed a finding outside the table-parameter fix')
    changed_status = {k for k in previous['statuses'].keys() | current['statuses'].keys()
                      if previous['statuses'].get(k) != current['statuses'].get(k)}
    if changed_status - {'F1C-GEN12'}:
        raise ValueError('Replay changed unrelated coverage statuses')
    old_charges = {(c['penalty_id'], c['defect_id'], c['points']) for c in previous['score']['charges']}
    new_charges = {(c['penalty_id'], c['defect_id'], c['points']) for c in current['score']['charges']}
    if new_charges - old_charges or any(p != 'F1C-GEN12' or d not in unresolved for p, d, _ in old_charges - new_charges):
        raise ValueError('Replay changed unrelated charges')
    return {'removed_findings': len(removed), 'removed_charges': len(old_charges - new_charges)}


def reassess(result_id, prior_path, revision, output, *, root=ROOT, server_name='Owner Windows stand',
             verification=None, publish=False, allow_incomplete=False, historical=None):
    from tools.demo_runner import prerequisites
    from tools.supplemental_acceptance import normalize
    cfg, calibration = prerequisites(root, fresh=False)
    if not calibration.get('query_parameter_calibration', {}).get('passed'):
        raise ValueError('The new table-parameter calibration has not passed')
    folder = root / 'community/results' / check_id(result_id)
    validate_bundle(folder)
    prior_path = Path(prior_path).resolve()
    if not prior_path.is_relative_to((root / '.local').resolve()):
        raise ValueError('Prior evaluation must be in the local workspace')
    previous = read(prior_path)
    if previous['submission_id'] != result_id or previous['original_manifest_sha256'] != digest(folder / 'manifest.json'):
        raise ValueError('Previous assessment refers to a different frozen submission')
    grade_path = prior_path.parent / 'grade/grade.json'
    grade = read(grade_path)
    if tree_manifest(folder / 'src') != grade['source_manifest']:
        raise ValueError('Frozen source differs from the observed source')
    if grade['rules'] != previous['rules'] or grade['errors'] != previous['errors']:
        raise ValueError('Stored observations do not match the previous assessment')
    current = grading_fingerprint()
    changed = check_input_changes(previous['grading_fingerprint'], current)
    old_queries, old_penalties = historical or historical_modules(root, revision, previous['grading_fingerprint'])
    if old_queries.code(folder / 'src') != queries.code(folder / 'src'):
        raise ValueError('The query observer changed; a fresh 1C run is required')
    binding, _ = strip_extras(read(folder / 'binding.json'))
    if (folder / 'binding-adapter.json').is_file():
        projected, _ = normalize(folder / 'src', read(folder / 'binding.json'))
        if projected != read(folder / 'binding-adapter.json'):
            raise ValueError('Normalized binding differs from the proved projection')
        binding = projected
    binding, _ = canonical_ledger(folder / 'src', binding)
    check_bindings(folder / 'src', binding)
    task = root / 'tasks/1c-platform-official-sample'
    arguments = (grade['rules'], folder / 'src', binding, read(task / 'checks.json')['requirements'],
                 starter_for(root / cfg['starter_dt']), read(task / 'private/official-assessment-mapping.json'),
                 read(task / 'private/owner-scoring-policy.json'), previous['gates'], grade['observations'])
    historical_result = old_penalties.assess(*arguments)
    if (historical_result['score'] != previous['assessment']['score'] or
            historical_result['findings'] != previous['assessment']['findings'] or
            historical_result['statuses'] != previous['assessment']['statuses']):
        raise ValueError('The previous assessment cannot be reproduced from these observations')
    new_assessment = penalties.assess(*arguments)
    scope = verify_scope(historical_result, new_assessment, folder / 'src', grade['observations'])
    verification = copy.deepcopy(verification or owner_verification.begin(root, cfg, server_name))
    verification['started_at'] = utc()
    verification['method'] = 'saved_platform_observations'
    verification['outcome'] = 'incomplete' if grade['errors'] else 'complete'
    verification = owner_verification.complete(verification)
    output = Path(output).resolve()
    if output.exists() or output.is_relative_to((root / 'community').resolve()):
        raise ValueError('Use a new output directory outside community submissions')
    record = {'schema_version': 1, 'submission_id': result_id, 'created_at': verification['completed_at'],
              'original_manifest_sha256': previous['original_manifest_sha256'], 'gates': previous['gates'],
              'machine': previous['machine'], 'grading_fingerprint': current,
              'calibration_sha256': digest(root / cfg['calibration']), 'may_grade': previous['may_grade'],
              'rules': grade['rules'], 'errors': grade['errors'], 'assessment': new_assessment,
              'owner_verification': verification,
              'reassessment': {'method': 'saved_platform_observations', 'previous_revision': revision,
                  'previous_evaluation_sha256': digest(prior_path), 'previous_grade_sha256': digest(grade_path),
                  'previous_calibration_sha256': previous['calibration_sha256'],
                  'previous_platform_version': previous['machine']['platform_version'],
                  'query_observer_sha256': hashlib.sha256(queries.code(folder / 'src').encode('utf-8')).hexdigest(),
                  'calibration_sha256': digest(root / cfg['calibration']), 'changed_inputs': changed,
                  'observation_errors': sorted(grade['errors']), 'verified_scope': scope}}
    if tree_manifest(folder / 'src') != grade['source_manifest'] or grading_fingerprint() != current:
        raise ValueError('Source or grader changed during reassessment')
    validate_bundle(folder)
    write_json(output / 'evaluation.json', record)
    if publish:
        owner_verification.publish(record, folder, root, allow_incomplete=allow_incomplete)
    return output / 'evaluation.json'


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('id')
    p.add_argument('--prior', required=True)
    p.add_argument('--revision', required=True, help='Git revision matching all prior grading input hashes')
    p.add_argument('--output', required=True)
    p.add_argument('--server-name', default='Owner Windows stand')
    p.add_argument('--publish', action='store_true')
    p.add_argument('--allow-incomplete', action='store_true')
    a = p.parse_args()
    print(reassess(a.id, a.prior, a.revision, a.output, server_name=a.server_name,
                   publish=a.publish, allow_incomplete=a.allow_incomplete))
