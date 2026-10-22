import unittest
from tools.compare_harness_runs import compare


class ComparableConditionsTest(unittest.TestCase):
    def test_version_specific_capability_does_not_change_common_conditions(self):
        common={'model':'gpt-6.1-sol','reasoning_effort':'medium','solve_timeout_seconds':1800,
                'statement_sha256':'unchanged','implementation_files':{'codex.py':'same'}}
        a={'plan':{**common,'harness':'unica-0.12.3','runtime_probe_ref':'runtime.json','run_id':'a'}}
        b={'plan':{**common,'harness':'shirokov-skills','run_id':'b'}}
        result=compare([a,b])
        self.assertTrue(result['same_conditions_except_harness'])
        self.assertFalse(result['model_ranking_eligible'])

    def test_different_time_budget_is_exposed(self):
        a={'plan':{'model':'gpt-6.1-sol','solve_timeout_seconds':900,'harness':'none'}}
        b={'plan':{'model':'gpt-6.1-sol','solve_timeout_seconds':1800,'harness':'unica-0.12.3'}}
        result=compare([a,b])
        self.assertFalse(result['same_conditions_except_harness'])
        self.assertEqual(result['different_condition_fields'],['solve_timeout_seconds'])
