import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def read(name):
    return json.loads((ROOT/name).read_text(encoding='utf-8'))


class MethodologyPolicy(unittest.TestCase):
    def test_all_official_applicabilities_match_the_current_ticket(self):
        ticket=read('tasks/1c-platform-official-sample/checks.json')
        catalogue=read('tasks/1c-platform-official-sample/private/official-assessment-mapping.json')
        applies={r['rule_id']:r['applicability'] for r in ticket['official_rules']}
        self.assertEqual(len(catalogue['items']),75)
        for item in catalogue['items']:
            self.assertEqual(applies[item['id'].removeprefix('F1C-')],item['applicability'],item['id'])
        for rule in ticket['official_rules']:
            if rule['rule_id'] in ('GEN03','GEN09','GEN10','GEN24'):
                self.assertNotIn('максим',rule['ticket_check'])

    def test_practices_and_gate_consequences_are_explicit_without_an_extra_charge(self):
        book=read('rules/1c-specialist-platform/rules.json')
        rules={r['id']:r for r in book['rules']}
        for name in ('GATE-MECHANISMS','GATE-LOCKS'):
            self.assertEqual(rules[name]['stand_effect']['kind'],'penalty')
        self.assertNotIn('stand_effect',rules['GATE-CLIENTS'])
        practices=read('rules/1c-specialist-platform/examiner.json')['items']
        exm=next(x for x in practices if x['id']=='EXM06')
        self.assertEqual(exm['penalty_via'],'PR14')
        self.assertNotIn('penalty',exm)
        chs=next(x for x in read('rules/1c-specialist-platform/chistov.json')['items'] if x['id']=='CHS03')
        self.assertNotIn('без штрафа',chs['check']['how'])
        self.assertEqual(chs['penalty']['rule'],'GEN01')

    @unittest.skipUnless(shutil.which('node'),'Node.js required')
    def test_browser_policy_display(self):
        result=subprocess.run(['node','--test','tests/test_scoring_display.mjs'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
