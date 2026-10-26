import contextlib
import copy
import unittest

import test_penalties as fixtures
from exam_bench.codescan import scan
from exam_bench.examiner import course


@contextlib.contextmanager
def solution():
    t = fixtures.Penalties(); t.setUp()
    try:
        yield t
    finally:
        t.tearDown()


def module(t, text):
    p = t.src/'CommonModules/Учет/Ext/Module.bsl'; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('Процедура П()\n'+text+'\nКонецПроцедуры', encoding='utf-8')


def rules(t, **overrides):
    t.binding.update(ou={'objects': {}}, pr={'objects': {}}, forms={'objects': {}})
    return [{'id': r['id'], 'verdict': overrides.get(r['id'], 'pass')} for r in t.requirements]


class IssueRegressions(unittest.TestCase):
    def test_29_exception_branch_does_not_read_repeatedly_but_message_branch_does(self):
        with solution() as t:
            for expression in ('Выборка.Ссылка', 'Строка(Выборка.Ссылка)'):
                module(t, 'Пока Выборка.Следующий() Цикл\nЕсли Выборка.Количество = 0 Тогда\nВызватьИсключение "Не хватает " + '+expression+';\nКонецЕсли;\nКонецЦикла;')
                self.assertFalse(scan(t.src, t.binding)['loop_reads'])
            module(t, 'Пока Выборка.Следующий() Цикл\nСообщить("Не хватает " + Выборка.Ссылка);\nКонецЦикла;')
            self.assertTrue(scan(t.src, t.binding)['loop_reads'])

    def test_31_one_mechanism_defect_one_minimum_charge_independent_defects_remain(self):
        with solution() as t:
            for name in ('OU04', 'F03', 'PR14'):
                charges = t.run_with(rules(t, **{name: 'fail'}))['score']['charges']
                self.assertEqual([(x['defect_id'], x['points']) for x in charges], [('requirement.'+name, '0.5')])
            charges = t.run_with(rules(t, OU04='fail', F03='fail'))['score']['charges']
            self.assertEqual(len(charges), 2)

    def test_32_write_then_read_is_safe_without_a_dummy_lock_and_read_then_write_is_not(self):
        with solution() as t:
            query = 'З = Новый Запрос("ВЫБРАТЬ О.КоличествоОстаток ИЗ РегистрНакопления.Т.Остатки(&М, ) КАК О"); З.Выполнить();'
            for dummy in ('', 'Б = Новый БлокировкаДанных;'):
                module(t, dummy+'\nДвижения.Т.Записать();\n'+query)
                self.assertFalse([x for x in t.run_with(rules(t))['score']['charges'] if x['penalty_id']=='F1C-GEN29'])
            module(t, query+'\nДвижения.Т.Записать();')
            self.assertTrue([x for x in t.run_with(rules(t))['score']['charges'] if x['penalty_id']=='F1C-GEN29'])

    def test_33_types_belong_to_the_query_source_and_alias_scope(self):
        with solution() as t:
            for name, types in (('Составной', ['А','Б']), ('Простой', ['А'])):
                p = t.src/f'InformationRegisters/{name}.xml'; p.parent.mkdir(exist_ok=True)
                p.write_text('<InformationRegister><Attribute uuid="a"><Properties><Name>Объект</Name><Type>'+''.join('<v8:Type>cfg:CatalogRef.'+x+'</v8:Type>' for x in types)+'</Type></Properties></Attribute></InformationRegister>', encoding='utf-8')
            module(t, 'З = Новый Запрос("ВЫБРАТЬ Т.Объект.Код ИЗ РегистрСведений.Простой КАК Т");')
            self.assertEqual(course(t.src)['CHS03'][0], 'no_violation_found')
            module(t, 'З = Новый Запрос("ВЫБРАТЬ Т.Объект.Код ИЗ РегистрСведений.Составной КАК Т");\nЗ = Новый Запрос("ВЫБРАТЬ Т.Объект.Код ИЗ РегистрСведений.Простой КАК Т");')
            self.assertEqual(course(t.src)['CHS03'][0], 'violation')
            module(t, 'З = Новый Запрос("ВЫБРАТЬ ВЫРАЗИТЬ(Т.Объект КАК Справочник.А).Код ИЗ РегистрСведений.Составной КАК Т");')
            self.assertEqual(course(t.src)['CHS03'][0], 'no_violation_found')

    def test_33_registrar_type_is_scoped_to_its_register(self):
        with solution() as t:
            for name in ('Один','Два'):
                p=t.src/f'InformationRegisters/{name}.xml';p.parent.mkdir(exist_ok=True);p.write_text('<InformationRegister/>')
            (t.src/'Documents/А.xml').write_text('<xr:Item>InformationRegister.Один</xr:Item><xr:Item>InformationRegister.Два</xr:Item>',encoding='utf-8')
            (t.src/'Documents/Б.xml').write_text('<xr:Item>InformationRegister.Два</xr:Item>',encoding='utf-8')
            for name, expected in [('Один','no_violation_found'),('Два','violation')]:
                module(t,f'З = Новый Запрос("ВЫБРАТЬ т.регистратор.Код ИЗ РегистрСведений.{name} КАК т");')
                self.assertEqual(course(t.src)['CHS03'][0],expected)

    def test_34_pr10_only_where_the_ticket_permits_recalculation(self):
        with solution() as t:
            p=t.src/'CalculationRegisters/Начисления/Recalculations/Перерасчет.xml';p.parent.mkdir(parents=True);p.write_text('<Recalculation/>')
            (t.src/'CalculationRegisters/Начисления.xml').write_text('<CalculationRegister><ChartOfCalculationTypes>ChartOfCalculationTypes.Виды</ChartOfCalculationTypes></CalculationRegister>')
            p=t.src/'ChartsOfCalculationTypes/Виды/Ext/Predefined.xml';p.parent.mkdir(parents=True)
            p.write_text('<Item id="1"><Name>Премия</Name><Base><CalculationType>Виды.Оклад</CalculationType></Base></Item>',encoding='utf-8')
            self.assertFalse([x for x in t.run_with(rules(t))['score']['charges'] if x['penalty_id']=='F1C-PR10'])
            t.policy=copy.deepcopy(t.policy); t.policy['recalculation']['current_task_mode']='required'
            for entry in t.catalogue['items']:
                if entry['id']=='F1C-PR10':entry['applicability']='conditional'
            self.assertTrue([x for x in t.run_with(rules(t))['score']['charges'] if x['penalty_id']=='F1C-PR10'])

    def test_52_memory_rows_are_not_reference_reads_and_proved_references_still_are(self):
        with solution() as t:
            module(t, 'Партии = Остатки.НайтиСтроки(Отбор);\nРаспределение = Новый ТаблицаЗначений;\nДля Каждого П Из Партии Цикл\nР = Распределение.Добавить();\nР.Партия = П;\nКонецЦикла;\nДля Каждого Р Из Распределение Цикл\nР.Количество = Р.Партия.Количество;\nКонецЦикла;')
            self.assertEqual(t.run_with(rules(t))['statuses']['F1C-GEN20']['status'], 'no_violation_found')
            p=t.src/'InformationRegisters/Строки.xml';p.parent.mkdir(exist_ok=True)
            p.write_text('<InformationRegister><Dimension uuid="a"><Properties><Name>Товар</Name><Type><v8:Type>cfg:CatalogRef.Товары</v8:Type></Type></Properties></Dimension></InformationRegister>',encoding='utf-8')
            module(t, 'З = Новый Запрос("ВЫБРАТЬ Т.Товар ИЗ РегистрСведений.Строки КАК Т");\nВыборка = З.Выполнить().Выбрать();\nПока Выборка.Следующий() Цикл\nИмя = Выборка.Товар.Наименование;\nКонецЦикла;')
            self.assertTrue(scan(t.src,t.binding)['loop_reads'])

    def test_53_current_totals_with_filter_are_not_empty_parameters(self):
        with solution() as t:
            for table, args in [('РегистрНакопления.Т.Остатки',' , Товар В (&Товары)'), ('РегистрБухгалтерии.У.Остатки',', Счет = &Счет, &Виды, Субконто1 В (&Товары)')]:
                module(t, f'З = Новый Запрос("ВЫБРАТЬ О.КоличествоОстаток ИЗ {table}({args}) КАК О ГДЕ О.КоличествоОстаток < 0");')
                self.assertFalse(scan(t.src,t.binding)['empty_virtual_parameters'])
            module(t, 'З = Новый Запрос("ВЫБРАТЬ * ИЗ РегистрНакопления.Т.Остатки(, ) КАК О");')
            self.assertTrue(scan(t.src,t.binding)['empty_virtual_parameters'])

    def test_53_dimension_filter_in_where_is_still_detected(self):
        with solution() as t:
            p=t.src/'AccumulationRegisters/Т.xml';p.parent.mkdir();p.write_text('<Dimension uuid="x"><Properties><Name>Товар</Name></Properties></Dimension>',encoding='utf-8')
            module(t,'З = Новый Запрос("ВЫБРАТЬ О.КоличествоОстаток ИЗ РегистрНакопления.Т.Остатки(&М, ) КАК О ГДЕ О.Товар = &Товар");')
            self.assertTrue(scan(t.src,t.binding)['where_on_dimension'])
