import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from exam_bench.codex import worker_document
from exam_bench.materials import DEFAULT_PROMPT, DEADLINE_PROMPT, solver_prompt
from exam_bench.preflight import validate_plan


class Deadline(unittest.TestCase):
    def test_disclosed_deadline_reaches_worker_and_prompt(self):
        plan = {'deadline_disclosed': True, 'solve_timeout_seconds': 1800}
        before = datetime.now(timezone.utc)
        deadline = datetime.fromisoformat(worker_document(plan, Path('/w'), {}, [], True)['deadline_utc'])
        self.assertTrue(before + timedelta(seconds=1799) <= deadline <= datetime.now(timezone.utc) + timedelta(seconds=1800))
        self.assertEqual(solver_prompt(plan), DEFAULT_PROMPT + DEADLINE_PROMPT)

    def test_without_flag_nothing_changes_and_probes_keep_their_prompt(self):
        self.assertNotIn('deadline_utc', worker_document({'solve_timeout_seconds': 1800}, Path('/w'), {}, [], True))
        self.assertEqual(solver_prompt({}), DEFAULT_PROMPT)
        self.assertEqual(solver_prompt({'deadline_disclosed': True}, 'probe'), 'probe')

    def test_flag_must_be_boolean(self):
        with self.assertRaisesRegex(ValueError, 'deadline_disclosed'):
            validate_plan({'schema_version': 1, 'run_id': 'x', 'client_version': '1', 'model': 'gpt-x', 'billing_channel': 'subscription',
                           'harness': 'none', 'solve_timeout_seconds': 1800, 'stop_grace_seconds': 3, 'purpose': 'p',
                           'acceptance_profile': 'a', 'deadline_disclosed': 'yes'})


if __name__ == '__main__':
    unittest.main()
