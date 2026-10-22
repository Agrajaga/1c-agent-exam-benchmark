import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def utc():
    return datetime.now(timezone.utc).isoformat()


def tree_manifest(root):
    root = Path(root)
    def link(path):
        return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)
    if link(root):
        raise ValueError('Symlink/reparse root refused: '+str(root))
    result = {}
    for path in sorted(root.rglob('*')):
        if link(path):
            raise ValueError(f'Symlink refused: {path.relative_to(root)}')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = digest(path)
    return result


GRADING_FILES = ('grader.py', 'observer.py', 'platform.py', 'submission.py',
                 'common.py', 'process.py', 'windows_job.py', 'workspaces.py', 'runtime.py', 'isolation.py', 'gates.py', 'ou.py','pr.py','forms.py','interface.py', 'calibration.py', 'calibration_ou.py','calibration_pr.py','calibration_forms.py','calibration_interface.py', 'calibrate.py', 'replay_calibration.py', 'smoke_check.py')


def grading_fingerprint():
    root = Path(__file__).parent
    return {name: digest(root / name) for name in GRADING_FILES}
