import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from exam_bench import codex


class HarnessCleanup(unittest.TestCase):
    def test_harness_start_failure_removes_auth_and_stops_helpers_before_a_model_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);ws=root/'worker';run=root/'run'
            (ws/'client-home').mkdir(parents=True);run.mkdir()
            auth=ws/'client-home/auth.json';auth.write_text('TEST_FIXTURE')
            plan={'harness':'code-index-1.9.0','input_revision':'fixture'}
            with patch.object(codex,'machine_identity',return_value={}), \
                 patch.object(codex,'prepare',return_value=(ws,[],{},{})), \
                 patch.object(codex,'solver_prompt',return_value='fixture'), \
                 patch.object(codex,'portable_harness_run',return_value=True), \
                 patch('exam_bench.portable_harnesses.launch',side_effect=RuntimeError('fixture startup failure')), \
                 patch('exam_bench.portable_harnesses.stop',return_value={'stop_confirmed':True}) as stop, \
                 patch.object(codex,'supervise') as model:
                with self.assertRaisesRegex(RuntimeError,'startup failure'):
                    codex.start(plan,run,root,root,'unused','unused')
            self.assertFalse(auth.exists())
            stop.assert_called_once_with(ws)
            model.assert_not_called()
