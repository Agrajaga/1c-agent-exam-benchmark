import unittest

from tools.grading_compatibility import changed_grading_files

OLD = 'eedabc75fca0faa434f40a1624b71419ec7dc22e2854a0886cf84b4911db8372'
NEW = '5bae98af6e2021e2718afa3a71ed04bee812deaae31a43d4e7324814139ccc82'


class GradingCompatibility(unittest.TestCase):
    def test_exempts_only_the_proved_directional_hash_pair(self):
        old = {'claude.py': OLD, 'grader.py': 'same'}
        current = {'claude.py': NEW, 'grader.py': 'same'}
        self.assertEqual(changed_grading_files(old, current), [])
        self.assertEqual(changed_grading_files(current, old), ['claude.py'])
        self.assertEqual(changed_grading_files(old, {**current, 'claude.py': 'future'}), ['claude.py'])
        self.assertEqual(changed_grading_files({'claude.py': 'unrelated'}, current), ['claude.py', 'grader.py'])
        self.assertEqual(changed_grading_files(old, {**current, 'grader.py': 'changed'}), ['grader.py'])
        self.assertEqual(changed_grading_files(old, {'grader.py': 'same'}), ['claude.py'])


if __name__ == '__main__':
    unittest.main()
