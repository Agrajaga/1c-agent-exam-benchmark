import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.probe_frequency_entry import observer, run


def binding():
    return {'objects': {'items': 'Catalog.Items'}, 'ou': {
        'objects': {'departments': 'Catalog.Departments', 'properties': 'Catalog.Properties',
                    'policies': 'InformationRegister.Policies', 'specification': 'InformationRegister.Specification'},
        'fields': {'properties': {'owner': 'Owner'}, 'policies': {'department': 'Department', 'method': 'Method'},
                   'policy_values': {'fifo': 'Enum.Methods.FIFO', 'lifo': 'Enum.Methods.LIFO'},
                   'specification': {'block': 'Block', 'item': 'Item', 'property': 'Property', 'quantity': 'Quantity'}},
        'frequency_entry': {'policy': 'CommonModule.Entry.Policy', 'specification': 'CommonModule.Entry.Specification'}}}


class ProbeFrequencyEntry(unittest.TestCase):
    def test_observer_calls_service_and_does_not_write_bypassing_it(self):
        code = observer(binding())
        self.assertIn('Entry.Policy(Отдел, Период, Метод)', code)
        self.assertIn('Entry.Specification(Товары[0], Период, Строки)', code)
        self.assertNotIn('СоздатьМенеджерЗаписи', code)
        self.assertNotIn('СоздатьНаборЗаписей', code)
        self.assertNotIn('ЗаписьДвухПериодов', code)
        self.assertIn('РегистрСведений.Specification', code)

    def test_incomplete_fields_are_unassessed_before_starting_platform(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root / 'src'; source.mkdir()
            bad = binding(); del bad['ou']['fields']['specification']['property']
            with patch('exam_bench.runtime.require_execution_mode'), \
                 patch('exam_bench.runtime.platform_binary', return_value=str((root / '1cv8').resolve())), \
                 patch('tools.probe_frequency_entry.validate_frequency_entries', return_value=(bad['ou']['frequency_entry'], {})), \
                 patch('tools.probe_frequency_entry.OneC') as platform:
                result = run(source, bad, root / 'starter.dt', root / '1cv8', root / 'out')
            self.assertEqual(result['grading_status'], 'not_assessed')
            self.assertIn('Неполная', result['reason'])
            self.assertEqual(json.loads((root / 'out/service-observation.json').read_text(encoding='utf-8'))['grading_status'], 'not_assessed')
            platform.assert_not_called()

    def test_missing_entry_is_unassessed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root / 'src'; source.mkdir()
            with patch('exam_bench.runtime.require_execution_mode'), \
                 patch('exam_bench.runtime.platform_binary', return_value=str((root / '1cv8').resolve())):
                result = run(source, {'ou': {}}, root / 'starter.dt', root / '1cv8', root / 'out')
            self.assertEqual(result['grading_status'], 'not_assessed')
            self.assertIn('нужны обе', result['reason'])

    def test_unsafe_policy_value_is_rejected_before_generated_code(self):
        bad = binding(); bad['ou']['fields']['policy_values']['fifo'] = 'Enum.X.Y); ЗловредныйКод();'
        with self.assertRaises(ValueError):
            observer(bad)


if __name__ == '__main__':
    unittest.main()
