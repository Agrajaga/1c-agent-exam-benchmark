import unittest
from unittest.mock import patch

from tools.reassess_community import check_input_changes, verify_scope


class ReassessmentScopeTests(unittest.TestCase):
    def test_rejects_unrelated_grader_change(self):
        with self.assertRaises(ValueError):
            check_input_changes({'grader.py': 'old'}, {'grader.py': 'new'})

    def test_accepts_only_the_proved_query_penalty_removal(self):
        finding = {'penalty_id': 'F1C-GEN12', 'defect_id': 'code.query.module:4'}
        charge = {**finding, 'points': 0.25}
        old = {'findings': [finding], 'statuses': {'F1C-GEN12': 'violation'}, 'score': {'charges': [charge]}}
        new = {'findings': [], 'statuses': {'F1C-GEN12': 'not_assessed'}, 'score': {'charges': []}}
        verdict = [{'file': 'module', 'line': 4, 'status': 'unresolved_parameter_schema'}]
        with patch('tools.reassess_community.queries.verdicts', return_value=(verdict, None)):
            self.assertEqual(verify_scope(old, new, None, {}), {'removed_findings': 1, 'removed_charges': 1})
            new['statuses']['unrelated'] = 'changed'
            with self.assertRaises(ValueError):
                verify_scope(old, new, None, {})


if __name__ == '__main__':
    unittest.main()
