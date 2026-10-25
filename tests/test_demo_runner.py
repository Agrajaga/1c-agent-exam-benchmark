import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import ExitStack
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from exam_bench.common import tree_manifest
from tools.demo_runner import Controller, atomic, read, work, history


class ResultHistory(unittest.TestCase):
    def test_supplemental_evaluation_does_not_hide_original_rejected_submission(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            jobs = root / '.local/demo/jobs'
            atomic(jobs / 'demo-original/status.json', {'mode': 'run', 'phase': 'invalid_submission', 'started_unix': 1})
            atomic(jobs / 'demo-supplemental/status.json', {'mode': 'regrade', 'phase': 'finished', 'started_unix': 2})
            atomic(jobs / 'demo-supplemental/evaluation.json', {})
            with patch('tools.demo_runner.public_evaluation', return_value={'binding_compatibility': {'scope': 'supplemental'}}):
                rows = history(root)
            self.assertEqual(len(rows), 2)
            original = next(r for r in rows if r['mode'] == 'run')
            self.assertEqual(original['phase'], 'invalid_submission')
            self.assertIsNone(original['evaluation'])
            self.assertTrue(next(r for r in rows if r['mode'] == 'regrade')['evaluation']['binding_compatibility'])
from tools.serve_result_site import StaticHandler


class DemoHTTP(unittest.TestCase):
    def setUp(self):
        self.controller = Mock(token='test-token')
        self.controller.snapshot.return_value = {'ready': True}
        self.controller.start.return_value = {'job_id': 'test-job'}
        handler = type('TestHandler', (StaticHandler,), {'controller': self.controller, 'log_message': lambda *a: None})
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def post(self, headers=None, data=None):
        request = urllib.request.Request(self.url + '/api/demo/start',
            data=json.dumps(data or {'mode': 'run'}).encode(),
            headers={'Content-Type': 'application/json', 'X-Demo-Token': 'test-token', **(headers or {})})
        return urllib.request.urlopen(request)

    def test_explicit_local_start_is_accepted(self):
        with self.post() as response:
            self.assertEqual(response.status, 202)
        self.controller.start.assert_called_once_with('run')

    def test_foreign_origin_cannot_launch(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.post({'Origin': 'https://foreign.example'})
        self.assertEqual(raised.exception.code, 403)
        self.controller.start.assert_not_called()

    def test_missing_token_cannot_launch(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.post({'X-Demo-Token': ''})
        self.assertEqual(raised.exception.code, 403)
        self.controller.start.assert_not_called()

    def test_paths_cannot_be_submitted(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.post(data={'mode': 'run', 'client': 'arbitrary-command'})
        self.assertEqual(raised.exception.code, 400)
        self.controller.start.assert_not_called()

    def test_duplicate_is_conflict(self):
        self.controller.start.side_effect = RuntimeError('Already running')
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.post()
        self.assertEqual(raised.exception.code, 409)


class DemoWorker(unittest.TestCase):
    def test_public_snapshot_does_not_include_local_gate_paths(self):
        from tools.demo_runner import atomic
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            atomic(root/'.local/demo/current.json',{'job_id':'fixture'})
            atomic(root/'.local/demo/jobs/fixture/status.json',{'phase':'finished','started_unix':0,'ended_unix':1,
                'run_id':'fixture','pid':123,'gates':{'load':{'reason':'PRIVATE_LOCAL_PATH'}}})
            with patch('tools.demo_runner.config',return_value={'model':'gpt-test','platform_version':'test','timeout_seconds':1800}), \
                 patch('tools.demo_runner.prerequisites'), patch('tools.demo_runner.publication',return_value={'results':[]}), \
                 patch('tools.demo_runner.harness_options',return_value=[]):
                result=Controller(root).snapshot()
            self.assertNotIn('PRIVATE_LOCAL_PATH',json.dumps(result))
            self.assertNotIn('pid',result['job'])

    def exercise(self, mode='run', valid=True):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            job_id = 'demo-test'; job = root / '.local/demo/jobs' / job_id
            atomic(job / 'status.json', {'job_id': job_id, 'run_id': 'candidate', 'mode': mode, 'phase': 'queued'})
            task = root / 'tasks/1c-platform-official-sample'
            for name, data in [('checks.json', {'requirements': []}), ('private/official-assessment-mapping.json', {}), ('private/owner-scoring-policy.json', {})]:
                atomic(task / name, data)
            (task / 'public').mkdir(); (task / 'public/statement.docx').write_bytes(b'fixture')
            atomic(root / 'profiles/ai-exam-execution-policy.json', {'policy_id': 'fixture'})
            (root / 'exam_bench').mkdir()
            atomic(root / 'calibration.json', {'accepted': True})
            (root / 'starter.dt').write_bytes(b'fixture')
            cfg = {'calibration': 'calibration.json', 'starter_dt': 'starter.dt', 'starter_source': 'starter',
                   'client': 'codex', 'model': 'gpt-test', 'timeout_seconds': 1800}
            calls = []
            run = root / '.local/runs/candidate'

            def solve(*args, **kwargs):
                calls.append('solve')
                art = run / 'artifacts'
                (art / 'src').mkdir(parents=True)
                (art / 'src/Configuration.xml').write_text('<fixture/>')
                atomic(art / 'binding.json', {})
                atomic(run / 'artifact-manifest.json', tree_manifest(art))
                result = {'submission': {'valid': valid}, 'process': {'stop_confirmed': True, 'status': 'completed'}}
                atomic(run / 'result.json', result)
                return result

            stack.enter_context(patch('tools.demo_runner.prerequisites', return_value=(cfg, {'profile_id': 'test-profile'})))
            stack.enter_context(patch('tools.demo_runner.subprocess.run', return_value=Mock(stdout='codex-cli test')))
            stack.enter_context(patch('exam_bench.codex.start', side_effect=solve))
            stack.enter_context(patch('exam_bench.materials.delivery_metadata', return_value={}))
            stack.enter_context(patch('exam_bench.harness.profile_path', return_value=root / 'calibration.json'))
            stack.enter_context(patch('exam_bench.runtime.machine_identity', return_value={'platform_version': 'test'}))
            stack.enter_context(patch('exam_bench.runtime.platform_binary', return_value='fixture'))
            stack.enter_context(patch('exam_bench.submission.strip_extras', return_value=({}, [])))
            stack.enter_context(patch('exam_bench.submission.canonical_ledger', return_value=({}, [])))
            stack.enter_context(patch('exam_bench.submission.check_bindings'))
            def gates(*args):
                calls.append('gates'); return {}, None, True
            stack.enter_context(patch('exam_bench.gates.check_all', side_effect=gates))
            stack.enter_context(patch('exam_bench.gates.starter_for', return_value={}))
            def grade(*args):
                calls.append('grade'); return {'rules': [], 'status': 'partial_pass', 'errors': {}, 'observations': {}}
            stack.enter_context(patch('exam_bench.grader.grade', side_effect=grade))
            stack.enter_context(patch('exam_bench.penalties.assess', return_value={'score': {}}))
            if mode == 'regrade':
                solve(); calls.clear()
            work(job_id, root)
            state = read(job / 'status.json')
            self.assertEqual(state['phase'], 'finished' if valid else 'invalid_submission')
            self.assertEqual(calls, (['solve'] if mode == 'run' else []) + (['gates', 'grade'] if valid else []))
            self.assertEqual((job / 'evaluation.json').exists(), valid)

    def test_fresh_attempt_automatically_runs_acceptance(self):
        self.exercise()

    def test_regrade_never_contacts_model(self):
        self.exercise(mode='regrade')

    def test_invalid_submission_never_gets_a_grade(self):
        self.exercise(valid=False)

    def test_no_submission_names_the_agent_and_a_failed_client(self):
        from tools.demo_runner import no_submission
        failed = no_submission('claude', {'status': 'client_error', 'exit_code': 1})
        self.assertIn('Claude Code завершился с ошибкой (код 1)', failed)
        self.assertNotIn('Codex', failed)
        self.assertIn('Время вышло, Codex', no_submission('codex', {'status': 'timeout'}))
        self.assertIn('Codex завершил попытку', no_submission('codex', {'status': 'completed'}))
        self.assertIn('Причина: Ledger subconto', no_submission('codex', {'status': 'completed'}, 'Ledger subconto X'))

    def test_controller_rejects_second_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            c = Controller(Path(temporary))
            with patch.object(c, 'snapshot', return_value={'job': {'phase': 'solving'}}), patch('tools.demo_runner.subprocess.Popen') as spawn:
                with self.assertRaises(RuntimeError):
                    c.start('run')
                spawn.assert_not_called()
