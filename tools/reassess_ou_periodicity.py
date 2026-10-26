"""Reassess OU03/OU08 from the same frozen XML and prior 1C observations.

This narrowly scoped replay requires the newly accepted native periodicity
calibration and an exactly matching historical grader revision. It never runs
the model or 1C; it refuses unrelated changes and does not replace old receipts.
"""
import argparse
import ast
import copy
import hashlib
import json
import types
from pathlib import Path

from exam_bench import ou, penalties
from exam_bench.common import digest, grading_fingerprint, tree_manifest, utc, write_json
from exam_bench.gates import starter_for
from exam_bench.submission import canonical_ledger, check_bindings, strip_extras
from tools.community_results import ROOT, check_id, read, validate_bundle
from tools.grading_compatibility import changed_grading_files
from tools import owner_verification
from tools.reassess_community import git_file, historical_modules

TARGETS = {'OU03', 'OU08'}
ALLOWED_INPUTS = {'ou.py', 'calibrate.py', 'calibration_ou.py', 'calibration_periodicity.py', 'common.py',
                  'smoke_check.py', 'replay_calibration.py', 'tasks/1c-platform-official-sample/checks.json'}


def semantic_symbols(source):
    """Top-level statements other than the two audited functions must be unchanged."""
    parsed = ast.parse(source)
    return [ast.dump(n, include_attributes=False) for n in parsed.body
            if not (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in ('static_signs', 'compare'))]


def check_inputs(root, revision, old, current):
    changed = set(changed_grading_files(old, current))
    if changed - ALLOWED_INPUTS:
        raise ValueError('Unrelated grader changes require a fresh 1C recheck: ' + ', '.join(sorted(changed - ALLOWED_INPUTS)))
    old_ou = git_file(root, revision, 'exam_bench/ou.py').decode('utf-8-sig')
    current_ou = (root / 'exam_bench/ou.py').read_text(encoding='utf-8-sig')
    if semantic_symbols(old_ou) != semantic_symbols(current_ou):
        raise ValueError('OU observer or scenario inputs changed')
    def common_symbols(source):
        return [ast.dump(n, include_attributes=False) for n in ast.parse(source).body
                if not (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'GRADING_FILES' for t in n.targets))]
    old_common = git_file(root, revision, 'exam_bench/common.py').decode('utf-8-sig')
    new_common = (root / 'exam_bench/common.py').read_text(encoding='utf-8-sig')
    if common_symbols(old_common) != common_symbols(new_common):
        raise ValueError('Shared grading helpers changed')
    # The scorer consumes id, section and grader_cases; descriptions may be updated.
    task_path = 'tasks/1c-platform-official-sample/checks.json'
    previous_task = json.loads(git_file(root, revision, task_path))
    current_task = read(root / task_path)
    def requirements(task):
        return [(r['id'], r['section'], r['stand'].get('grader_cases') or []) for r in task['requirements']]
    if requirements(previous_task) != requirements(current_task):
        raise ValueError('Requirement identities or scenarios changed')
    return sorted(changed), old_ou


def historical_ou(source):
    module = types.ModuleType('exam_bench.historical_periodicity_ou')
    module.__package__ = 'exam_bench'
    exec(compile(source, 'historical_periodicity_ou.py', 'exec'), module.__dict__)
    return module


def replace_ou_rules(original, old_ou, source, binding, observations):
    """Replay the historical section exactly before applying the new static signs."""
    if not binding.get('ou'):
        raise ValueError('Operational section is absent: a fresh assessment is required')
    old_ou.check(source, binding['ou'])
    old_rows = old_ou.compare(observations, binding, old_ou.static_signs(source, binding))
    original_by_id = {r['id']: r for r in original}
    if any(original_by_id.get(r['id']) != r for r in old_rows):
        raise ValueError('Previous OU verdicts cannot be reproduced from these observations')
    new_rows = ou.compare(observations, binding, ou.static_signs(source, binding))
    old_map, new_map = ({r['id']: r for r in rows} for rows in (old_rows, new_rows))
    if old_map.keys() != new_map.keys():
        raise ValueError('OU rule set changed')
    changed = {k for k in old_map if old_map[k] != new_map[k]}
    if changed - TARGETS:
        raise ValueError('Unrelated OU rule changed: ' + ', '.join(sorted(changed - TARGETS)))
    return [new_map.get(row['id'], row) for row in original], sorted(changed)


