"""Regrade immutable community XML using the operator's calibrated local platform."""
import argparse
import json
import os
import tempfile
from pathlib import Path
from tools.community_results import ROOT, check_id, read, write, validate_bundle, digest, tree_manifest


def recheck(result_id, output, root=ROOT):
    from tools.demo_runner import prerequisites
    from exam_bench.runtime import platform_binary, machine_identity
    from exam_bench.common import grading_fingerprint, utc
    from exam_bench.submission import strip_extras, canonical_ledger, check_bindings
    from exam_bench.gates import check_all, starter_for
    from exam_bench.grader import grade
    from exam_bench.penalties import assess
    cfg, calibration = prerequisites(root, fresh=False)
    folder = root / 'community/results' / check_id(result_id)
    manifest = validate_bundle(folder)
    output = Path(output).resolve()
    if output.exists() or output.is_relative_to((root / 'community').resolve()):
        raise ValueError('Use a new output directory outside original community submissions')
    output.mkdir(parents=True)
    binding, _ = strip_extras(read(folder / 'binding.json'))
    if (folder / 'binding-adapter.json').is_file():
        from tools.supplemental_acceptance import normalize
        projected, _ = normalize(folder / 'src', read(folder / 'binding.json'))
        if projected != read(folder / 'binding-adapter.json'):
            raise ValueError('Normalized binding differs from the metadata-proved projection')
        binding = projected
    binding, _ = canonical_ledger(folder / 'src', binding)
    check_bindings(folder / 'src', binding)
    dt = root / cfg['starter_dt']
    task = root / 'tasks/1c-platform-official-sample'
    with tempfile.TemporaryDirectory(prefix='rc-') as td:
        gates, ticket, allowed = check_all(folder / 'src', binding, dt, platform_binary(), Path(td))
    record = {'schema_version': 1, 'submission_id': result_id, 'created_at': utc(),
              'original_manifest_sha256': digest(folder / 'manifest.json'), 'gates': gates,
              'machine': machine_identity(), 'grading_fingerprint': grading_fingerprint(),
              'calibration_sha256': digest(root / cfg['calibration']), 'may_grade': allowed}
    if allowed:
        g = grade(folder / 'src', binding, dt, platform_binary(), output / 'grade')
        record.update(rules=g['rules'], errors=g['errors'], assessment=assess(g['rules'], folder / 'src', binding,
            read(task / 'checks.json')['requirements'], starter_for(dt), read(task / 'private/official-assessment-mapping.json'),
            read(task / 'private/owner-scoring-policy.json'), gates, g['observations']))
    validate_bundle(folder)
    write(output / 'evaluation.json', record)
    return output / 'evaluation.json'


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('id'); p.add_argument('--output', required=True)
    a = p.parse_args()
    print(recheck(a.id, a.output))
