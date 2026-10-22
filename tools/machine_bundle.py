#!/usr/bin/env python3
"""Move the stand to another Mac: pack the pinned local inputs here, restore and re-verify them there.

    pack   — on a working machine: one tar.gz with the pinned harness packages, the Codex client, .local/sources and
             the Unica 0.12.3 runtime receipt, plus a sha256 manifest of every file.
    setup  — on the new machine (after cloning the repository): checks prerequisites, unpacks the bundle, verifies every
             harness package against its profile, then re-creates what is machine-specific: the environment passport
             (restore, runtime probe, reset), the check that 1C runs inside the solver sandbox, and the calibration.

Credentials, probes and runs are separate steps, described in docs/new-machine.md.
"""
import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PLATFORM = Path('/opt/1cv8/8.3.27.2074/1cv8')
PYTHON = Path('/opt/homebrew/bin/python3.12')
JAVA = Path('/opt/homebrew/opt/openjdk@21/bin/java')
CLAUDE_VERSION = '2.1.290'
CODEX = '.local/clients/codex-0.162.1/node_modules/@openai/codex-darwin-arm64/vendor/aarch64-apple-darwin/bin/codex'
STARTER_DT = '.local/sources/new_carcass_8_3_25_1445.dt'
ENVIRONMENT = '.local/environment-verified-v1'
# Release downloads and unpacked sources are kept out: the packages themselves are what the profiles pin.
SKIP = {'download', 'downloads', 'source'}
CONTENT = ['.local/sources', '.local/clients/codex-0.162.1', '.local/capabilities']


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def members():
    from exam_bench.harness import PROFILE_FILES
    roots = [ROOT / c for c in CONTENT]
    for name in PROFILE_FILES:
        if name != 'none' and (ROOT / '.local/harnesses' / name).is_dir():
            roots += [p for p in (ROOT / '.local/harnesses' / name).iterdir() if p.name not in SKIP]
    for top in roots:
        paths = [top] if top.is_file() else sorted(p for p in top.rglob('*') if p.is_file() or p.is_symlink())
        for path in paths:
            if path.name == '.DS_Store':
                continue
            yield path


def pack(output):
    output = Path(output).resolve()
    if output.exists():
        raise SystemExit('Bundle exists: %s' % output)
    manifest = {}
    with tarfile.open(output, 'w:gz') as tar:
        for path in members():
            rel = str(path.relative_to(ROOT))
            tar.add(path, arcname=rel, recursive=False)
            if path.is_file() and not path.is_symlink():
                manifest[rel] = sha256(path)
        data = json.dumps({'schema_version': 1, 'created_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                           'source_commit': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
                           'files': manifest}, ensure_ascii=False, indent=1).encode()
        info = tarfile.TarInfo('bundle-manifest.json')
        info.size = len(data)
        import io
        tar.addfile(info, io.BytesIO(data))
    print('Bundle: %s (%d files, %.0f MB)' % (output, len(manifest), output.stat().st_size / 1e6))


def check(label, ok, hint=''):
    print(('  ok   ' if ok else '  FAIL ') + label + ('' if ok or not hint else ' — ' + hint))
    return ok


def prerequisites():
    print('Prerequisites')
    results = [
        check('macOS on Apple silicon', platform.system() == 'Darwin' and platform.machine() == 'arm64'),
        check('Rosetta 2 (the 1C client is x86_64)', subprocess.run(['/usr/bin/arch', '-x86_64', '/usr/bin/true'], capture_output=True).returncode == 0,
              'softwareupdate --install-rosetta --agree-to-license'),
        check('1C:Enterprise 8.3.27.2074 at %s' % PLATFORM, PLATFORM.is_file(), 'install the platform and its license'),
        check('Python 3.12 at %s' % PYTHON, PYTHON.is_file(), 'brew install python@3.12'),
        check('Java 21 at %s' % JAVA, JAVA.is_file(), 'brew install openjdk@21'),
        check('git and gh', bool(shutil.which('git')) and bool(shutil.which('gh')), 'brew install gh'),
    ]
    claude = Path.home() / '.local/bin/claude'
    version = subprocess.run([str(claude), '--version'], capture_output=True, text=True).stdout.strip() if claude.is_file() else ''
    results.append(check('Claude Code %s at %s' % (CLAUDE_VERSION, claude), version.startswith(CLAUDE_VERSION),
                         'curl -fsSL https://claude.ai/install.sh | bash -s %s' % CLAUDE_VERSION))
    return all(results)


def unpack(bundle):
    print('Bundle')
    with tarfile.open(bundle, 'r:gz') as tar:
        manifest = json.loads(tar.extractfile('bundle-manifest.json').read())
        for member in tar.getmembers():
            if member.name == 'bundle-manifest.json':
                continue
            target = (ROOT / member.name).resolve()
            if not str(target).startswith(str(ROOT / '.local') + os.sep):
                raise SystemExit('Bundle member outside .local: ' + member.name)
            if target.exists() or target.is_symlink():
                raise SystemExit('Refusing to overwrite: ' + member.name)
            tar.extract(member, ROOT, filter='tar')
    bad = [rel for rel, digest in manifest['files'].items() if sha256(ROOT / rel) != digest]
    check('%d files unpacked and match the manifest' % len(manifest['files']), not bad, ', '.join(bad[:5]))
    if bad:
        raise SystemExit(1)


