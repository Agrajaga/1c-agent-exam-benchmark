import json
import tempfile
import unittest
from pathlib import Path

from exam_bench.calcwrite import rewrites
from exam_bench.examiner import course, signs, standards

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / 'rules/1c-specialist-platform/examiner.json'


class Solution:
    """A minimal accrual: a document with movements in a calculation register and the calculation code."""

    def __init__(self, root):
        self.root = Path(root)

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8-sig')

    def make(self, posting='Deny', query='ЕСТЬNULL(Д.ЗначениеФактическийПериодДействия, 0) КАК Часы ИЗ РегистрРасчета.Начисления.ДанныеГрафика(Регистратор = &Р) КАК Д',
             predefined=True, common=True, write='Записать(, Истина)'):
        self.write('CalculationRegisters/Начисления.xml', '<CalculationRegister><ActionPeriod>true</ActionPeriod>'
                   '<ChartOfCalculationTypes>ChartOfCalculationTypes.Виды</ChartOfCalculationTypes></CalculationRegister>')
        self.write('ChartsOfCalculationTypes/Виды/Ext/Predefined.xml', '<Item id="1"><Name>Оклад</Name></Item>' if predefined else '')
        self.write('Documents/Начисление.xml', '<Document><RealTimePosting>%s</RealTimePosting>'
                   '<RegisterRecords><xr:Item>CalculationRegister.Начисления</xr:Item></RegisterRecords></Document>' % posting)
        self.write('Documents/Начисление/Ext/ObjectModule.bsl', 'Процедура ОбработкаПроведения(Отказ)\n Движения.Начисления.Записать();\n'
                   ' Расчет.Рассчитать(Движения.Начисления, Ссылка);\nКонецПроцедуры\n')
        calc = ('Процедура Рассчитать(Набор, Р) Экспорт\n Запрос = Новый Запрос("ВЫБРАТЬ Д.НомерСтроки, %s");\n'
                ' Для Каждого З Из Набор Цикл З.Результат = 1; КонецЦикла;\n Набор.%s;\nКонецПроцедуры\n') % (query, write)
        self.write('CommonModules/Расчет/Ext/Module.bsl' if common else 'Documents/Начисление/Ext/ManagerModule.bsl', calc)


