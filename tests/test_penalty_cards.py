import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools import build_result_site
from tools.community_results import export_public, write
from exam_bench.common import tree_manifest
from test_community_results import fixture


class PenaltyPresentation(unittest.TestCase):
    def test_display_metadata_contains_titles_but_no_grader_oracle(self):
        export = getattr(build_result_site, 'penalty_metadata', None)
        self.assertTrue(callable(export), 'The site needs a separate presentation catalogue')
        source = {'rulebooks': {'b': {'rules': [{'id': 'GEN01', 'title': 'Rule', 'number': 'М4.1',
                  'stand_check': {'how': 'private expected amount 1680'}}]}},
                  'tickets': [{'requirements': [{'id': 'BU13', 'title': 'Requirement', 'number': 'Т3.13',
                  'stand': {'how': 'expected amount 26'}}]}]}
        before = json.dumps(source)
        self.assertEqual(export(source), {'rules': {'GEN01': {'title': 'Rule', 'number': 'М4.1'}},
                                         'requirements': {'BU13': {'title': 'Requirement', 'number': 'Т3.13'}}})
        self.assertEqual(json.dumps(source), before)

    def test_ambiguous_ids_do_not_get_a_title_from_the_wrong_ticket(self):
        export = getattr(build_result_site, 'penalty_metadata', None)
        self.assertTrue(callable(export), 'The site needs a separate presentation catalogue')
        source = {'rulebooks': {}, 'tickets': [
            {'requirements': [{'id': 'BU13', 'title': 'First', 'number': 'Т3.13'}]},
            {'requirements': [{'id': 'BU13', 'title': 'Other', 'number': 'Т3.13'}]}]}
        self.assertEqual(export(source)['requirements'], {})

    def test_public_result_and_download_keep_original_evaluation_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = fixture(root)
            evaluation = {'run_id': 'demo-test', 'score': None, 'score_upper_bound': '4.5',
                          'charges': [{'id': 'F1C-GEN01', 'points': '0.5',
                                       'reason': 'не выполнено требование: BU13'}]}
            write(folder / 'evaluation.json', evaluation)
            write(folder / 'assessment.json', {'original': 'неизменная диагностика'})
            manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
            manifest['files'] = {k: v for k, v in tree_manifest(folder).items() if k != 'manifest.json'}
            write(folder / 'manifest.json', manifest)
            stage = root / 'dist'
            stage.mkdir()
            export_public(root, stage)
            published = json.loads((stage / 'community.json').read_text(encoding='utf-8'))['results'][0]
            self.assertEqual(published['result'], evaluation)
            with zipfile.ZipFile(stage / published['download']) as archive:
                for name in ('evaluation.json', 'assessment.json', 'manifest.json'):
                    self.assertEqual(archive.read(name), (folder / name).read_bytes())

    @unittest.skipUnless(shutil.which('node'), 'Node.js is needed for browser presenter unit tests')
    def test_browser_presenter(self):
        result = subprocess.run(['node', '--test', 'tests/test_penalty_cards.mjs'],
                                cwd=build_result_site.ROOT, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
