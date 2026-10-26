import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from exam_bench import codex, portable_harnesses as native
from exam_bench.common import digest, tree_manifest, write_json
from exam_bench.materials import delivery_metadata


TASK = Path(__file__).resolve().parents[1] / 'tasks/1c-platform-official-sample'


class CodexMcpStartup(unittest.TestCase):
    def test_selected_mcp_is_required_even_when_user_config_is_ignored(self):
        self.check_preparation('bsl-analyzer-0.3.2', {'bsl-analyzer': True})

    def test_no_harness_does_not_register_or_require_an_mcp_server(self):
        self.check_preparation('none', {})

    def check_preparation(self, name, expected):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            starter = root / 'starter'; starter.mkdir()
            (starter / 'Configuration.xml').write_text('<fixture/>', encoding='utf-8')
            auth = root / 'dummy-auth.json'; auth.write_text('{}', encoding='utf-8')
            machine = root / 'machine.json'; write_json(machine, {'isolation': 'dedicated-host'})
            if name != 'none':
                package = root / '.local/harnesses' / name / 'package'; package.mkdir(parents=True)
                (package / 'fixture.txt').write_text('fixture', encoding='utf-8')
                config = {'version': 'fixture', 'server': 'bsl-analyzer', 'command': sys.executable,
                          'args': [], 'registration': 'test-only package; never launched'}
                write_json(root / '.local/harnesses/portable.json', {name: config})
                manifest = package.parent / 'package-manifest.json'; write_json(manifest, tree_manifest(package))
                profile = package.parent / 'profile.json'
                write_json(profile, {'configuration': config, 'package_manifest_sha256': digest(manifest),
                                     'memory': False, 'extensions': False, 'delegation': 'disabled'})
                write_json(package.parent / 'capability.json', {'accepted': True, 'profile_sha256': digest(profile)})
            plan = {'schema_version': 1, 'run_id': 'mcp-startup-test', 'client_version': 'fixture',
                    'model': 'gpt-test', 'billing_channel': 'subscription', 'harness': name,
                    'solve_timeout_seconds': 60, 'stop_grace_seconds': 3,
                    'purpose': 'mcp_startup_test', 'acceptance_profile': 'not_applicable_probe',
                    **delivery_metadata(TASK), 'public_inputs': tree_manifest(TASK / 'public')}
            with patch.object(native, 'ROOT', root), patch.dict(os.environ, {'EXAM_BENCH_CONFIG': str(machine)}):
                ws, argv, env, _ = codex.prepare(plan, root / 'run', starter, TASK, Path('/fake-client'), auth)
            try:
                overrides = dict(argv[i + 1].split('=', 1) for i, arg in enumerate(argv) if arg == '-c')
                required = {key[len('mcp_servers.'):-len('.required')]: json.loads(value)
                            for key, value in overrides.items() if key.startswith('mcp_servers.') and key.endswith('.required')}
                self.assertEqual(required, expected)
                self.assertIn('--ignore-user-config', argv)
                self.assertEqual(env['CODEX_HOME'], str(ws / 'client-home'))
                if expected:
                    self.assertEqual(overrides['mcp_servers.bsl-analyzer.startup_timeout_sec'], '120')
            finally:
                shutil.rmtree(ws)
