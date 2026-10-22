import json
import tempfile
import unittest
from pathlib import Path
from exam_bench.interpretations import read, compare

ROOT = Path(__file__).parents[1]
TASK = ROOT / 'tasks/1c-platform-official-sample'


class InterpretationsTest(unittest.TestCase):
    def write(self, value):
        self.td = tempfile.TemporaryDirectory(); out = Path(self.td.name)
        (out / 'interpretations.json').write_text(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
        return out

    def tearDown(self):
        if hasattr(self, 'td'): self.td.cleanup()

    def test_missing_is_recorded_not_an_error(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(read(td)['status'], 'missing')

    def test_invalid_file_is_reported(self):
        self.assertEqual(read(self.write('{broken'))['status'], 'invalid')
        self.assertEqual(read(self.write({'schema_version': 1, 'items': [{'quote': 'x'}]}))['status'], 'invalid')

    def test_empty_list_means_no_ambiguities(self):
        self.assertEqual(read(self.write({'schema_version': 1, 'items': []})), {'status': 'present', 'items': []})

    def test_agent_reading_is_matched_to_the_stand_answer(self):
        checks = json.loads((TASK / 'checks.json').read_text())
        ledger = json.loads((TASK / 'ledger.json').read_text())
        item = {'quote': 'Порядок списания аналогов определяется артикулом', 'question': 'Направление?',
                'interpretation': 'По убыванию', 'implementation': ''}
        [result] = compare([item], ledger, checks['requirements'], checks['questions'])
        self.assertIn('BU11', result['requirements'])
        self.assertEqual([q['id'] for q in result['stand_questions']], ['Q05'])
        [unknown] = compare([{**item, 'quote': 'такого текста в билете нет вовсе'}], ledger, checks['requirements'], checks['questions'])
        self.assertEqual(unknown['places'], [])


if __name__ == '__main__':
    unittest.main()
