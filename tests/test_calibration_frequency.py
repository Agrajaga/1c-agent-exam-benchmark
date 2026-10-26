import copy
import json
import unittest
from pathlib import Path
from exam_bench.calibration_frequency import verify_annual, verify_controls


def controls():
    common = {k: 'ok' for k in ('p_initial', 'p_correction', 'p_next_year', 's_initial', 's_correction', 's_next_week')}
    initial = [{'date': '2025-12-30', 'item': 'FREQ_A', 'qty': 3}, {'date': '2025-12-30', 'item': 'FREQ_B', 'qty': 4}]
    next_week = [{'date': '2026-01-05', 'item': 'FREQ_A', 'qty': 5}, {'date': '2026-01-05', 'item': 'FREQ_B', 'qty': 6}]
    same_week = [{'date': '2026-01-01', 'item': 'FREQ_A', 'qty': 4}, {'date': '2026-01-01', 'item': 'FREQ_B', 'qty': 5}]
    g = {**common, 'p_same_year': 'BENCH_FREQUENCY_GUARD', 's_same_week': 'BENCH_FREQUENCY_GUARD', 's_mixed_batch': 'BENCH_FREQUENCY_GUARD',
         'policy_records': [{'date': '2025-01-01'}, {'date': '2026-01-01'}], 'spec_records': initial + next_week}
    b = {**common, 'p_same_year': 'ok', 's_same_week': 'ok', 's_mixed_batch': 'ok',
         'policy_records': [{'date': '2025-01-01'}, {'date': '2025-06-01'}, {'date': '2026-01-01'}],
         'spec_records': initial + same_week + next_week}
    return {'guarded': g, 'unguarded': b}


class FrequencyCalibration(unittest.TestCase):
    def test_complete_observations_pass(self):
        self.assertTrue(all(verify_controls(controls()).values()))

    def test_fixture_error_is_not_a_correct_guard(self):
        x = controls(); x['guarded']['s_same_week'] = 'Ошибка отбора платформы'
        self.assertFalse(verify_controls(x)['s_same_week'])

    def test_wrong_correction_cannot_pass_by_row_count(self):
        x = controls(); x['guarded']['spec_records'][0]['qty'] = 1
        self.assertFalse(verify_controls(x)['guarded_atomic_rows_and_correction'])

    def test_year_boundary_requires_same_calendar_week(self):
        x = controls(); x['unguarded']['spec_records'][2]['date'] = '2026-01-04'
        self.assertFalse(verify_controls(x)['unguarded_atomic_rows_and_correction'])

    def test_native_year_corrects_value_and_does_not_hide_errors(self):
        year = {'p_initial': 'ok', 'p_correction': 'ok', 'p_same_year': 'ok', 'p_next_year': 'ok',
                'policy_records': [{'date': '2025-01-01', 'method': 'FIFO'}, {'date': '2026-01-01', 'method': 'LIFO'}]}
        self.assertTrue(verify_annual(year))
        year['policy_records'][0]['method'] = 'LIFO'
        self.assertFalse(verify_annual(year))
        year['policy_records'][0]['method'] = 'FIFO'; year['p_same_year'] = 'ошибка записи'
        self.assertFalse(verify_annual(year))

    def test_recorded_platform_fixture_replays_control_assertions(self):
        recorded = json.loads((Path(__file__).parent / 'frequency_calibration_8_3_27.json').read_text(encoding='utf-8'))
        self.assertEqual(recorded['platform_version'], '8.3.27.2342')
        self.assertTrue(all(verify_controls(recorded['observations']).values()))
        self.assertTrue(verify_annual(recorded['observations']['year_native']))


if __name__ == '__main__':
    unittest.main()
