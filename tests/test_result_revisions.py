import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from exam_bench.common import tree_manifest
from tools.community_results import export_public, write
from test_community_results import fixture


class ResultRevisions(unittest.TestCase):
    def test_regrades_count_once_and_all_original_artifacts_remain_downloadable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = fixture(root, 'z-original')
            new = fixture(root, 'a-regrade')
            separate = fixture(root, 'another-run')
            for folder, date, bound in ((old, '2026-10-25T13:00:00+03:00', '4.5'),
                                        (new, '2026-10-25T11:00:00Z', '1.0')):
                write(folder / 'evaluation.json', {'run_id': 'original-run', 'created_at': date,
                      'score': None, 'score_upper_bound': bound, 'infrastructure_errors': folder == new})
                manifest = json.loads((folder / 'manifest.json').read_text())
                manifest['run_id'] = 'original-run'
                manifest['files'] = {k: v for k, v in tree_manifest(folder).items() if k != 'manifest.json'}
                write(folder / 'manifest.json', manifest)
            before = tree_manifest(root / 'community')
            export_public(root, root / 'dist')
            records = json.loads((root / 'dist/community.json').read_text(encoding='utf-8'))['results']
            self.assertEqual(len(records), 2)  # identical XML from a different run is still its own attempt
            current = next(r for r in records if r['run_id'] == 'original-run')
            self.assertEqual(current['id'], new.name)  # newest by instant, not score, folder name or UTC offset
            self.assertTrue(current['result']['infrastructure_errors'])
            self.assertEqual([r['id'] for r in current['previous_evaluations']], [old.name])
            revisions = [r for current in records for r in [current, *current['previous_evaluations']]]
            self.assertEqual(len(revisions), 3)
            for revision in revisions:
                folder = root / 'community/results' / revision['id']
                with zipfile.ZipFile(root / 'dist' / revision['download']) as archive:
                    for name in ('solution.dt', 'src/Configuration.xml', 'evaluation.json', 'manifest.json'):
                        self.assertEqual(archive.read(name), (folder / name).read_bytes())
            self.assertEqual(tree_manifest(root / 'community'), before)
