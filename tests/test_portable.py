import contextlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from exam_bench.common import tree_manifest
from exam_bench.process import supervise
from exam_bench.runtime import child_environment, settings, require_execution_mode


@contextlib.contextmanager
def machine(data):
    with tempfile.TemporaryDirectory() as td:
        config = Path(td)/'machine.json'
        config.write_text(json.dumps(data), encoding='utf-8')
        with patch.dict(os.environ, {'EXAM_BENCH_CONFIG': str(config)}):
            yield


class PortableSettings(unittest.TestCase):
    def test_material_hashes_do_not_depend_on_python_utf8_mode(self):
        code=('from pathlib import Path;from exam_bench.materials import delivery_metadata;'
              'print(delivery_metadata(Path("tasks/1c-platform-official-sample"))["input_revision"])')
        result=subprocess.run([sys.executable,'-X','utf8=0','-c',code],capture_output=True,text=True,check=True)
        self.assertEqual(result.stdout.strip(),'open-methodics-v5')

    def test_missing_sandbox_never_falls_back_silently(self):
        with machine({'isolation': 'required'}):
            with self.assertRaisesRegex(ValueError, 'No outer sandbox'):
                require_execution_mode()

    def test_explicit_host_mode_does_not_claim_isolation(self):
        from exam_bench.isolation import verify, wrapped
        with machine({'isolation': 'dedicated-host'}), tempfile.TemporaryDirectory() as td:
            self.assertFalse(verify(td, Path(td)/'private')['verified'])
            self.assertEqual(wrapped([sys.executable, '-V'], td), [str(Path(sys.executable).resolve()), '-V'])

    def test_unknown_setting_is_an_error(self):
        with machine({'isolaton': 'dedicated-host'}):
            with self.assertRaisesRegex(ValueError, 'Unknown'):
                settings()

    def test_worker_environment_retains_windows_prerequisites_and_omits_secrets(self):
        with patch.dict(os.environ, {'SystemRoot': 'C:/Windows', 'ProgramData': 'C:/ProgramData', 'ALLUSERSPROFILE': 'C:/ProgramData', 'COMPUTERNAME': 'BENCH-HOST', 'PROCESSOR_ARCHITECTURE': 'AMD64', 'OPENAI_API_KEY': 'private', 'GH_TOKEN': 'private', 'CUSTOM_SECRET': 'private'}):
            env = child_environment(Path('worker'))
        self.assertEqual(env['SystemRoot'], 'C:/Windows')
        self.assertEqual(env['ProgramData'], 'C:/ProgramData')
        self.assertEqual(env['ALLUSERSPROFILE'], 'C:/ProgramData')
        self.assertEqual(env['COMPUTERNAME'], 'BENCH-HOST')
        self.assertEqual(env['PROCESSOR_ARCHITECTURE'], 'AMD64')
        self.assertNotIn('OPENAI_API_KEY', env)
        self.assertNotIn('GH_TOKEN', env)
        self.assertNotIn('CUSTOM_SECRET', env)
        self.assertEqual(env['TEMP'], str(Path('worker/tmp')))

    def test_manifest_uses_portable_names_and_preserves_exact_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root/'a').mkdir(); (root/'a/file.txt').write_bytes(b'a\r\nb\r\n')
            import hashlib
            self.assertEqual(tree_manifest(root), {'a/file.txt': hashlib.sha256(b'a\r\nb\r\n').hexdigest()})

    def test_bubblewrap_has_private_pid_namespace_and_grader_network(self):
        from exam_bench.isolation import linux_wrapped
        with machine({'isolation': 'bubblewrap'}), tempfile.TemporaryDirectory() as td, patch('shutil.which', return_value='/usr/bin/bwrap'):
            args = linux_wrapped([sys.executable, '-V'], td, grading=True)
            self.assertIn('--unshare-net', args)
            self.assertIn('--unshare-pid', args)
            self.assertIn('--die-with-parent', args)
            self.assertNotIn(str(Path.home()), args)


class PortableProcess(unittest.TestCase):
    def run_client(self, code, prompt='', timeout=5):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = supervise([sys.executable, '-c', code], root, dict(os.environ), prompt, timeout, .2, root/'raw')
            return result, (root/'raw/stdout.jsonl').read_bytes(), (root/'raw/stderr.log').read_bytes()

    def test_large_interleaved_stdout_stderr_are_not_truncated(self):
        result, out, err = self.run_client('import os;[(os.write(1,b"x"*8192),os.write(2,b"y"*8192)) for _ in range(64)]')
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(out, b'x'*(8192*64)); self.assertEqual(err, b'y'*(8192*64))

    def test_blocked_stdin_cannot_bypass_timeout(self):
        result, _, _ = self.run_client('import time;time.sleep(30)', 'x'*2_000_000, timeout=.5)
        self.assertEqual(result['status'], 'timeout')
        self.assertTrue(result['stop_confirmed'])
        self.assertLess(result['elapsed_ms'], 5000)

    def test_unicode_prompt_and_output(self):
        result, out, _ = self.run_client('import sys;sys.stdout.buffer.write(sys.stdin.buffer.read())', 'Проверка 1С')
        self.assertEqual(out, 'Проверка 1С'.encode('utf-8'))
        self.assertTrue(result['stop_confirmed'])


class PortableCodex(unittest.TestCase):
    def test_failure_and_success_remove_credentials_and_freeze_artifacts(self):
        from exam_bench.codex import start
        for code, expected in [('import pathlib;pathlib.Path("out/probe.txt").write_bytes(b"READY")', 'completed'),
                               ('import time;time.sleep(30)', 'timeout')]:
            with self.subTest(expected=expected), machine({'isolation':'dedicated-host'}), tempfile.TemporaryDirectory() as td:
                root = Path(td); run = root/'run'; run.mkdir(); ws=root/'ws'
                (ws/'out').mkdir(parents=True); (ws/'client-home').mkdir()
                (ws/'client-home/auth.json').write_text('test-only')
                plan = {'run_id':'portable-test','harness':'none','model':'gpt-test',
                        'input_revision':'test','billing_channel':'subscription',
                        'solve_timeout_seconds':.5,'stop_grace_seconds':.2}
                prepared = (ws, [sys.executable,'-c',code], dict(os.environ), {})
                with patch('exam_bench.codex.prepare', return_value=prepared):
                    result=start(plan,run,root/'starter',root/'task',sys.executable,root/'auth',prompt='test')
                self.assertEqual(result['process']['status'],expected)
                self.assertFalse((ws/'client-home/auth.json').exists())
                self.assertTrue((run/'artifact-manifest.json').is_file())
                self.assertFalse(result['comparison_eligible'])
                self.assertFalse(result['isolation_verified'])


class PortableSite(unittest.TestCase):
    def test_catalogue_build_needs_no_campaign_or_passport(self):
        from tools.build_result_site import ROOT, build
        data = build(catalogue_only=True)
        self.assertTrue(data['tasks']); self.assertEqual(data['runs'], [])
        self.assertIsNone(data['campaign']); self.assertFalse(data['ranking_ready'])
        self.assertTrue((ROOT/'site/dist/index.html').is_file())


if __name__ == '__main__':
    unittest.main()
