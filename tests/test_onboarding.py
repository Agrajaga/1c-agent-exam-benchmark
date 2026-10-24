"""Every blocking case on the way to an exam leads the user somewhere: a button, a link or a command."""
import itertools
import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import installers, readiness

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ('github', 'platform', 'protection', 'agent', 'isolation', 'starter', 'calibration')


def actionable(step):
    return bool(step['actions'] or step.get('link') or step.get('copy') or step.get('input') or step.get('hint'))


class Onboarding(unittest.TestCase):
    def snapshot(self, root, tools, manager, platforms, codex, logged_in, agent='codex', author=None):
        def find(tool):
            return '/fake/' + tool if tool in tools else None
        settings = {'agent': agent}
        with patch.object(installers, 'find', side_effect=find), \
             patch.object(installers, 'package_manager', return_value=manager), \
             patch.object(readiness, 'discover_platforms', return_value=platforms), \
             patch.object(readiness, 'discover_codex', return_value=codex), \
             patch.object(readiness, 'codex_logged_in', return_value=logged_in), \
             patch.object(readiness, 'settings', return_value=settings):
            if author:
                readiness.write(root / '.local/community/operator.json', author)
            return readiness.snapshot(root)

    def test_every_missing_prerequisite_has_a_next_step(self):
        platform = [{'path': '/opt/1cv8/8.3.27.2074/1cv8', 'version': '8.3.27.2074'}]
        cases = itertools.product(
            [set(), {'git'}, {'git', 'gh'}, {'git', 'gh', 'npm', 'node'}, {'git', 'gh', 'claude', 'npm'}],
            [None, 'winget', 'brew'], [[], platform], [[], ['/fake/codex']], [False, True], ['codex', 'claude'])
        for tools, manager, platforms, codex, logged_in, agent in cases:
            with self.subTest(tools=sorted(tools), manager=manager, platform=bool(platforms), codex=bool(codex), login=logged_in, agent=agent), \
                 tempfile.TemporaryDirectory() as td:
                root = Path(td)
                shutil.copytree(ROOT / readiness.STARTER, root / readiness.STARTER)
                state = self.snapshot(root, tools, manager, platforms, codex, logged_in, agent)
                steps = {s['id']: s for s in state['steps']}
                self.assertEqual(set(REQUIRED) - set(steps), set())
                for name in REQUIRED:
                    if steps[name]['state'] != 'ok':
                        self.assertTrue(actionable(steps[name]) or steps[name]['state'] == 'blocked', (name, steps[name]))
                self.assertFalse(state['ready'])

    def test_installs_are_offered_through_a_package_manager_only_when_one_exists(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shutil.copytree(ROOT / readiness.STARTER, root / readiness.STARTER)
            github = {s['id']: s for s in self.snapshot(root, {'git'}, 'winget', [], [], False)['steps']}['github']
            self.assertIn({'tool': 'gh'}, [a['data'] for a in github['actions']])
            github = {s['id']: s for s in self.snapshot(root, {'git'}, None, [], [], False)['steps']}['github']
            self.assertNotIn('install', [a['id'] for a in github['actions']])
            self.assertIn('gh', github['hint'])
            agent = {s['id']: s for s in self.snapshot(root, {'git', 'gh'}, 'brew', [], [], False)['steps']}['agent']
            self.assertIn({'tool': 'node'}, [a['data'] for a in agent['actions']])

    def test_logins_and_claude_token(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shutil.copytree(ROOT / readiness.STARTER, root / readiness.STARTER)
            github = {s['id']: s for s in self.snapshot(root, {'git', 'gh'}, None, [], ['/fake/codex'], False)['steps']}
            self.assertIn('login', [a['id'] for a in github['github']['actions']])
            self.assertIn({'kind': 'codex-login'}, [a['data'] for a in github['agent']['actions']])
            claude = {s['id']: s for s in self.snapshot(root, {'git', 'gh', 'claude'}, None, [], [], False, 'claude')['steps']}['agent']
            self.assertEqual(claude['input']['action'], 'claude-token')
            with self.assertRaises(ValueError):
                readiness.act('claude-token', {'value': 'not a token'}, root)
            readiness.act('claude-token', {'value': 'sk-ant-oat01-' + 'x' * 40}, root)
            if os.name != 'nt':
                self.assertEqual((root / readiness.CLAUDE_TOKEN).stat().st_mode & 0o777, 0o600)
            claude = {s['id']: s for s in self.snapshot(root, {'git', 'gh', 'claude'}, None, [], [], False, 'claude')['steps']}['agent']
            self.assertEqual(claude['state'], 'ok')

    def test_unsafe_action_protection_is_switched_off_and_back_in_the_user_file(self):
        with tempfile.TemporaryDirectory() as td:
            root, conf = Path(td), Path(td) / 'home/conf/conf.cfg'
            conf.parent.mkdir(parents=True); conf.write_text('SystemLanguage=RU', encoding='utf-8')
            with patch.object(readiness, 'user_conf', return_value=conf), patch.object(Path, 'is_file', lambda p: p == conf or Path.exists(p)):
                self.assertIsNone(readiness.protection_disabled(None) if not Path('/opt/1cv8/conf/conf.cfg').exists() else None)
                readiness.act('disable-protection', {}, root)
                self.assertEqual(conf.read_text(), 'SystemLanguage=RU\nDisableUnsafeActionProtection=.*\n')
                self.assertTrue((conf.parent / 'conf.cfg.before-exam-bench.bak').is_file())
                self.assertEqual(readiness.protection_disabled(None), conf)
                readiness.act('restore-protection', {}, root)
                self.assertEqual(conf.read_text(), 'SystemLanguage=RU\n')

    def test_device_login_link_and_code_are_read_from_the_helper_log(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            installers.start('gh-login', [sys.executable, '-u', '-c', 'print("! First copy your one-time code: 65D5-FF93");'
                                          'print("Open this URL to continue in your web browser: https://github.com/login/device");'
                                          'import time; time.sleep(2)'], root)
            for _ in range(50):
                state = installers.helper(root)
                if state['code']:
                    break
                import time; time.sleep(.1)
            self.assertEqual((state['code'], state['url']), ('65D5-FF93', 'https://github.com/login/device'))
            with self.assertRaises(RuntimeError):
                installers.start('codex-login', [sys.executable, '-c', 'pass'], root)
            installers._processes['gh-login'].wait()
            self.assertEqual(installers.helper(root)['returncode'], 0)


if __name__ == '__main__':
    unittest.main()
