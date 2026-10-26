import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from exam_bench.common import digest, grading_inputs, grading_fingerprint, runtime_fingerprint
from exam_bench.preflight import verify_calibration
from tools.serve_result_site import watch_signature

ROOT = Path(__file__).resolve().parents[1]


class GradingIdentity(unittest.TestCase):
    def test_penalty_dependencies_and_policy_are_identified(self):
        inputs = grading_inputs()
        for name in ('penalties.py', 'assessment.py', 'examiner.py', 'codescan.py', 'queryschema.py', 'calcwrite.py', 'bp.py'):
            self.assertIn(name, inputs)
        for name in ('checks.json', 'private/owner-scoring-policy.json', 'private/official-assessment-mapping.json'):
            self.assertIn('tasks/1c-platform-official-sample/' + name, inputs)

    def test_every_declared_input_changes_the_score_identity_and_unrelated_files_do_not(self):
        before = grading_fingerprint()
        from exam_bench import common
        for key, path in grading_inputs().items():
            with self.subTest(key=key), patch.object(common, 'digest', side_effect=lambda p: '0' * 64 if Path(p) == path else digest(p)):
                after = grading_fingerprint()
                self.assertEqual([k for k in before if before[k] != after[k]], [key])
        self.assertNotIn('site/style.css', before)

    def test_old_incomplete_receipt_is_stale_and_runtime_receipt_is_not_penalty_policy(self):
        receipt = {'accepted': True, 'readonly_sources_verified': True, 'grader_sha256': digest(ROOT/'exam_bench/grader.py'),
                   'implementation_files': runtime_fingerprint()}
        with self.assertRaisesRegex(ValueError, 'stale'):
            verify_calibration(receipt)
        receipt.update(fingerprint_version=2, runtime_implementation_files=runtime_fingerprint())
        verify_calibration(receipt)
        receipt['runtime_implementation_files']['observer.py'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'stale'):
            verify_calibration(receipt)

    def test_watcher_tracks_all_exported_practices_and_policy_but_not_unrelated_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ('site', 'rules', 'tasks', 'starters'):
                shutil.copytree(ROOT/name, root/name, ignore=shutil.ignore_patterns('dist', 'dist-public', '.dist-staging', '*.dt', '*.docx'))
            before = watch_signature(root, True)
            paths = [root/'rules/1c-specialist-platform'/name for name in ('examiner.json','chistov.json','standards.json')]
            paths.append(root/'tasks/1c-platform-official-sample/private/owner-scoring-policy.json')
            for path in paths:
                data = path.read_bytes()
                path.write_bytes(data+b'\n')
                self.assertNotEqual(watch_signature(root, True), before, path.name)
                path.write_bytes(data)
            (root/'rules/1c-specialist-platform/unrelated.json').write_text('{}')
            self.assertEqual(watch_signature(root, True), before)
