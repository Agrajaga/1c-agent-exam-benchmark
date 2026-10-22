import unittest
from exam_bench.pr import compare


class RecalculationVerdict(unittest.TestCase):
    def test_prohibited_recalculation_is_failed_not_inconclusive(self):
        result=next(r for r in compare({}, {}, {'recalculation_signs':['Documents/Payroll/Ext/ObjectModule.bsl']}) if r['id']=='PR14')
        self.assertEqual(result['verdict'],'fail')
        self.assertIn('recalculation signs',result['reason'])

    def test_absence_is_still_a_scoped_pass(self):
        result=next(r for r in compare({}, {}, {'recalculation_signs':[]}) if r['id']=='PR14')
        self.assertEqual(result['verdict'],'pass')
        self.assertEqual(result['coverage'],'no_violation_found')
