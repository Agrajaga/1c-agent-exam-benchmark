import tempfile
import unittest
from pathlib import Path

from exam_bench.submission import strip_extras
from tools.frequency_entry_contract import validate_frequency_entries


class FrequencyEntryContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = Path(self.tmp.name)
        modules = self.src / 'CommonModules'
        modules.mkdir()
        (modules / 'Ввод.xml').write_text('<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses"><CommonModule><Properties><Name>Ввод</Name><Server>true</Server></Properties></CommonModule></MetaDataObject>', encoding='utf-8')
        self.code = modules / 'Ввод/Ext/Module.bsl'
        self.code.parent.mkdir(parents=True)
        self.code.write_text('Процедура Политика(Подразделение, Период, Знач Метод) Экспорт\nКонецПроцедуры\nПроцедура Состав(Блок, Дата, Строки) Экспорт\nКонецПроцедуры', encoding='utf-8')
        self.ou = {'frequency_entry': {'policy': 'CommonModule.Ввод.Политика', 'specification': 'CommonModule.Ввод.Состав'}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_optional_and_partial_declarations_are_accepted(self):
        self.assertEqual(validate_frequency_entries(self.src, {}), ({}, {}))
        valid, errors = validate_frequency_entries(self.src, self.ou)
        self.assertEqual(valid, self.ou['frequency_entry'])
        self.assertEqual(errors, {})
        self.ou['frequency_entry']['specification'] = 'CommonModule.Ввод.Отсутствует'
        valid, errors = validate_frequency_entries(self.src, self.ou)
        self.assertEqual(set(valid), {'policy'})
        self.assertEqual(set(errors), {'specification'})

    def test_illegal_path_and_incorrect_or_commented_signature(self):
        self.ou['frequency_entry']['policy'] = 'CommonModule.Ввод.Политика();X'
        self.assertIn('policy', validate_frequency_entries(self.src, self.ou)[1])
        self.ou['frequency_entry']['policy'] = 'CommonModule.Ввод.Политика'
        self.code.write_text('// Процедура Политика(А, Б, В) Экспорт\nПроцедура Состав(Блок, Дата) Экспорт', encoding='utf-8')
        self.assertEqual(set(validate_frequency_entries(self.src, self.ou)[1]), {'policy', 'specification'})

    def test_candidate_must_be_server_module(self):
        descriptor = self.src / 'CommonModules/Ввод.xml'
        descriptor.write_text(descriptor.read_text(encoding='utf-8').replace('<Server>true</Server>', '<Server>false</Server>'), encoding='utf-8')
        self.assertEqual(set(validate_frequency_entries(self.src, self.ou)[1]), {'policy', 'specification'})

    def test_strip_preserves_optional_section_and_validator_ignores_unknown_roles(self):
        source = {'ou': {'frequency_entry': {**self.ou['frequency_entry'], 'extra': 'arbitrary'}}}
        clean, ignored = strip_extras(source)
        self.assertEqual(clean['ou']['frequency_entry'], source['ou']['frequency_entry'])
        self.assertEqual(validate_frequency_entries(self.src, clean['ou'])[0], self.ou['frequency_entry'])
        self.assertEqual(ignored, [])


if __name__ == '__main__':
    unittest.main()