def verify_scope(previous, current):
    """Refuse any assessment change not attributable to the two requirements."""
    encode = lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True)
    old_find = {encode(f): f for f in previous['findings']}
    new_find = {encode(f): f for f in current['findings']}
    diff = [old_find[k] for k in old_find.keys() - new_find.keys()] + [new_find[k] for k in new_find.keys() - old_find.keys()]
    allowed = {'requirement.OU03', 'requirement.OU08'}
    if any(f['penalty_id'] != 'F1C-GEN01' or f['defect_id'] not in allowed for f in diff):
        raise ValueError('An unrelated finding changed')
    statuses = {k for k in previous['statuses'].keys() | current['statuses'].keys()
                if previous['statuses'].get(k) != current['statuses'].get(k)}
    if statuses - {'F1C-GEN01'}:
        raise ValueError('An unrelated coverage status changed: ' + ', '.join(sorted(statuses - {'F1C-GEN01'})))
    old_c = {(c['penalty_id'], c['defect_id'], c['points']) for c in previous['score']['charges']}
    new_c = {(c['penalty_id'], c['defect_id'], c['points']) for c in current['score']['charges']}
    if any(p != 'F1C-GEN01' or d not in allowed for p, d, _ in old_c ^ new_c):
        raise ValueError('An unrelated charge changed')
    if previous['gates'] != current['gates']:
        raise ValueError('Attestation gates changed; a fresh assessment is required')
    return {'changed_findings': len(diff), 'changed_charges': len(old_c ^ new_c)}


