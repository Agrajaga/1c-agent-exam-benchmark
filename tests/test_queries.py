import tempfile
import unittest
from pathlib import Path

from exam_bench import queries

MODULE = '''Процедура Пример()
	Запрос = Новый Запрос;
	Запрос.Текст =
	"ВЫБРАТЬ
	|	Т.Поле КАК Поле
	|ИЗ
	|	Справочник.Склады КАК Т";
	Сообщить("ВЫБРАТЬ — не запрос, это часть сообщения" + Строка(1));
	Запрос.Текст = "ВЫБРАТЬ Т.Поле ИЗ Справочник.Склады КАК Т ГДЕ " + Условие;
	Запрос.Текст = Запрос.Текст + "
	|ВЫБРАТЬ 2";
	Запрос = Новый Запрос("УНИЧТОЖИТЬ ВТ");
	Текст = "Сумма";
	Сообщить("Выбрать склад");
КонецПроцедуры
'''


class QueryTexts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = Path(self.tmp.name)
        path = self.src / 'CommonModules/Запросы/Ext/Module.bsl'
        path.parent.mkdir(parents=True)
        path.write_text(MODULE, encoding='utf-8-sig')
        observer = self.src / 'CommonModules/BenchmarkObserver/Ext/Module.bsl'
        observer.parent.mkdir(parents=True)
        observer.write_text('Запрос = Новый Запрос("ВЫБРАТЬ 1");', encoding='utf-8-sig')

    def tearDown(self):
        self.tmp.cleanup()

    def test_complete_literals_are_checked_concatenated_ones_are_reported(self):
        found, skipped = queries.extract(self.src)
        self.assertEqual([(q['line'], q['text'].split()[0]) for q in found], [(4, 'ВЫБРАТЬ'), (12, 'УНИЧТОЖИТЬ')])
        self.assertEqual(found[0]['text'], 'ВЫБРАТЬ\n\tТ.Поле КАК Поле\nИЗ\n\tСправочник.Склады КАК Т')
        # A message that starts like a query but is concatenated is reported as unchecked, never parsed.
        self.assertEqual([q['line'] for q in skipped], [8, 9, 10])
        self.assertEqual({q['file'] for q in skipped}, {'CommonModules/Запросы/Ext/Module.bsl'})

    def test_observer_code_keeps_text_and_order(self):
        code = queries.code(self.src)
        self.assertIn('Текст = "ВЫБРАТЬ" + Символы.ПС + "	Т.Поле КАК Поле" + Символы.ПС + "ИЗ"', code)
        self.assertIn('Новый Структура("index,error,schema,schema_error", 1, ""', code)
        self.assertNotIn('ВЫБРАТЬ 1', code)  # the observer's own module is never a solution query

    def test_verdicts(self):
        observation = {'checked': [{'index': 0, 'error': '{(4, 2)}: Поле не найдено "Т.Поле"\nТ.<<?>>Поле КАК Поле'},
                                   {'index': 1, 'error': '{(1, 12)}: Таблица не найдена "ВТ"\nУНИЧТОЖИТЬ <<?>>ВТ'}]}
        checked, skipped = queries.verdicts(self.src, observation)
        self.assertEqual([q['status'] for q in checked], ['error', 'unresolved_temp_table'])
        self.assertEqual(queries.message(checked[0]['error']), 'Поле не найдено "Т.Поле"')
        self.assertEqual([q['status'] for q in queries.verdicts(self.src, {})[0]], ['not_observed', 'not_observed'])

    def test_table_parameter_field_error_is_unresolved_but_other_errors_are_not_hidden(self):
        path = self.src / 'CommonModules/Запросы/Ext/Module.bsl'
        path.write_text('''Процедура Тест()
Запрос = Новый Запрос("ВЫБРАТЬ Сотрудник ПОМЕСТИТЬ ВТ ИЗ &Периоды КАК Т");
Запрос = Новый Запрос("ВЫБРАТЬ НетТакогоПоля ПОМЕСТИТЬ ВТ ИЗ &Периоды КАК Т");
Запрос = Новый Запрос("ВЫБРАТЬ ИЗ &Периоды КАК Т");
Запрос = Новый Запрос("ВЫБРАТЬ Т.Нет ИЗ Справочник.Склады КАК Т");
КонецПроцедуры''', encoding='utf-8')
        observation = {'checked': [{'index': 0, 'error': 'Поле не найдено "Сотрудник"'},
                                   {'index': 1, 'error': 'Поле не найдено "НетТакогоПоля"'},
                                   {'index': 2, 'error': 'Синтаксическая ошибка'},
                                   {'index': 3, 'error': 'Поле не найдено "Т.Нет"'}]}
        result, _ = queries.verdicts(self.src, observation)
        self.assertEqual([x['status'] for x in result],
                         ['unresolved_parameter_schema', 'unresolved_parameter_schema', 'error', 'error'])


if __name__ == '__main__':
    unittest.main()
