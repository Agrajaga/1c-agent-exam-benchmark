import json
import shutil
import tempfile
import unittest
from pathlib import Path
from exam_bench.gates import starter_origin

ROOT = Path(__file__).parents[1]
STARTER_SRC = ROOT / '.local/environment-verified-v1/src-2'


@unittest.skipUnless(STARTER_SRC.is_dir(), 'starter export required')
class StarterOriginTest(unittest.TestCase):
    def setUp(self):
        self.starter = json.loads((ROOT / 'starters/carcass-8.3.25.1445/starter.json').read_text())

    def test_starter_itself_passes(self):
        self.assertTrue(starter_origin(STARTER_SRC, self.starter)['passed'])

    def test_foreign_configuration_fails_but_removed_objects_are_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'src'; shutil.copytree(STARTER_SRC, src)
            removed = next((src / 'Catalogs').glob('*.xml')); removed.unlink()
            result = starter_origin(src, self.starter)
            self.assertTrue(result['passed'])  # М1.5 allows changing the starter structure
            self.assertEqual(len(result['starter_objects_missing']), 1)
            xml = src / 'Configuration.xml'
            xml.write_text(xml.read_text(encoding='utf-8-sig').replace(self.starter['configuration_uuid'], '00000000-0000-0000-0000-000000000000'), encoding='utf-8')
            self.assertFalse(starter_origin(src, self.starter)['passed'])


if __name__ == '__main__':
    unittest.main()


class ClientsGate(unittest.TestCase):
    def test_compile_errors_in_client_contexts_fail_the_gate(self):
        from unittest import mock
        from exam_bench import gates
        from exam_bench.platform import PlatformError
        with tempfile.TemporaryDirectory() as tmp:
            def failing(self, argv, label, confined=None):
                (Path(tmp) / 'clients/platform/001-check-clients.platform.log').write_text(
                    '﻿{ОбщийМодуль.НаКлиенте.Модуль(2,17)}: Тип не определен (Запрос)\n\tЗапрос = Новый <<?>>Запрос; (Проверка: Тонкий клиент)\n', encoding='utf-8')
                raise PlatformError('check-clients: platform failed')
            with mock.patch.object(gates.OneC, 'command', failing):
                result = gates.clients_gate(Path(tmp) / 'ib', '/bin/true', Path(tmp) / 'clients')
            self.assertEqual(result['status'], 'not_compiled')
            self.assertEqual(result['errors'], ['{ОбщийМодуль.НаКлиенте.Модуль(2,17)}: Тип не определен (Запрос)'])
            with mock.patch.object(gates.OneC, 'command', lambda *a, **k: {'exit_code': 0}):
                self.assertEqual(gates.clients_gate(Path(tmp) / 'ib', '/bin/true', Path(tmp) / 'ok')['status'], 'compiles')
