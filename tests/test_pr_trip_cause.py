import unittest
from decimal import Decimal

from exam_bench.pr import CASES, compare, model


class TripRateCause(unittest.TestCase):
    def verdicts(self, amount):
        observations = {'pr_trip': {'errors': {}, 'posted': {'trip': True},
            'snapshots': {'results': [{'employee': 'BENCH_E4',
                'department': 'BENCH_B', 'role': 'trip', 'amount': str(amount)}]}}}
        return {r['id']: r['verdict'] for r in compare(observations, {})}

    def test_wrong_window_at_original_posting_is_rate_error(self):
        data = CASES['pr_trip']
        index = next(i for i, step in enumerate(data['steps'])
                     if step[0] == 'doc' and any(row[0] == 'trip' for row in step[3]))
        prefix = dict(data, steps=data['steps'][:index + 1])
        amount = sum((v for (e, d, r, m), v in model(prefix, previous=(2, 1, 0)).items()
                      if e == 'E4' and d == 'B' and r == 'trip'), Decimal(0))
        rules = self.verdicts(amount.quantize(Decimal('0.01')))
        self.assertEqual(rules['PR11'], 'pass')
        self.assertEqual(rules['PR12'], 'fail')

    def test_unexplained_amount_remains_one_defect(self):
        rules = self.verdicts(Decimal('1234567.89'))
        self.assertEqual(rules['PR11'], 'fail')
        self.assertEqual(rules['PR12'], 'inconclusive')
