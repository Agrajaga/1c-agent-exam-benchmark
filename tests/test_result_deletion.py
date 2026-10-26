"""Deletion changes local history, never the evidence needed by other assessments."""
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from tools.community_service import start
from tools.demo_runner import ACTIVE, atomic, history
from tools.serve_result_site import StaticHandler


class ResultDeletion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.job = self.root / '.local/demo/jobs/demo-test'
        self.status = {'mode': 'run', 'phase': 'failed', 'started_unix': 1}
        atomic(self.job / 'status.json', self.status)

    def delete(self, identifier='demo-test'):
        return start('delete', {'id': identifier}, self.root)

    def test_delete_persists_and_preserves_evidence_and_other_results(self):
        atomic(self.root / '.local/demo/jobs/demo-other/status.json', self.status)
        atomic(self.job / 'evaluation.json', {})
        atomic(self.root / '.local/runs/demo-test/result.json', {'proof': 'retained'})
        self.assertTrue(self.delete()['deleted'])
        self.assertEqual([r['job_id'] for r in history(self.root)], ['demo-other'])
        self.assertTrue((self.job / 'evaluation.json').is_file())
        self.assertTrue((self.root / '.local/runs/demo-test/result.json').is_file())
        self.assertTrue(self.delete()['deleted'])
        for action in ('prepare', 'pr'):
            with self.assertRaisesRegex(ValueError, 'удалён'):
                start(action, {'id': 'demo-test'}, self.root)

    def test_every_active_phase_is_protected(self):
        for phase in ACTIVE:
            with self.subTest(phase=phase):
                atomic(self.job / 'status.json', {**self.status, 'phase': phase})
                with self.assertRaises(RuntimeError):
                    self.delete()

    def test_cli_entry_points_cannot_publish_deleted_results(self):
        from tools.community_results import make_pr, prepare_bundle
        self.delete()
        for operation in (prepare_bundle, make_pr):
            with self.subTest(operation=operation.__name__), self.assertRaisesRegex(ValueError, 'удалён'):
                operation('demo-test', self.root)

    def test_pr_created_from_cli_also_protects_history(self):
        from tools.community_results import make_pr
        url = 'https://github.com/zeegin/1c-agent-exam-benchmark/pull/1'
        with patch('tools.community_results._make_pr', return_value=url):
            self.assertEqual(make_pr('demo-test', self.root), url)
        with self.assertRaises(RuntimeError):
            self.delete()
        self.assertFalse(history(self.root)[0]['deletable'])

    def test_concurrent_cli_pr_records_url_before_deletion_can_proceed(self):
        from concurrent.futures import ThreadPoolExecutor
        from tools.community_results import make_pr
        entered, release, deleting = threading.Event(), threading.Event(), threading.Event()
        url = 'https://github.com/zeegin/1c-agent-exam-benchmark/pull/1'

        def publish(*args):
            entered.set()
            if not release.wait(5):
                raise TimeoutError('Test did not release the PR operation')
            return url

        def delete():
            deleting.set()
            return self.delete()

        with patch('tools.community_results._make_pr', side_effect=publish), ThreadPoolExecutor(2) as pool:
            publishing = pool.submit(make_pr, 'demo-test', self.root)
            try:
                self.assertTrue(entered.wait(5))
                deletion = pool.submit(delete)
                self.assertTrue(deleting.wait(5))
            finally:
                release.set()
            self.assertEqual(publishing.result(timeout=5), url)
            with self.assertRaises(RuntimeError):
                deletion.result(timeout=5)
        self.assertEqual(len(history(self.root)), 1)

    def test_saved_pr_record_is_protected_even_if_empty(self):
        atomic(self.root / '.local/community/pr/demo-test.json', {})
        with self.assertRaises(RuntimeError):
            self.delete()
        self.assertFalse((self.root / '.local/community/deleted/demo-test.json').exists())

    def test_community_worker_and_pr_in_action_are_protected(self):
        for action in ('prepare', 'pr'):
            atomic(self.root / '.local/community/action.json',
                   {'id': 'demo-test', 'action': action, 'phase': 'working', 'pid': 123})
            with patch('tools.demo_runner.alive', return_value=True), self.assertRaises(RuntimeError):
                self.delete()
        atomic(self.root / '.local/community/action.json',
               {'id': 'demo-test', 'action': 'pr', 'phase': 'finished', 'pr_url': 'https://github.com/example/pull/1'})
        with self.assertRaises(RuntimeError):
            self.delete()

    def test_invalid_ids_unknown_results_and_payloads_are_rejected(self):
        for identifier in ('../escape', 'demo-absent', '', None, 1):
            with self.subTest(identifier=identifier), self.assertRaises((ValueError, TypeError)):
                self.delete(identifier)
        for data in ({}, {'id': 'demo-test', 'path': 'outside'}, [], None):
            with self.subTest(data=data), self.assertRaises((ValueError, TypeError)):
                start('delete', data, self.root)


class DeletionHTTP(unittest.TestCase):
    def test_real_endpoint_enforces_security_and_deletes_without_controller(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            atomic(root / '.local/demo/jobs/demo-test/status.json',
                   {'mode': 'run', 'phase': 'finished', 'started_unix': 1})
            handler = type('DeleteHandler', (StaticHandler,),
                           {'controller': None, 'community_token': 'csrf', 'log_message': lambda *a: None})
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f'http://127.0.0.1:{server.server_port}/api/community/delete'
                with patch('tools.serve_result_site.ROOT', root):
                    for extra in ({'X-Demo-Token': ''}, {'Origin': 'https://foreign.example'}, {'Host': 'foreign.example'}):
                        request = urllib.request.Request(url, data=b'{"id":"demo-test"}',
                            headers={'Content-Type': 'application/json', 'X-Demo-Token': 'csrf', **extra})
                        with self.assertRaises(urllib.error.HTTPError) as error:
                            urllib.request.urlopen(request)
                        self.assertEqual(error.exception.code, 403)
                        self.assertEqual(len(history(root)), 1)
                    request = urllib.request.Request(url, data=b'{"id":"demo-test"}',
                        headers={'Content-Type': 'application/json', 'X-Demo-Token': 'csrf'})
                    from exam_bench.locking import file_lock
                    with file_lock(root / '.local/community/action.lock'):
                        with self.assertRaises(urllib.error.HTTPError) as error:
                            urllib.request.urlopen(request, timeout=1)
                        self.assertEqual(error.exception.code, 409)
                    with urllib.request.urlopen(request) as response:
                        self.assertTrue(json.load(response)['deleted'])
                    self.assertEqual(history(root), [])
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


class DeletionUI(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is needed for page event tests')
    def test_confirmation_refresh_and_errors(self):
        subprocess.run([shutil.which('node'), str(Path(__file__).with_name('result_deletion_ui.cjs'))],
                       check=True, capture_output=True, text=True, encoding='utf-8', timeout=30)
