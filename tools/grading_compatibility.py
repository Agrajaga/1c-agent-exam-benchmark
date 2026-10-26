"""Narrow, evidence-backed compatibility exceptions for public result display.

Fingerprints stored with each result and owner verification remain untouched. An
exception is directional and tied to exact file hashes; future changes fail closed.
It does not alter calibration or permit replaying a run against a changed grader.
"""

# commit 4a0ad81 changed only claude.normalize's usage counters and missing-data
# reporting. Grader imports preflight, which reads claude.SETTINGS, but never calls
# normalize. No grader code, settings, observations or scoring inputs were changed.
COMPATIBLE_GRADING_INPUTS = {
    'claude.py': {
        ('eedabc75fca0faa434f40a1624b71419ec7dc22e2854a0886cf84b4911db8372',
         '5bae98af6e2021e2718afa3a71ed04bee812deaae31a43d4e7324814139ccc82'),
    },
}


def changed_grading_files(previous, current):
    """Return grading changes which still require reassessment, including missing keys."""
    return sorted(name for name in previous.keys() | current.keys()
                  if previous.get(name) != current.get(name)
                  and (previous.get(name), current.get(name)) not in COMPATIBLE_GRADING_INPUTS.get(name, ()))
