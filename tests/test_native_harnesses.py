import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from exam_bench import portable_harnesses as native
from exam_bench.common import digest, tree_manifest, write_json


class NativeHarness(unittest.TestCase):
    def test_unprobed_package_and_changed_registration_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); package = root / '.local/harnesses/test/package'; package.mkdir(parents=True)
            (package / 'tool.exe').write_bytes(b'fixture')
            value = {'version': 'test', 'command': '{package}/tool.exe'}
            write_json(root / '.local/harnesses/portable.json', {'test': value})
            manifest = package.parent / 'package-manifest.json'; write_json(manifest, tree_manifest(package))
            profile = root / 'profiles/test-portable.json'
            write_json(profile, {'configuration': value, 'package_manifest_sha256': digest(manifest)})
            with patch.object(native, 'ROOT', root):
                with self.assertRaises(FileNotFoundError):
                    native.verify('test')
                write_json(package.parent / 'capability.json', {'accepted': True, 'profile_sha256': digest(profile)})
                self.assertEqual(native.verify('test'), package.parent)
                write_json(root / '.local/harnesses/portable.json', {'test': {**value, 'command': 'different.exe'}})
                with self.assertRaisesRegex(ValueError, 'registration'):
                    native.verify('test')

    def test_installation_sealed_before_the_move_adopts_its_tracked_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); package = root / '.local/harnesses/test/package'; package.mkdir(parents=True)
            (package / 'tool.exe').write_bytes(b'fixture')
            value = {'version': 'test', 'command': '{package}/tool.exe'}
            write_json(root / '.local/harnesses/portable.json', {'test': value})
            manifest = package.parent / 'package-manifest.json'; write_json(manifest, tree_manifest(package))
            tracked = root / 'profiles/test-portable.json'
            write_json(tracked, {'configuration': value, 'package_manifest_sha256': digest(manifest)})
            local = native.profile('test', root)
            self.assertEqual(local, package.parent / 'profile.json')
            self.assertEqual(digest(local), digest(tracked))  # receipts made against the tracked file stay valid
            write_json(tracked, {'configuration': value, 'package_manifest_sha256': 'another machine'})
            other = Path(temporary) / 'other'; (other / '.local/harnesses/test').mkdir(parents=True)
            self.assertFalse(native.profile('test', other).exists())  # a foreign seal is never adopted

    def test_codex_receives_mcp_even_with_user_config_ignored(self):
        value = {'server': 'example', 'command': '{package}/tool.exe', 'args': ['mcp'], 'env': {'OPENAI_API_KEY': ''}}
        with patch.object(native, 'entry', return_value=value), patch('exam_bench.runtime.platform_binary', return_value=None):
            argv = native.codex_overrides({'name': 'test', 'package_path': '/worker/harness'}, Path('/worker'), Path('/worker/client-home'))
        self.assertTrue(any(x.startswith('mcp_servers.example.command=') for x in argv))
        self.assertIn('mcp_servers.example.args=["mcp"]', argv)
        self.assertIn('mcp_servers.example.env.OPENAI_API_KEY=""', argv)

    def test_daemon_launcher_exit_does_not_end_child_readiness_check(self):
        if native.os.name != 'nt':
            self.skipTest('Windows Job Object launcher regression')
        with tempfile.TemporaryDirectory() as temporary:
            ws = Path(temporary); run = ws / 'run'; run.mkdir()
            write_json(run / 'portable-harness.json', {'name': 'code-index-1.9.0', 'package_path': str(ws)})
            process = Mock(); process.poll.return_value = 0
            job = Mock(); job.active.return_value = True
            response = Mock(stdout=json.dumps({'paths': [{'status': 'ready'}]}).encode())
            with patch.object(native, 'spec', return_value=('indexer.exe', [], {})), \
                 patch.object(native.subprocess, 'Popen', return_value=process), \
                 patch.object(native.subprocess, 'run', return_value=response) as status, \
                 patch('exam_bench.windows_job.Job', return_value=job):
                try:
                    native.launch(ws, {}, run)
                    status.assert_called_once()
                    self.assertTrue((run / 'code-index-ready.json').is_file())
                finally:
                    native._daemons.pop(str(ws), None)
