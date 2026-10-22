import json
import os
import platform
import subprocess
import tempfile
import unittest
from pathlib import Path
from exam_bench.isolation import verify, grading_profile, grading_environment

ROOT = Path(__file__).parents[1]


@unittest.skipUnless(platform.system() == 'Darwin' and Path('/opt/homebrew/bin/python3.12').exists(), 'macOS worker only')
class SolverIsolationTest(unittest.TestCase):
    def test_curator_files_and_escapes_denied(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td, 'ws'); ws.mkdir()
            result = verify(ws, ROOT/'tasks/1c-platform-official-sample/private/fixtures.json', [ROOT/'exam_bench/grader.py'])
            self.assertTrue(result['secret_0_read_denied'] and result['outside_signal_denied'] and result['exec_denied_open'])

    def test_probe_fails_when_protected_file_is_reachable(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td, 'ws'); ws.mkdir(); leaked = ws/'leaked.json'; leaked.write_text('{}')
            with self.assertRaises(ValueError):
                verify(ws, leaked)


@unittest.skipUnless(platform.system() == 'Darwin', 'macOS worker only')
class GradingIsolationTest(unittest.TestCase):
    def test_graded_code_has_no_network_secrets_or_operator_env(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td, 'case'); (root/'tmp').mkdir(parents=True)
            policy = grading_profile(root, '/bin/sh')
            env = grading_environment(root)
            self.assertNotIn('OPENAI_API_KEY', env); self.assertEqual(set(env) - {'HOME', 'USER', 'LOGNAME'}, {'PATH', 'LANG', 'TMPDIR'})
            script = ('echo ok > "$1/written"; '
                      'cat "$2" >/dev/null 2>&1 && echo private-readable; '
                      '/usr/bin/nc -z -G 2 1.1.1.1 443 >/dev/null 2>&1 && echo network-open; true')
            p = subprocess.run(['/usr/bin/sandbox-exec', '-f', str(policy), '/bin/sh', '-c', script, 'sh', str(root), str(ROOT/'tasks/1c-platform-official-sample/private/rules.json')], env=env, capture_output=True, text=True)
            self.assertEqual(p.stdout.strip(), '')
            self.assertTrue((root/'written').is_file())


if __name__ == '__main__':
    unittest.main()
