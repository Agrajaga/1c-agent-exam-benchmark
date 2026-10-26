import copy
import json
import unittest
from pathlib import Path

from tools.calibrate_frequency_ui import verify_controls


class FrequencyFormControls(unittest.TestCase):
    def setUp(self):
        fixture = json.loads((Path(__file__).parent / 'frequency_ui_8_3_27.json').read_text(encoding='utf-8'))
        self.assertEqual(fixture['platform_version'], '8.3.27.2342')
        self.results = fixture['observations']

    def test_recorded_native_observations_satisfy_all_controls(self):
        self.assertTrue(all(verify_controls(self.results).values()))

    def test_platform_error_does_not_prove_guard(self):
        results = copy.deepcopy(self.results)
        results['guarded']['policy'][1] = 'Ошибка платформы при записи'
        self.assertFalse(verify_controls(results)['policy_outcomes'])

    def test_missing_or_hidden_field_is_not_evidence_of_usable_form(self):
        results = copy.deepcopy(self.results)
        next(e for e in results['guarded']['elements'] if e['name'] == 'Block')['visible'] = False
        self.assertFalse(verify_controls(results)['form_elements'])

    def test_bad_snapshot_or_missing_observations_cannot_pass(self):
        results = copy.deepcopy(self.results)
        results['guarded']['spec_snapshot'].pop()
        self.assertFalse(verify_controls(results)['spec_snapshots'])
        results['guarded']['policy'] = []
        self.assertFalse(verify_controls(results)['policy_outcomes'])

    def test_duplicate_detail_cannot_pass_as_two_distinct_rows(self):
        results = copy.deepcopy(self.results)
        results['guarded']['spec_snapshot'][1]['item'] = 'FREQ_FormA'
        self.assertFalse(verify_controls(results)['spec_snapshots'])


if __name__ == '__main__':
    unittest.main()
