import copy
import json
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from exam_bench.common import digest, tree_manifest
from exam_bench.docx_text import words
from exam_bench.materials import (render_methods, DEFAULT_PROMPT, INPUT_REVISION, METHODS_REF,
                                 POLICY_REF, delivery_metadata, extract_methods,
                                 render_policy, verify_delivery_plan)

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / 'tasks/1c-platform-official-sample'


class OpenExamMaterialsTest(unittest.TestCase):
    def plan(self):
        return {**json.loads((ROOT/'profiles/codex-probe-plan.json').read_text()),
                **delivery_metadata(TASK), 'public_inputs': tree_manifest(TASK/'public')}

    @unittest.skipUnless((ROOT/'.local/sources/ATT83PL.txt').is_file() and (ROOT/'.local/documents/ATT83PL.docx').is_file(), 'Original official sources are in the transfer archive, outside Git')
    def test_preface_is_exact_and_has_all_published_penalties_without_sample(self):
        text = (TASK/METHODS_REF).read_text()
        source = (ROOT/'.local/sources/ATT83PL.txt').read_text()
        # Same official words; only the layout differs (tables drawn with ASCII borders from the Word document).
        self.assertEqual(text, render_methods(ROOT/'.local/documents/ATT83PL.docx', source))
        self.assertEqual(Counter(words(text)), Counter(words(extract_methods(source))))
        self.assertNotIn('Примеры заданий:', text)
        catalogue = json.loads((TASK/'private/official-assessment-mapping.json').read_text())
        # Every official penalty's source words survive the rendering.
        penalties = catalogue['items']
        self.assertEqual(len(penalties), 75)
        for penalty in penalties:
            begin, end = penalty['source']['lines']
            self.assertLessEqual(end, 278)
            source_lines = source.splitlines()
            self.assertFalse(Counter(words('\n'.join(source_lines[begin-1:end]))) - Counter(words(text)))
        self.assertIn('Получение данных графика через таблицу регистра сведений', text)

    def test_unknown_extraction_boundary_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'boundary'):
            extract_methods('Changed source\nПримеры заданий:\n')

    def test_public_policy_matches_decisions_and_explicitly_distinguishes_authority(self):
        policy = json.loads((TASK/'private/owner-scoring-policy.json').read_text())
        execution = json.loads((ROOT/'profiles/ai-exam-execution-policy.json').read_text())
        text = (TASK/POLICY_REF).read_text()
        self.assertEqual(text, render_policy(policy, execution))
        for expected in ('основная серия — 5 часов', 'быстрая серия — 30 минут', '3.5 ≤ балл < 4.5',
                         '4.5 ≤ балл ≤ 5', 'Один дефект — один штраф', 'по нижней границе диапазона',
                         'не новая редакция официальной методики'):
            self.assertIn(expected, text)
        self.assertNotIn('PR-TRIP', text)  # No private fixture IDs or numeric oracles.
        mutated = copy.deepcopy(policy)
        mutated['range_selection'] = 'maximum'
        with self.assertRaisesRegex(ValueError, 'renderer'):
            render_policy(mutated, execution)

    def test_old_plan_or_changed_guidance_cannot_be_started_as_new_revision(self):
        plan = self.plan()
        verify_delivery_plan(plan, TASK)
        del plan['input_revision']
        with self.assertRaisesRegex(ValueError, 'new plan'):
            verify_delivery_plan(plan, TASK)
        with tempfile.TemporaryDirectory() as td:
            clone = Path(td)/'task';shutil.copytree(TASK, clone)
            (clone/METHODS_REF).write_text('modified criteria')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                verify_delivery_plan(self.plan(), clone)

    def test_worker_gets_guidance_in_all_harnesses_without_private_acceptance_plan(self):
        from exam_bench.codex import prepare
        for harness in ('none', 'unica-0.13.0', 'unica-0.12.3', 'shirokov-skills'):
            with self.subTest(harness=harness), tempfile.TemporaryDirectory() as td:
                directory = Path(td);starter = directory/'starter';starter.mkdir()
                (starter/'Configuration.xml').write_text('<fixture/>')
                auth = directory/'dummy-auth.json';auth.write_text('{}')
                plan = {**self.plan(), 'harness': harness}
                # No native runtime, model call or user credentials are needed to verify delivery.
                with patch('exam_bench.codex.configure', return_value=({}, '')), \
                     patch('exam_bench.codex.verify', return_value={'isolated': True}), \
                     patch('exam_bench.codex.require_execution_mode', return_value='macos'), \
                     patch('exam_bench.codex.settings', return_value={'isolation':'macos'}), \
                     patch('exam_bench.codex.is_unica', return_value=False):
                    ws, argv, env, inputs = prepare(plan, directory/'run', starter, TASK,
                                                   Path('/fake-client'), auth)
                try:
                    for ref in (METHODS_REF, POLICY_REF):
                        name = 'task/'+ref.removeprefix('public/')
                        self.assertEqual(inputs[name], digest(TASK/ref))
                        self.assertEqual((ws/name).read_bytes(), (TASK/ref).read_bytes())
                        self.assertIn(name, DEFAULT_PROMPT)
                    self.assertFalse((ws/'task/private').exists())
                    worker = json.loads((ws/'worker.json').read_text())
                    self.assertEqual(worker['input_revision'], INPUT_REVISION)
                    self.assertTrue(worker['methodical_requirements_disclosed'])
                    self.assertNotIn('acceptance_profile', worker)
                finally:
                    shutil.rmtree(ws)

    def test_new_materials_make_a_different_comparison_cohort(self):
        from tools.build_result_site import cohort_key
        new = self.plan();old = copy.deepcopy(new)
        for ref in (METHODS_REF, POLICY_REF):
            old['public_inputs'].pop(ref.removeprefix('public/'))
        old.pop('input_revision');old.pop('methodical_requirements_disclosed')
        self.assertNotEqual(cohort_key(new, 'environment'), cohort_key(old, 'environment'))
