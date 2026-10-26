import json
import tempfile
import unittest
from pathlib import Path

from exam_bench.calibration_frequency_entries import install_entry, observer, verify_service_controls
from tools.frequency_entry_contract import validate_frequency_entries


class EntryCalibration(unittest.TestCase):
    def test_native_recorded_fixture_replays_controls(self):
        recorded = json.loads((Path(__file__).parent / 'frequency_entries_calibration_8_3_27.json').read_text(encoding='utf-8'))
        self.assertEqual(recorded['platform_version'], '8.3.27.2342')
        self.assertIn('not a fresh calibration', recorded['description'])
        self.assertTrue(all(verify_service_controls(recorded['observations']).values()))

    def test_generated_entry_matches_candidate_contract(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td); (src / 'Configuration.xml').write_text('<Configuration><ChildObjects></ChildObjects></Configuration>')
            entries = install_entry(src)
            actual, errors = validate_frequency_entries(src, {'frequency_entry': entries})
            self.assertEqual((actual, errors), (entries, {}))
            code = observer()
            self.assertIn('BenchFrequencyInput.Policy(Отдел, Период, Метод)', code)
            self.assertIn('BenchFrequencyInput.Specification(Товары[0], Период, Строки)', code)
            self.assertNotIn('СоздатьНаборЗаписей', code)
            self.assertNotIn('СоздатьМенеджерЗаписи', code)
            self.assertNotIn('s_mixed_batch', code)


if __name__ == '__main__':
    unittest.main()
