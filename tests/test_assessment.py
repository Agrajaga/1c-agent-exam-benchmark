"""Counterexamples for the scoped mechanism assessor and score upper bounds."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from exam_bench.assessment import payroll_findings, score_bound, tariff_runtime_findings

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'.local/runs/official-sample-sol61-none-001/artifacts/src'


@unittest.skipUnless(SOURCE.exists(), 'Frozen local corpus required for integration controls')
class MechanismControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.source = Path(self.temp.name)/'src'
        shutil.copytree(SOURCE, self.source)
        for file in self.source.rglob('*'):
            if file.is_file():
                file.chmod(0o600)
        self.path = self.source/'CommonModules/УчетЗарплаты/Ext/Module.bsl'

    def tearDown(self):
        self.temp.cleanup()

    def findings(self):
        return {f['penalty_id'] for f in payroll_findings(self.source, 'none')}

    def replace(self, old, new):
        text = self.path.read_text(encoding='utf-8-sig')
        self.assertIn(old, text)
        self.path.write_text(text.replace(old, new), encoding='utf-8')

    def test_known_invalid_mechanisms(self):
        self.assertEqual(self.findings(), {'F1C-PR06', 'F1C-GEN20'})

    def test_virtual_schedule_is_not_real_table_read(self):
        # Valid specialized data-source example; no claim it is a full runnable solution.
        self.replace('ИЗ РегистрСведений.РабочийКалендарь',
                     'ИЗ РегистрРасчета.Начисления.ДанныеГрафика')
        self.assertEqual(self.findings(), {'F1C-GEN20'})

    def test_only_iteration_of_ready_tables_does_not_trigger_db_loop(self):
        text = self.path.read_text(encoding='utf-8-sig')
        # Preserve the raw schedule read outside the loop; remove every in-loop wrapper call.
        lines = [line.replace('Учет.Таблица(', 'ГотоваяТаблица(')
                 if any(word in line for word in ('Ставки=', 'Руководители=', 'Шкала='))
                 else line for line in text.splitlines()]
        self.path.write_text('\n'.join(lines), encoding='utf-8')
        self.assertEqual(self.findings(), {'F1C-PR06'})

    def test_comments_strings_and_dead_routine_do_not_add_loop_calls(self):
        self.test_only_iteration_of_ready_tables_does_not_trigger_db_loop()
        with self.path.open('a') as file:
            file.write('\nПроцедура НеВызывается()\nДля Каждого Р Из Данные Цикл\n'
                       'Учет.Таблица("ВЫБРАТЬ * ИЗ База"); КонецЦикла; КонецПроцедуры\n')
        self.replace('Календарь=Учет.Таблица',
                     '// Для Цикл Учет.Таблица("fake"); КонецЦикла\n'
                     'Сообщить("Цикл Учет.Таблица() КонецЦикла");\nКалендарь=Учет.Таблица')
        self.assertEqual(self.findings(), {'F1C-PR06'})

    def test_cached_helper_is_unverified_not_a_violation(self):
        xml = self.source/'CommonModules/Учет.xml'
        xml.write_text(xml.read_text(encoding='utf-8-sig').replace('DontUse', 'DuringSession'))
        with self.assertRaisesRegex(ValueError, 'Cached wrapper'):
            self.findings()

    def test_no_posting_call_means_no_proven_active_route(self):
        entry = self.source/'Documents/НачислениеЗарплаты/Ext/ObjectModule.bsl'
        entry.write_text(entry.read_text(encoding='utf-8-sig').replace('УчетЗарплаты.Рассчитать(', 'ИнаяПроцедура('))
        with self.assertRaisesRegex(ValueError, 'posting route'):
            self.findings()

    def test_second_frozen_variant(self):
        source = ROOT/'.local/runs/official-sample-sol61-unica013-001/artifacts/src'
        self.assertEqual({f['penalty_id'] for f in payroll_findings(source, 'unica013')},
                         {'F1C-PR06', 'F1C-GEN20'})


class ScoringControls(unittest.TestCase):
    def setUp(self):
        private = ROOT/'tasks/1c-platform-official-sample/private'
        self.catalogue = json.loads((private/'official-assessment-mapping.json').read_text())
        self.policy = json.loads((private/'owner-scoring-policy.json').read_text())

    def test_one_defect_one_smallest_penalty_at_its_minimum(self):
        a = {'defect_id': 'same', 'penalty_id': 'F1C-GEN01'}
        b = {'defect_id': 'same', 'penalty_id': 'F1C-GEN11'}
        result = score_bound([a, a, b], self.catalogue, self.policy)
        self.assertEqual([c['penalty_id'] for c in result['charges']], ['F1C-GEN01'])  # 0.5-3.0 beats 2.0
        self.assertEqual(result['deductions'], '0.5')
        self.assertEqual(result['score_upper_bound'], '4.5')
        self.assertIsNone(result['grade'])
        self.assertIsNone(result['score'])

    def test_failure_proven_only_when_best_case_below_threshold(self):
        items = [{'defect_id': str(i), 'penalty_id': 'F1C-GEN05'} for i in range(4)]
        result = score_bound(items, self.catalogue, self.policy)
        self.assertEqual(result['score_upper_bound'], '-7.0')  # not clamped
        self.assertEqual(result['grade'], 'unsatisfactory')
        ranged = [{'defect_id': str(i), 'penalty_id': 'F1C-GEN01'} for i in range(2)]
        self.assertIsNone(score_bound(ranged, self.catalogue, self.policy)['grade'])  # 4.0 so far; unchecked rules may lower it

    def test_insufficient_coverage_cannot_claim_good_grade(self):
        self.assertIsNone(score_bound([], self.catalogue, self.policy)['grade'])

    def test_own_document_type_is_penalized_as_in_1c(self):
        result = score_bound([{'defect_id': 'doc', 'penalty_id': 'F1C-GEN33'}], self.catalogue, self.policy)
        self.assertEqual(result['deductions'], '1.0')

    def test_grade_boundaries_follow_the_document(self):
        from exam_bench.assessment import grade_for
        self.assertEqual(grade_for('2.19', self.policy), 'unsatisfactory')
        self.assertEqual(grade_for('2.2', self.policy), 'satisfactory')
        self.assertEqual(grade_for('3.5', self.policy), 'good')
        self.assertEqual(grade_for('4.5', self.policy), 'excellent')
        self.assertEqual(grade_for('5', self.policy), 'excellent')

    def test_uncalibrated_runtime_failure_adds_no_penalty(self):
        observation = {'error':'{ОбщийМодуль.УчетЗарплаты.Модуль(52)}: Поле объекта недоступно для записи (Документы)'}
        self.assertEqual(tariff_runtime_findings(observation,{},'source'),[])

    def test_observer_failure_is_not_candidate_failure(self):
        calibration = {'same_fixture':True,'sole_variable_rename':True,'positive_equal':True}
        observation = {'error':'{ОбщийМодуль.BenchmarkObserver.Модуль(52)}: Поле объекта недоступно для записи (Документы)'}
        self.assertEqual(tariff_runtime_findings(observation,calibration,'source'),[])
