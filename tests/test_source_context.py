import tempfile
import unittest
from pathlib import Path

from tools.source_context import contexts, metadata_context, code_context
from tools.community_results import export_public, read, write
from exam_bench.common import tree_manifest
from test_community_results import fixture


class SourceContextTest(unittest.TestCase):
    def test_method_uses_saved_evidence_and_ignores_keywords_in_strings(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td)
            p = src / 'CommonModules/Example/Ext/Module.bsl'
            p.parent.mkdir(parents=True)
            p.write_text('Процедура Работа()\n Текст = "КонецПроцедуры";\n Запрос.Выполнить();\nКонецПроцедуры\n', encoding='utf-8')
            charge = {'id': 'F1C-GEN20', 'reason': 'данные базы читаются в цикле'}
            evidence = {'findings': [{'penalty_id': charge['id'], 'reason': charge['reason'],
                                      'evidence': [{'file': 'CommonModules/Example/Ext/Module.bsl', 'line': 3}]}]}
            view = contexts(src, [charge], evidence)['charges'][0]['contexts'][0]
            self.assertEqual(view['method'], 'Работа')
            self.assertEqual(view['marked_line'], 3)
            self.assertEqual(view['lines'][-1], 'КонецПроцедуры')
            self.assertIn('Запрос.Выполнить()', view['lines'][2])

    def test_metadata_property_and_absent_property_are_distinguished(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td)
            p = src / 'AccountingRegisters/Ledger.xml'; p.parent.mkdir(parents=True)
            p.write_text('<MetaDataObject>\n<AccountingRegister>\n<Properties><Name>Ledger</Name></Properties>\n'
                         '<ChildObjects><Resource><Properties>\n<Name>Количество</Name>\n<Balance>true</Balance>\n'
                         '</Properties></Resource></ChildObjects>\n</AccountingRegister>\n</MetaDataObject>', encoding='utf-8')
            view = metadata_context(src, 'AccountingRegisters/Ledger.xml', 'Balance', 'Количество')
            self.assertEqual(view['tree'][-1]['value'], 'true')
            self.assertIn('<Balance>true</Balance>', view['lines'][view['marked_line'] - view['start_line']])
            missing = metadata_context(src, 'AccountingRegisters/Ledger.xml', 'AccountingFlag', 'Количество')
            self.assertEqual(missing['tree'][-1]['value'], 'не задано')
            self.assertTrue(missing['tree'][-1]['marked'])
            self.assertIsNone(metadata_context(src, 'AccountingRegisters/Ledger.xml', 'Balance', 'Другой'))

    def test_unmatched_proof_and_outside_paths_are_never_attributed(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'src'; src.mkdir()
            (src.parent / 'secret.bsl').write_text('secret', encoding='utf-8')
            self.assertIsNone(code_context(src, '../secret.bsl', 1))
            self.assertIsNone(code_context(src, 'C:/secret.bsl', 1))
            charge = {'id': 'F1C-GEN20', 'reason': 'другая ошибка'}
            evidence = {'findings': [{'penalty_id': charge['id'], 'reason': 'старая ошибка',
                                      'evidence': [{'file': '../secret.bsl', 'line': 1}]}]}
            self.assertEqual(contexts(src, [charge], evidence)['charges'][0]['contexts'], [])

    def test_location_in_diagnostic_works_for_older_owner_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td); p = src / 'Documents/Doc/Ext/ObjectModule.bsl'; p.parent.mkdir(parents=True)
            p.write_text('Процедура Печать()\n Ошибка();\nКонецПроцедуры\n', encoding='utf-8')
            charge = {'id': 'F1C-GEN12', 'reason': 'Documents/Doc/Ext/ObjectModule.bsl:2 — ошибка'}
            view = contexts(src, [charge])['charges'][0]['contexts'][0]
            self.assertEqual(view['marked_line'], 2)
            self.assertEqual(view['method'], 'Печать')

    def test_published_context_is_bound_to_frozen_result(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); folder = fixture(root)
            source = folder / 'src/CommonModules/Example/Ext/Module.bsl'
            source.parent.mkdir(parents=True)
            source.write_text('Процедура Работа()\n Запрос.Выполнить();\nКонецПроцедуры\n', encoding='utf-8')
            charge = {'id': 'F1C-GEN20', 'points': '1', 'reason': 'чтение в цикле'}
            write(folder / 'evaluation.json', {'run_id': folder.name, 'score': None,
                                               'score_upper_bound': '4', 'charges': [charge]})
            write(folder / 'assessment.json', {'findings': [{'penalty_id': charge['id'], 'reason': charge['reason'],
                  'evidence': [{'file': 'CommonModules/Example/Ext/Module.bsl', 'line': 2}]}]})
            manifest = read(folder / 'manifest.json')
            manifest['files'] = {k: v for k, v in tree_manifest(folder).items() if k != 'manifest.json'}
            write(folder / 'manifest.json', manifest)
            before = tree_manifest(folder)
            export_public(root, root / 'dist')
            row = read(root / 'dist/community.json')['results'][0]
            view = read(root / 'dist' / row['source_context'])['charges'][0]['contexts'][0]
            self.assertEqual((view['method'], view['marked_line']), ('Работа', 2))
            self.assertEqual(tree_manifest(folder), before)

    def test_accounting_dimensions_are_shown_only_when_named_in_diagnostic(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td); path = src / 'AccountingRegisters/Ledger.xml'; path.parent.mkdir()
            path.write_text('<MetaDataObject><AccountingRegister><Properties><Name>Ledger</Name></Properties>'
                            '<ChildObjects><Dimension><Properties><Name>Склад</Name></Properties></Dimension>'
                            '</ChildObjects></AccountingRegister></MetaDataObject>', encoding='utf-8')
            charge = {'id': 'F1C-BU05', 'reason': 'аналитика счетов вынесена в измерения регистра бухгалтерии и есть у всех счетов: Склад (Склады)'}
            result = contexts(src, [charge], binding={'objects': {'ledger': 'AccountingRegister.Ledger'}})
            self.assertEqual(result['charges'][0]['contexts'][0]['tree'][-2]['label'], 'Измерение · Склад')

    def test_contradictory_metadata_is_not_presented_as_proof(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td); path = src / 'Documents/Doc.xml'; path.parent.mkdir()
            path.write_text('<MetaDataObject><Document><Properties><Name>Doc</Name>'
                            '<RealTimePosting>Deny</RealTimePosting></Properties></Document></MetaDataObject>', encoding='utf-8')
            charge = {'id': 'F1C-GEN28', 'reason': 'оперативное проведение разрешено у документов с движениями по регистрам расчёта: Doc'}
            self.assertEqual(contexts(src, [charge])['charges'][0]['contexts'], [])
