import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from exam_bench import replay_calibration as replay
from exam_bench.common import grading_fingerprint, write_json

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '.local/calibration/accepted-v15'


class ReplayGuards(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.patches = [patch('exam_bench.runtime.require_execution_mode'),
                        patch('exam_bench.runtime.platform_binary', return_value=str(Path('/bin/sh').resolve())),
                        patch('exam_bench.runtime.machine_identity', return_value={'os': 'TestOS'})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.td.cleanup()

    def source(self, **summary):
        write_json(self.root / 'src-cal/summary.json', {'accepted': True, 'negatives': [{'mutation': 'm'}], 'positives': [],
                                                        'implementation_files': {}, **summary})
        return self.root / 'src-cal'

    def test_only_an_accepted_full_calibration_can_be_replayed(self):
        for summary in ({'accepted': False}, {'mode': 'quick'}, {'mode': 'replay'}, {'negatives': []}):
            with self.subTest(summary=summary), self.assertRaises(ValueError):
                replay.replay_calibrate(self.source(**summary), self.root, self.root / 'dt', '/bin/sh', self.root / ('out-' + str(len(summary))))

    def test_changed_observation_code_requires_the_full_calibration(self):
        with patch.object(replay, 'code_unchanged', return_value=('abc', ['one'])), patch.object(replay.grader, 'grade') as grade:
            result = replay.replay_calibrate(self.source(), self.root, self.root / 'dt', '/bin/sh', self.root / 'out')
        self.assertFalse(result['accepted'])
        self.assertEqual(result['observation_inputs_differ'], ['one'])
        grade.assert_not_called()
        with patch.object(replay, 'code_unchanged', return_value=(None, 'source_commit_not_found')):
            result = replay.replay_calibrate(self.source(), self.root, self.root / 'dt', '/bin/sh', self.root / 'out2')
        self.assertEqual(result['reason'], 'source_commit_not_found')

    def test_stored_platform_is_restored_after_replay(self):
        original = replay.grader.OneC, replay.grader.case_workspace, replay.grader.inject
        with replay.stored_platform({}):
            self.assertIsNot(replay.grader.OneC, original[0])
        self.assertEqual((replay.grader.OneC, replay.grader.case_workspace, replay.grader.inject), original)


@unittest.skipUnless((SOURCE / 'summary.json').is_file(), 'Stored full calibration is local to the owner machine')
class ReplayStoredCalibration(unittest.TestCase):
    def test_current_grader_accepts_positives_and_catches_every_mutant(self):
        summary = json.loads((SOURCE / 'summary.json').read_text())
        with tempfile.TemporaryDirectory() as td:
            for p in summary['positives'][:2]:
                g, _ = replay.replay_run(SOURCE, p['grade_ref'], p['variant'], Path(td) / p['variant'] / str(p['repetition']))
                self.assertEqual(g['status'], 'partial_pass')
            for n in summary['negatives']:
                g, _ = replay.replay_run(SOURCE, n['grade_ref'], n['mutation'], Path(td) / n['mutation'])
                self.assertEqual(next(r['verdict'] for r in g['rules'] if r['id'] == n['rule']), 'fail', n['mutation'])


if __name__ == '__main__':
    unittest.main()
