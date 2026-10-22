"""Owner: accept the current grader by replaying an earlier full calibration instead of running a new one.

Checks that the observation code is unchanged, runs one positive variant in 1C on this machine,
replays all stored runs through the current grader and connects the stand to the result. Use it
after a change of the verdict logic; a change of generation or observer code needs a full calibration.

    python tools/replay_calibration.py [.local/calibration/<accepted full calibration>]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def latest_full():
    for path in sorted((ROOT / '.local/calibration').glob('*/summary.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        summary = json.loads(path.read_text(encoding='utf-8'))
        if summary.get('accepted') and summary.get('negatives') and summary.get('mode') not in ('quick', 'replay'):
            return path.parent
    raise SystemExit('No accepted full calibration in .local/calibration')


if __name__ == '__main__':
    from tools.readiness import selection
    from tools.community_setup import setup
    source = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else latest_full()
    pick = selection(ROOT)
    if not pick['platform'] or not pick['isolation_usable']:
        raise SystemExit('Finish the platform and isolation steps on the stand first')
    print('Replaying', source, flush=True)
    setup({'platform': pick['platform']['path'], 'version': pick['platform']['version'], 'isolation': pick['isolation']}, ROOT, source)
    cfg = json.loads((ROOT / '.local/demo/config.json').read_text(encoding='utf-8'))
    print('Stand calibrated:', cfg['calibration'])
