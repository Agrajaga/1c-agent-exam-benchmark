"""Community result directories are append-only; revised assessments need a new ID."""
import os
import re
import subprocess
from tools.community_results import ROOT, executable


def check(base):
    if not re.fullmatch(r'[0-9a-fA-F]{40,64}', base):
        raise ValueError('A full base commit SHA is required')
    data = subprocess.check_output([executable('git'), 'diff', '--name-status', '-z', '--no-renames', base,
                                    'HEAD', '--', 'community/results'], cwd=ROOT)
    tokens = data.split(b'\0')
    for i in range(0, len(tokens) - 1, 2):
        if tokens[i] != b'A':
            raise ValueError('Existing community results cannot be modified or deleted; submit a new result ID')


if __name__ == '__main__':
    check(os.environ['BASE_SHA'])