class ExaminerPractices(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.solution = Solution(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def states(self, **kw):
        self.solution.make(**kw)
        return {k: v[0] for k, v in signs(self.solution.root).items()}

    def test_the_examiners_way_is_clean(self):
        self.assertEqual(set(self.states().values()), {'no_violation_found'})
        self.assertEqual(rewrites(self.solution.root), [])

    def test_each_practice(self):
        cases = {'EXM01': dict(posting='Allow'),
                 'EXM02': dict(query='ЕСТЬNULL(Д.ЗначениеФактическийПериодДействия, 0) КАК Часы ИЗ РегистрРасчета.Начисления.ДанныеГрафика КАК Д'),
                 'EXM03': dict(query='Д.ЗначениеФактическийПериодДействия КАК Часы ИЗ РегистрРасчета.Начисления.ДанныеГрафика(Регистратор = &Р) КАК Д'),
                 'EXM04': dict(predefined=False), 'EXM05': dict(common=False)}
        for practice, kw in cases.items():
            with self.subTest(practice):
                self.tmp.cleanup(); self.tmp = tempfile.TemporaryDirectory(); self.solution = Solution(self.tmp.name)
                states = self.states(**kw)
                self.assertEqual({k for k, v in states.items() if v == 'violation'}, {practice})

    def test_plain_rewrite_after_calculation(self):
        self.solution.make(write='Записать()')
        self.assertEqual([(t, s) for _, _, t, s in rewrites(self.solution.root)], [('Начисления', 'Набор.Записать()')])
        for write in ('Записать(, Истина)', 'Записать(Истина, , Ложь)'):
            self.solution.make(write=write)
            self.assertEqual(rewrites(self.solution.root), [], write)

    def test_course_practices(self):
        self.solution.make()
        self.assertEqual({k: v[0] for k, v in course(self.solution.root).items()}, {'CHS01': 'no_violation_found', 'CHS02': 'no_violation_found', 'CHS03': 'no_violation_found'})
        self.solution.write('Documents/Начисление.xml', '<Document><Attribute uuid="1"><Properties><Name>Комментарий</Name></Properties></Attribute></Document>')
        self.solution.write('Documents/Начисление/Ext/ObjectModule.bsl', 'Процедура ПриЗаписи(Отказ)\n Комментарий = "x";\nКонецПроцедуры\n'
                            'Процедура Р()\n Дни = (З.БазовыйПериодКонец - З.БазовыйПериодНачало) / 86400;\nКонецПроцедуры\n')
        self.assertEqual({k: v[0] for k, v in course(self.solution.root).items()}, {'CHS01': 'violation', 'CHS02': 'violation', 'CHS03': 'no_violation_found'})

    def test_calculation_method_attribute_replaces_predefined_types(self):
        self.solution.make(predefined=False)
        self.assertEqual(signs(self.solution.root)['EXM04'][0], 'violation')
        self.solution.write('ChartsOfCalculationTypes/Виды.xml', '<ChartOfCalculationTypes><Attribute uuid="1"><Properties><Name>СпособРасчета</Name>'
                            '<Type><v8:Type>cfg:EnumRef.СпособыРасчета</v8:Type></Type></Properties></Attribute></ChartOfCalculationTypes>')
        self.assertEqual(signs(self.solution.root)['EXM04'][0], 'no_violation_found')

    def test_composite_field_dereferenced_without_cast(self):
        self.solution.make()
        self.solution.write('InformationRegisters/Цены.xml', '<InformationRegister><Dimension uuid="1"><Properties><Name>Объект</Name><Type>'
                            '<v8:Type>cfg:CatalogRef.А</v8:Type><v8:Type>cfg:CatalogRef.Б</v8:Type></Type></Properties></Dimension></InformationRegister>')
        module = 'CommonModules/Цены/Ext/Module.bsl'
        self.solution.write(module, 'Запрос = Новый Запрос("ВЫБРАТЬ Ц.Объект.Код КАК Код ИЗ РегистрСведений.Цены КАК Ц");')
        self.assertEqual(course(self.solution.root)['CHS03'][0], 'violation')
        self.solution.write(module, 'Запрос = Новый Запрос("ВЫБРАТЬ ВЫРАЗИТЬ(Ц.Объект КАК Справочник.А).Код КАК Код ИЗ РегистрСведений.Цены КАК Ц");')
        self.assertEqual(course(self.solution.root)['CHS03'][0], 'no_violation_found')

    def test_read_only_registers_without_a_shared_lock(self):
        self.solution.make()
        self.solution.write('CommonModules/Расчет/Ext/Module.bsl', 'Процедура П()\n З = Новый Запрос("ВЫБРАТЬ С.Ставка ИЗ РегистрСведений.Ставки.СрезПоследних(&Д, ) КАК С");\nКонецПроцедуры\n')
        self.assertEqual(standards(self.solution.root)['STD01'][0], 'violation')
        self.solution.write('CommonModules/Расчет/Ext/Module.bsl', 'Процедура П()\n Б = Новый БлокировкаДанных; Э = Б.Добавить("РегистрСведений.Ставки"); Э.Режим = РежимБлокировкиДанных.Разделяемый; Б.Заблокировать();\n'
                            ' З = Новый Запрос("ВЫБРАТЬ С.Ставка ИЗ РегистрСведений.Ставки.СрезПоследних(&Д, ) КАК С");\nКонецПроцедуры\n')
        self.assertEqual(standards(self.solution.root)['STD01'][0], 'no_violation_found')

    def test_no_calculation_registers(self):
        self.assertEqual({v[0] for v in signs(self.solution.root).values()}, {'not_assessed'})


class Catalogue(unittest.TestCase):
    def test_every_practice_has_a_time_code_and_the_checked_ones_a_detector(self):
        book = json.loads(CATALOGUE.read_text(encoding='utf-8'))
        self.assertIn('Белоусов', book['source']['speaker'])
        self.assertTrue(book['source']['url'].startswith('https://www.youtube.com/watch?v='))
        with tempfile.TemporaryDirectory() as tmp:
            Solution(tmp).make()
            detected = set(signs(tmp))
        for item in book['items']:
            self.assertTrue(item['at'], item['id'])
            if item['check']['readiness'] == 'ready' and not item['related_rules'] == ['PR14']:
                self.assertIn(item['id'], detected)



class Charged(unittest.TestCase):
    def test_practice_violations_are_charged_under_their_items(self):
        from exam_bench.penalties import PRACTICE_PENALTIES, assess
        task = ROOT / 'tasks/1c-platform-official-sample'
        with tempfile.TemporaryDirectory() as tmp:
            Solution(tmp).make(posting='Allow')
            (Path(tmp) / 'Configuration.xml').write_text('<Configuration><DataLockControlMode>Managed</DataLockControlMode></Configuration>')
            result = assess([], tmp, {}, json.loads((task / 'checks.json').read_text())['requirements'], None,
                            json.loads((task / 'private/official-assessment-mapping.json').read_text()),
                            json.loads((task / 'private/owner-scoring-policy.json').read_text()))
        charged = {(f['penalty_id'], f['defect_id']) for f in result['findings']}
        self.assertIn((PRACTICE_PENALTIES['EXM01'], 'practice.EXM01'), charged)
        self.assertEqual(PRACTICE_PENALTIES['EXM01'], 'F1C-GEN28')


if __name__ == '__main__':
    unittest.main()

