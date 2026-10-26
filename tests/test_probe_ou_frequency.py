import tempfile
import unittest
from pathlib import Path
from tools.probe_ou_frequency import inspect


class FrequencyProbe(unittest.TestCase):
    def test_period_is_evidence_not_a_verdict(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            folder = root / 'InformationRegisters'
            folder.mkdir()
            for name, period in [('Policy', 'Year'), ('Spec', 'Day')]:
                (folder / (name + '.xml')).write_text(
                    '<Meta xmlns="urn:1c"><InformationRegister><Properties>'
                    '<InformationRegisterPeriodicity>' + period + '</InformationRegisterPeriodicity>'
                    '</Properties></InformationRegister></Meta>', encoding='utf-8')
            binding = {'ou': {'objects': {'policies': 'InformationRegister.Policy', 'specification': 'InformationRegister.Spec'}}}
            result = inspect(root, binding)
            self.assertEqual([r['periodicity'] for r in result], ['Year', 'Day'])
            self.assertEqual([r['status'] for r in result], ['evidence_only', 'evidence_only'])

    def test_missing_and_unsafe_bindings_are_not_proof(self):
        with tempfile.TemporaryDirectory() as td:
            result = inspect(td, {'ou': {'objects': {'policies': 'InformationRegister.../../elsewhere'}}})
            self.assertEqual([r['status'] for r in result], ['not_observed', 'not_observed'])


if __name__ == '__main__':
    unittest.main()
