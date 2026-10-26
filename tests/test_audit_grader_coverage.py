import unittest
from tools.audit_grader_coverage import audit, read, BOOK, TICKET


class CoverageAudit(unittest.TestCase):
    def test_report_distinguishes_existing_checks_from_incomplete_targets(self):
        result = audit(read(BOOK), read(TICKET))
        cases = {r['id']: r for r in result['discrepancies']}
        self.assertIn('GEN15', cases)
        self.assertEqual(cases['GEN15']['target_coverage'], 'not_implemented')
        self.assertIn('индекс', cases['GEN15']['implemented_description'].lower())
        self.assertEqual({r['id'] for r in result['partial_requirements']}, {'OU03', 'OU08', 'BU02', 'F04'})

    def test_old_calibration_is_not_presented_as_current(self):
        book, ticket = read(BOOK), read(TICKET)
        result = audit(book, ticket, {'accepted': True, 'implementation_files': {'a': 'old'},
                                     'query_parameter_calibration': {'passed': True}}, {'a': 'new'})
        self.assertTrue(result['native_calibration']['accepted'])
        self.assertFalse(result['native_calibration']['current_grader'])
        self.assertTrue(result['native_calibration']['query_parameter_passed'])


if __name__ == '__main__':
    unittest.main()
