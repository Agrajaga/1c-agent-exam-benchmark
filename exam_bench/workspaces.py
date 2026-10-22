"""Short Windows case paths with durable evidence outside the temporary tree."""
import contextlib
import os
import shutil
import tempfile
import zipfile
from pathlib import Path


@contextlib.contextmanager
def case_workspace(evidence):
    evidence=Path(evidence).resolve()
    if os.name!='nt':
        yield evidence
        return
    temporary=tempfile.TemporaryDirectory(prefix='eb-')
    work=Path(temporary.name).resolve()
    # Explicitly check the deletion target before TemporaryDirectory cleans it.
    if work.parent!=Path(tempfile.gettempdir()).resolve() or not work.name.startswith('eb-'):
        raise ValueError('Unexpected case workspace location')
    try:
        yield work
    finally:
        evidence.mkdir(parents=True,exist_ok=True)
        for path in work.iterdir():
            if path.name=='ib':
                continue  # disposable database; recreate from the pinned DT
            if path.name=='observed-src':
                with zipfile.ZipFile(evidence/'observed-src.zip','w',zipfile.ZIP_DEFLATED) as archive:
                    for source in sorted(path.rglob('*')):
                        if source.is_file():archive.write(source,source.relative_to(path).as_posix())
            elif path.is_dir():
                shutil.copytree(path,evidence/path.name)
            else:
                shutil.copyfile(path,evidence/path.name)
        temporary.cleanup()
