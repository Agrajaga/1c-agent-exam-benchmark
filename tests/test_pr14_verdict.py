import unittest
from exam_bench.pr import compare


class RecalculationVerdict(unittest.TestCase):
    def test_code_or_metadata_alone_does_not_prove_prohibited_use(self):
        result=next(r for r in compare({}, {}, {'recalculation_signs':['Documents/Payroll/Ext/ObjectModule.bsl']}) if r['id']=='PR14')
        self.assertEqual(result['verdict'],'inconclusive')
        self.assertIn('runtime use is not established',result['reason'])

    def test_absence_is_still_a_scoped_pass(self):
        result=next(r for r in compare({}, {}, {'recalculation_signs':[]}) if r['id']=='PR14')
        self.assertEqual(result['verdict'],'pass')
        self.assertEqual(result['coverage'],'no_violation_found')
