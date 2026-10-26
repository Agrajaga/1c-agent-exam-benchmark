import tempfile
import unittest
from pathlib import Path

from exam_bench import ou


def binding():
    return {'ou': {'objects': {'policies': 'InformationRegister.Policy', 'specification': 'InformationRegister.Spec'},
                   'fields': {'sale': {'department': 'Rows.Department'}}}}


def observations():
    def balance(qty, cost):
        return [{'department': 'BENCH_H', 'item': 'BENCH_X', 'property': '', 'qty': qty, 'cost': cost}]
    return {'ou_history': {'snapshots': {
        's23a': balance(2, 20), 's23b': balance(1, 10),
        's25a': balance(2, 40), 's25b': balance(1, 10),
        'spec_jan': [{'item': 'BENCH_A', 'property': 'BENCH_P1', 'qty': 1}],
        'spec_feb': [{'item': 'BENCH_A', 'property': 'BENCH_P1', 'qty': 2}],
    }}}


class OperationalPeriodicity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = Path(self.tmp.name)
        (self.src / 'InformationRegisters').mkdir()
        self.xml('Policy', 'Year')
        self.xml('Spec', 'Day')

    def tearDown(self):
        self.tmp.cleanup()

    def xml(self, name, period):
        (self.src / 'InformationRegisters' / (name + '.xml')).write_text(
            '<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses"><InformationRegister>'
            '<Properties><Name>' + name + '</Name><InformationRegisterPeriodicity>' + period +
            '</InformationRegisterPeriodicity></Properties></InformationRegister></MetaDataObject>', encoding='utf-8')

    def assess(self, data=None):
        static = ou.static_signs(self.src, binding())
        return {r['id']: r for r in ou.compare(observations() if data is None else data, binding(), static)}

    def test_matching_periodicity_and_history(self):
        results = self.assess()
        self.assertEqual(results['OU03']['verdict'], 'pass')
        self.assertIn('годовая периодичность', results['OU03']['reason'])
        self.assertEqual(results['OU08']['verdict'], 'pass')
        self.assertIn('недел', results['OU08']['reason'])
        self.assertEqual(results['OU08']['coverage'], 'history_and_periodicity')

    def test_other_periodicity_is_not_an_unproved_penalty(self):
        self.xml('Policy', 'Day'); self.xml('Spec', 'Second')
        results = self.assess()
        for rule, actual in [('OU03', 'Day'), ('OU08', 'Second')]:
            self.assertEqual(results[rule]['verdict'], 'inconclusive')
            self.assertIn(actual, results[rule]['reason'])

    def test_missing_metadata_and_observations_are_inconclusive(self):
        (self.src / 'InformationRegisters/Policy.xml').unlink()
        results = self.assess({})
        self.assertEqual(results['OU03']['verdict'], 'inconclusive')
        self.assertIn('Недостаточно данных', results['OU03']['reason'])
        self.assertEqual(results['OU08']['verdict'], 'inconclusive')

    def test_proved_history_failure_is_not_hidden_by_unknown_period(self):
        self.xml('Spec', 'Second')
        data = observations(); data['ou_history']['snapshots']['spec_feb'][0]['qty'] = 9
        self.assertEqual(self.assess(data)['OU08']['verdict'], 'fail')

    def test_periodicity_calibration_is_part_of_runtime_fingerprint(self):
        from exam_bench.common import runtime_fingerprint
        self.assertIn('calibration_periodicity.py', runtime_fingerprint())


if __name__ == '__main__':
    unittest.main()