def reassess(result_id, prior_path, grade_path, revision, output, *, root=ROOT, server_name='Owner Windows stand',
             verification=None, publish=False, allow_incomplete=False):
    from tools.demo_runner import prerequisites
    from tools.supplemental_acceptance import normalize
    cfg, calibration = prerequisites(root, fresh=False)
    if calibration.get('periodicity_calibration', {}).get('passed') is not True:
        raise ValueError('The native periodicity calibration has not passed')
    folder = root / 'community/results' / check_id(result_id)
    validate_bundle(folder)
    local = (root / '.local').resolve()
    prior_path, grade_path = Path(prior_path).resolve(), Path(grade_path).resolve()
    if not prior_path.is_relative_to(local) or not grade_path.is_relative_to(local):
        raise ValueError('Prior evidence must be in the local workspace')
    prior_digest, grade_digest = digest(prior_path), digest(grade_path)
    previous, grade = read(prior_path), read(grade_path)
    if digest(prior_path) != prior_digest or digest(grade_path) != grade_digest:
        raise ValueError('Prior evidence changed while being read')
    if previous['submission_id'] != result_id or previous['original_manifest_sha256'] != digest(folder / 'manifest.json'):
        raise ValueError('Previous assessment refers to a different submission')
    prior_hash = previous.get('reassessment', {}).get('previous_grade_sha256')
    if prior_hash and prior_hash != grade_digest:
        raise ValueError('Grade observations differ from the previous replay evidence')
    if tree_manifest(folder / 'src') != grade['source_manifest'] or grade['rules'] != previous['rules'] or grade['errors'] != previous['errors']:
        raise ValueError('Source or observations differ from the previous assessment')
    current = grading_fingerprint()
    old_queries, old_penalties = historical_modules(root, revision, previous['grading_fingerprint'])
    changed, source = check_inputs(root, revision, previous['grading_fingerprint'], current)
    old_ou = historical_ou(source)
    binding, _ = strip_extras(read(folder / 'binding.json'))
    if (folder / 'binding-adapter.json').is_file():
        projected, _ = normalize(folder / 'src', read(folder / 'binding.json'))
        if projected != read(folder / 'binding-adapter.json'):
            raise ValueError('Normalized binding differs from the proved projection')
        binding = projected
    binding, _ = canonical_ledger(folder / 'src', binding)
    check_bindings(folder / 'src', binding)
    from exam_bench import queries
    if old_queries.code(folder / 'src') != queries.code(folder / 'src'):
        raise ValueError('Query observer changed')
    new_rules, changed_rules = replace_ou_rules(grade['rules'], old_ou, folder / 'src', binding, grade['observations'])
    task = root / 'tasks/1c-platform-official-sample'
    arguments = (folder / 'src', binding, read(task / 'checks.json')['requirements'], starter_for(root / cfg['starter_dt']),
                 read(task / 'private/official-assessment-mapping.json'), read(task / 'private/owner-scoring-policy.json'),
                 previous['gates'], grade['observations'])
    old_assessment = old_penalties.assess(grade['rules'], *arguments)
    if any(old_assessment[k] != previous['assessment'][k] for k in ('score', 'findings', 'statuses', 'gates')):
        raise ValueError('Previous assessment cannot be reproduced')
    new_assessment = penalties.assess(new_rules, *arguments)
    scope = verify_scope(old_assessment, new_assessment)
    verification = copy.deepcopy(verification or owner_verification.begin(root, cfg, server_name))
    verification.update(started_at=utc(), method='saved_platform_observations', outcome='incomplete' if grade['errors'] else 'complete')
    verification = owner_verification.complete(verification)
    output = Path(output).resolve()
    if output.exists() or not output.is_relative_to(local):
        raise ValueError('Use a new output directory under .local')
    record = {'schema_version': 1, 'submission_id': result_id, 'created_at': verification['completed_at'],
              'original_manifest_sha256': previous['original_manifest_sha256'], 'gates': previous['gates'],
              'machine': previous['machine'], 'grading_fingerprint': current, 'calibration_sha256': digest(root / cfg['calibration']),
              'may_grade': previous['may_grade'], 'rules': new_rules, 'errors': grade['errors'], 'assessment': new_assessment,
              'owner_verification': verification,
              'reassessment': {'method': 'saved_platform_observations', 'reason': 'OU periodicity metadata',
                  'previous_revision': revision, 'previous_evaluation_sha256': prior_digest,
                  'previous_grade_sha256': grade_digest, 'previous_calibration_sha256': previous['calibration_sha256'],
                  'changed_inputs': changed, 'changed_rules': changed_rules, 'verified_scope': scope,
                  'observation_errors': sorted(grade['errors'])}}
    if (tree_manifest(folder / 'src') != grade['source_manifest'] or grading_fingerprint() != current
            or digest(prior_path) != prior_digest or digest(grade_path) != grade_digest):
        raise ValueError('Source, prior evidence or grader changed during reassessment')
    validate_bundle(folder)
    write_json(output / 'evaluation.json', record)
    if publish:
        owner_verification.publish(record, folder, root, allow_incomplete=allow_incomplete)
    return output / 'evaluation.json'


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('id'); p.add_argument('--prior', required=True); p.add_argument('--grade', required=True)
    p.add_argument('--revision', required=True); p.add_argument('--output', required=True)
    p.add_argument('--server-name', default='Owner Windows stand'); p.add_argument('--publish', action='store_true')
    p.add_argument('--allow-incomplete', action='store_true')
    a = p.parse_args()
    print(reassess(a.id, a.prior, a.grade, a.revision, a.output, server_name=a.server_name,
                   publish=a.publish, allow_incomplete=a.allow_incomplete))
