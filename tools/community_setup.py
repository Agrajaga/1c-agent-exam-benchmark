"""First-run setup using installed 1C and Codex. No redistributable platform or account data."""
import os
import shutil
import sys
from pathlib import Path
from tools.community_results import ROOT, read, write, digest, tree_manifest


def validate_request(data):
    if set(data) != {'platform', 'version', 'isolation'}:
        raise ValueError('Fill all setup fields')
    for key in ('platform',):
        if not isinstance(data[key], str) or not Path(data[key]).is_file():
            raise ValueError('Executable file missing: ' + key)
    if not isinstance(data['version'], str) or not __import__('re').fullmatch(r'8\.\d+\.\d+\.\d+', data['version']):
        raise ValueError('Use the complete 1C version, e.g. 8.3.27.2342')
    if data['isolation'] not in ('dedicated-host', 'macos', 'bubblewrap'):
        raise ValueError('Select an execution environment')
    return data


def setup(data, root=ROOT, replay_source=None):
    """replay_source: an accepted full calibration to replay instead of quick/full calibration (owner only)."""
    from datetime import datetime, timezone
    from exam_bench.platform import OneC
    from exam_bench.runtime import machine_identity
    data = validate_request(data)
    machine = root / '.local/community/machine.json'
    settings = {'platform_binary': str(Path(data['platform']).resolve()), 'platform_version': data['version'], 'isolation': data['isolation']}
    write(machine, settings)
    os.environ['EXAM_BENCH_CONFIG'] = str(machine)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    work = root / '.local/community/setup' / stamp
    work.mkdir(parents=True)
    starter = root / 'starters/carcass-8.3.25.1445/new_carcass_8_3_25_1445.dt'
    onec = OneC(data['platform'], work / 'platform', 600)
    # Short native path on Windows; retain only exported XML, not the temporary database.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='cs-') as td:
        ib = Path(td) / 'ib'
        onec.restore(ib, starter)
        onec.export(ib, Path(td) / 'src')
        shutil.copytree(Path(td) / 'src', work / 'starter-src')
    if replay_source:
        from exam_bench.replay_calibration import replay_calibrate
        target = work / 'replay-calibration'
        summary = replay_calibrate(replay_source, work / 'starter-src', starter, data['platform'], target)
        if not summary['accepted']:
            raise ValueError('Replay not accepted: %s; run the full calibration' % summary.get('reason'))
    else:
        # Rules are calibrated centrally by the owner; here only prove the grader works on this machine.
        from exam_bench.smoke_check import smoke_check
        target = work / 'smoke-check'
        summary = smoke_check(work / 'starter-src', starter, data['platform'], target)
        if not summary['accepted']:
            raise ValueError('Проверка грейдера не прошла: %s' % summary.get('reason'))
    manifest = work / 'starter-manifest.json'
    write(manifest, tree_manifest(work / 'starter-src'))
    relative = lambda p: p.relative_to(root).as_posix()
    cfg = {'machine_config': relative(machine), 'calibration': relative(target / 'summary.json'),
           'starter_source': relative(work / 'starter-src'), 'starter_source_manifest': relative(manifest),
           'starter_dt': relative(starter), 'starter_dt_sha256': digest(starter),
           'model': 'gpt-6.1-sol', 'platform_version': data['version'], 'timeout_seconds': 1800,
           'baseline_run_id': '', 'baseline_evaluation': '.local/community/no-baseline.json'}
    write(root / '.local/demo/config.json', cfg)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True, help='JSON with fields from the website setup form')
    setup(read(parser.parse_args().request))