def harnesses():
    from exam_bench.harness import PROFILE_FILES, verify_package
    print('Harness packages (against the pinned profiles)')
    ok = True
    for name in PROFILE_FILES:
        if name == 'none':
            continue
        try:
            verify_package(name)
            check(name, True)
        except (ValueError, OSError) as exc:
            ok = check(name, False, str(exc)) and ok
    codex = ROOT / CODEX
    version = subprocess.run([str(codex), '--version'], capture_output=True, text=True).stdout.strip() if codex.is_file() else ''
    return check('Codex CLI 0.162.1', version == 'codex-cli 0.162.1') and ok


def sandbox_platform(environment):
    """1C designer runs inside the solver sandbox with the worker's own cache namespace and no other (preflight gate)."""
    from exam_bench.isolation import wrapped
    from exam_bench.platform import OneC
    cache = Path.home() / '.1cv82/1C/1Cv82'
    cache.mkdir(parents=True, exist_ok=True)
    ws = Path(tempfile.mkdtemp(prefix='1c-exam-sandbox-check-')).resolve()
    (ws / 'tmp').mkdir()
    before = set(cache.iterdir())
    OneC(PLATFORM, ws / 'bootstrap', 120).restore(ws / 'ib', ROOT / STARTER_DT)
    allocated = [str(p.resolve()) for p in set(cache.iterdir()) - before if p.is_dir()]
    (ws / 'platform-cache-grant.json').write_text(json.dumps({'paths': allocated}))
    granted = set(cache.iterdir())
    started = time.monotonic()
    process = subprocess.run(wrapped([str(PLATFORM), 'DESIGNER', '/F', str(ws / 'ib'), '/DumpConfigToFiles', str(ws / 'tmp/dump'),
                                      '/DisableStartupMessages', '/DisableStartupDialogs'], ws),
                             cwd=ws, env={**os.environ, 'TMPDIR': str(ws / 'tmp')}, capture_output=True, timeout=300)
    receipt = {'status': 'completed' if process.returncode == 0 and (ws / 'tmp/dump/Configuration.xml').is_file() else 'failed',
               'exit_code': process.returncode, 'elapsed_ms': round((time.monotonic() - started) * 1000),
               'cache_mapping_unchanged': len(allocated) == 1 and set(cache.iterdir()) == granted,
               'workspace': str(ws), 'checked_by': 'tools/machine_bundle.py setup'}
    (ROOT / environment / 'solver-platform-bootstrap-capability-04.json').write_text(json.dumps(receipt, indent=1))
    return check('1C designer inside the solver sandbox', receipt['status'] == 'completed' and receipt['cache_mapping_unchanged'], json.dumps(receipt))


def environment():
    from exam_bench.platform import prepare_environment, verify_runtime_and_reset
    print('Environment passport (restore, runtime probe, reset)')
    root = ROOT / ENVIRONMENT
    if root.exists():
        return check('%s already exists — kept' % ENVIRONMENT, True)
    prepare_environment(PLATFORM, ROOT / STARTER_DT, root)
    passport = verify_runtime_and_reset(PLATFORM, ROOT / STARTER_DT, root)
    ok = check('passport: runtime and reset verified', bool(passport.get('runtime_probe_verified') and passport.get('reset_verified')), passport.get('state'))
    return sandbox_platform(ENVIRONMENT) and ok


def calibration(name):
    from exam_bench.calibrate import calibrate
    print('Calibration (about 50 minutes)')
    target = ROOT / '.local/calibration' / name
    summary = calibrate(ROOT / ENVIRONMENT / 'src-2', ROOT / STARTER_DT, PLATFORM, target)
    return check('calibration %s accepted' % name, summary['accepted'])


def setup(bundle, calibration_name, skip_calibration):
    if not prerequisites():
        raise SystemExit('Install the missing prerequisites and run setup again.')
    if bundle:
        unpack(bundle)
    if not harnesses():
        raise SystemExit('Harness packages do not match the pinned profiles.')
    if not environment():
        raise SystemExit('The environment is not verified.')
    if not skip_calibration and not calibration(calibration_name):
        raise SystemExit('Calibration rejected.')
    print('Done. Next: credentials and probes, see docs/new-machine.md.')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('pack')
    p.add_argument('--output', required=True)
    s = sub.add_parser('setup')
    s.add_argument('--bundle')
    s.add_argument('--calibration', default='accepted-' + time.strftime('%Y%m%d'))
    s.add_argument('--skip-calibration', action='store_true')
    args = parser.parse_args()
    if args.command == 'pack':
        pack(args.output)
    else:
        setup(args.bundle, args.calibration, args.skip_calibration)


if __name__ == '__main__':
    main()
