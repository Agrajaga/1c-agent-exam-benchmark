import json
import tempfile
import unittest
from pathlib import Path

from exam_bench import queryschema
from exam_bench.penalties import assess

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / 'tasks/1c-platform-official-sample'
# Schemas the platform 8.3.27 returned for synthetic query cases, recorded once (exam_bench.queries observer).
FIXTURE = json.loads((Path(__file__).parent / 'query_schema_repro.json').read_text())
EXPECTED = {
    'ИндексБезПервогоИзмерения': [('F1C-GEN15', 'РегистрНакопления.ТоварыНаСкладах.Остатки')],
    'ИтогиПоОсновнойТаблице': [('F1C-GEN14', 'РегистрНакопления.ТоварыНаСкладах')],
    # Balances read only to compare quantities, no search for negative balances: the old posting method (A18).
    'СоединениеВместоПараметра': [('F1C-GEN28', 'РегистрНакопления.ТоварыНаСкладах.Остатки'), ('F1C-GEN24', 'РегистрНакопления.ТоварыНаСкладах.Остатки')],
    'СоединениеСПараметром': [('F1C-GEN28', 'РегистрНакопления.ТоварыНаСкладах.Остатки')],
    'ЧтениеОстатковБезБлокировки': [('F1C-GEN28', 'РегистрНакопления.ТоварыНаСкладах.Остатки')],
    'ПолеБезЕстьNull': [('F1C-GEN22', 'Остатки'), ('F1C-GEN22', 'Остатки')],
    'БазаБезОтбора': [('F1C-PR09', 'РегистрРасчета.Начисления.БазаНачисления')],
}


class QuerySchemaSigns(unittest.TestCase):
    def test_each_synthetic_case(self):
        for name, schema in FIXTURE['schemas'].items():
            with self.subTest(name):
                found = [(s['penalty'], s['target']) for s in queryschema.signs(schema, FIXTURE['storage'])]
                self.assertEqual(found, EXPECTED.get(name, []))

    def test_storage_indexes_get_configuration_names(self):
        indexes = queryschema.index_lookup(FIXTURE['storage'])
        self.assertEqual(indexes[('РегистрНакопления.ТоварыНаСкладах', 'Итоги')], [['Период', 'Склад', 'Номенклатура', 'Качество']])
        self.assertIn(['Регистратор', 'НомерСтроки'], indexes[('РегистрНакопления.ТоварыНаСкладах', 'Основная')])

    def test_expression_helpers(self):
        self.assertEqual(queryschema.conjuncts('(А = 1) И (Б В (ВЫБРАТЬ 1 И 2)) И В = &В'), ['А = 1', 'Б В (ВЫБРАТЬ 1 И 2)', 'В = &В'])
        self.assertEqual(queryschema.outside_isnull('ЕСТЬNULL(Т.А, 0) + Т.Б').strip(), '+ Т.Б')
        self.assertEqual(queryschema.direct_refs('Т.Субконто2.Валюта = К.Валюта И Т.Счет = &С', 'Т'), {'Счет'})


class QuerySchemaPenalties(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = Path(self.tmp.name)
        (self.src / 'Configuration.xml').write_text('<Configuration><DataLockControlMode>Managed</DataLockControlMode></Configuration>')
        path = self.src / 'Documents/Расход/Ext/ObjectModule.bsl'
        path.parent.mkdir(parents=True)
        path.write_text('\n\nЗапрос = Новый Запрос("ВЫБРАТЬ 1 ИЗ Справочник.Склады КАК С");', encoding='utf-8-sig')

    def tearDown(self):
        self.tmp.cleanup()

    def assess(self, schema):
        observations = {'query_texts': {'checked': [{'index': 0, 'error': '', 'schema': schema, 'schema_error': ''}], 'storage': FIXTURE['storage']}}
        return assess([], self.src, {}, json.loads((TASK / 'checks.json').read_text())['requirements'], None,
                      json.loads((TASK / 'private/official-assessment-mapping.json').read_text()),
                      json.loads((TASK / 'private/owner-scoring-policy.json').read_text()), None, observations)

    def test_sign_is_a_finding_with_the_query_place(self):
        result = self.assess(FIXTURE['schemas']['СоединениеВместоПараметра'])
        finding = next(f for f in result['findings'] if f['penalty_id'] == 'F1C-GEN24')
        self.assertEqual(finding['defect_id'], 'query.Documents/Расход/Ext/ObjectModule.bsl:3.РегистрНакопления.ТоварыНаСкладах.Остатки')
        self.assertEqual(finding['proof_kind'], 'query_schema')
        self.assertEqual(result['statuses']['F1C-GEN15']['status'], 'no_violation_found')

    def test_two_signs_on_one_outer_joined_table_are_one_defect(self):
        result = self.assess(FIXTURE['schemas']['ПолеБезЕстьNull'])
        gen22 = [f for f in result['findings'] if f['penalty_id'] == 'F1C-GEN22']
        self.assertEqual(len(gen22), 2)
        self.assertEqual({f['defect_id'] for f in gen22}, {'query.Documents/Расход/Ext/ObjectModule.bsl:3.Остатки'})

    def test_clean_query_reports_its_limits(self):
        result = self.assess(FIXTURE['schemas']['СоединениеСПараметром'])
        self.assertEqual(result['statuses']['F1C-GEN24']['status'], 'no_violation_found')
        self.assertIn('структуру 1 запросов', result['statuses']['F1C-GEN24']['reason'])


if __name__ == '__main__':
    unittest.main()
