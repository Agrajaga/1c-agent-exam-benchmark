import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from exam_bench.common import digest
from tools.reassess_ou_periodicity import check_inputs, reassess, replace_ou_rules, semantic_symbols, verify_scope


def assessment():
    return {'findings': [], 'statuses': {'F1C-GEN01': {'status': 'no_violation_found'}},
            'gates': {'OU': 'not_attested'}, 'score': {'charges': []}}


class Scope(unittest.TestCase):
    def test_scenario_code_changes_are_rejected(self):
        old = 'CASES = {"x": 1}\ndef static_signs(): return {}\ndef compare(): return []\n'
        change_only_comparison = 'CASES = {"x": 1}\ndef static_signs(): return {"period": 1}\ndef compare(): return [1]\n'
        changed_scenario = 'CASES = {"x": 2}\ndef static_signs(): return {}\ndef compare(): return []\n'
        self.assertEqual(semantic_symbols(old), semantic_symbols(change_only_comparison))
        self.assertNotEqual(semantic_symbols(old), semantic_symbols(changed_scenario))

    def test_scope_allows_only_targeted_requirement_findings(self):
        old = assessment(); new = copy.deepcopy(old)
        finding = {'penalty_id': 'F1C-GEN01', 'defect_id': 'requirement.OU08', 'reason': 'x'}
        new['findings'].append(finding)
        new['score']['charges'].append({'penalty_id': 'F1C-GEN01', 'defect_id': 'requirement.OU08', 'points': '0.5'})
        self.assertEqual(verify_scope(old, new), {'changed_findings': 1, 'changed_charges': 1})
        new['findings'][0]['defect_id'] = 'requirement.BU01'
        with self.assertRaises(ValueError): verify_scope(old, new)

    def test_unrelated_status_or_attestation_is_never_replayed(self):
        old = assessment(); new = copy.deepcopy(old)
        new['statuses']['F1C-BU01'] = {'status': 'violation'}
        with self.assertRaises(ValueError): verify_scope(old, new)
        new = copy.deepcopy(old); new['gates']['OU'] = 'passed'
        with self.assertRaises(ValueError): verify_scope(old, new)

    def test_unrelated_charge_is_refused_independently_of_findings(self):
        old = assessment(); new = copy.deepcopy(old)
        new['score']['charges'].append({'penalty_id': 'F1C-GEN12', 'defect_id': 'code.other', 'points': '0.25'})
        with self.assertRaisesRegex(ValueError, 'unrelated charge'): verify_scope(old, new)

    def test_changed_observer_is_refused_even_if_file_is_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / 'exam_bench').mkdir()
            (root / 'exam_bench/ou.py').write_text('CASES={"test": 2}\ndef static_signs(): pass\ndef compare(): pass')
            previous = b'CASES={"test": 1}\ndef static_signs(): pass\ndef compare(): pass'
            with patch('tools.reassess_ou_periodicity.git_file', return_value=previous):
                with self.assertRaisesRegex(ValueError, 'observer or scenario'):
                    check_inputs(root, 'revision', {'ou.py': 'old'}, {'ou.py': 'new'})

    def test_changed_frozen_sources_refuse_replay_before_assessment(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); folder = root / 'community/results/example'
            folder.mkdir(parents=True); (folder / 'manifest.json').write_text('{}')
            local = root / '.local'; local.mkdir()
            old = {'submission_id': 'example', 'original_manifest_sha256': digest(folder / 'manifest.json'),
                   'rules': [], 'errors': {}}
            grade = {'source_manifest': {'original.xml': 'original'}, 'rules': [], 'errors': {}}
            prior = local / 'old.json'; prior.write_text(json.dumps(old))
            observations = local / 'grade.json'; observations.write_text(json.dumps(grade))
            with patch('tools.demo_runner.prerequisites', return_value=({}, {'periodicity_calibration': {'passed': True}})), \
                 patch('tools.reassess_ou_periodicity.validate_bundle'), \
                 patch('tools.reassess_ou_periodicity.tree_manifest', return_value={'changed.xml': 'different'}), \
                 patch('tools.reassess_ou_periodicity.historical_modules') as history:
                with self.assertRaisesRegex(ValueError, 'Source or observations'):
                    reassess('example', prior, observations, 'revision', local / 'out', root=root)
                history.assert_not_called()

    def test_replay_reproduces_previous_rules_and_only_updates_two_targets(self):
        old = [{'id': 'OU03', 'verdict': 'pass'}, {'id': 'OU08', 'verdict': 'pass'}, {'id': 'OU02', 'verdict': 'pass'}]
        new = copy.deepcopy(old); new[1]['verdict'] = 'inconclusive'
        original = [{'id': 'BU01', 'verdict': 'pass'}, *old]
        class Historical:
            def check(self, *_): return True
            def static_signs(self, *_): return {}
            def compare(self, *_): return old
        with patch('tools.reassess_ou_periodicity.ou.static_signs', return_value={}), \
             patch('tools.reassess_ou_periodicity.ou.compare', return_value=new):
            actual, changed = replace_ou_rules(original, Historical(), Path('.'), {'ou': {'x': 1}}, {})
            self.assertEqual(changed, ['OU08'])
            self.assertEqual(actual, [original[0], *new])
            original[-1] = {'id': 'OU02', 'verdict': 'fail'}
            with self.assertRaisesRegex(ValueError, 'cannot be reproduced'):
                replace_ou_rules(original, Historical(), Path('.'), {'ou': {'x': 1}}, {})

    def test_replay_refuses_changes_to_other_ou_rules(self):
        old = [{'id': 'OU08', 'verdict': 'pass'}, {'id': 'OU02', 'verdict': 'pass'}]
        new = copy.deepcopy(old); new[1]['verdict'] = 'fail'
        class Historical:
            def check(self, *_): return True
            def static_signs(self, *_): return {}
            def compare(self, *_): return old
        with patch('tools.reassess_ou_periodicity.ou.static_signs', return_value={}), \
             patch('tools.reassess_ou_periodicity.ou.compare', return_value=new):
            with self.assertRaisesRegex(ValueError, 'Unrelated OU rule'):
                replace_ou_rules(old, Historical(), Path('.'), {'ou': {'x': 1}}, {})


if __name__ == '__main__':
    unittest.main()
