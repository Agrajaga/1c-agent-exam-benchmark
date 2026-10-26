"""Calibrate proposed service entry contract on 1C; no finding about submission UI use.

Synthetic fixtures expose two documented exported server procedures. The
underlying checks compare actual saved records, including refusal and correction.
Calling a declared service does not prove that the application's UI uses it.
"""
import argparse
import hashlib
import json
import uuid
from pathlib import Path

from . import calibration_frequency as frequency
from .calibration import generate
from .common import digest, tree_manifest, write_json
from .observer import inject, MD
from .platform import OneC
from .workspaces import case_workspace


def install_entry(source):
    """Install an ordinary exported API in control fixtures only."""
    source = Path(source)
    name = 'BenchFrequencyInput'
    path = source / 'Configuration.xml'
    text = path.read_text(encoding='utf-8-sig')
    if '</ChildObjects>' not in text:
        raise ValueError('Unsupported configuration XML layout')
    path.write_text(text.replace('</ChildObjects>', f'<CommonModule>{name}</CommonModule></ChildObjects>', 1), encoding='utf-8')
    root = source / 'CommonModules'
    root.mkdir(exist_ok=True)
    (root / (name + '.xml')).write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="{MD}" xmlns:v8="http://v8.1c.ru/8.1/data/core" version="2.17">
<CommonModule uuid="{uuid.uuid4()}"><Properties><Name>{name}</Name><Synonym/><Comment/>
<Global>false</Global><ClientManagedApplication>false</ClientManagedApplication><Server>true</Server>
<ExternalConnection>false</ExternalConnection><ClientOrdinaryApplication>false</ClientOrdinaryApplication>
<ServerCall>true</ServerCall><Privileged>false</Privileged><ReturnValuesReuse>DontUse</ReturnValuesReuse>
</Properties></CommonModule></MetaDataObject>''', encoding='utf-8')
    path = root / name / 'Ext' / 'Module.bsl'
    path.parent.mkdir(parents=True)
    path.write_text('''Процедура Policy(Отдел, Период, Метод) Экспорт
 МЗ = РегистрыСведений.BenchPolicies.СоздатьМенеджерЗаписи(); МЗ.Период = Период;
 МЗ.Department = Отдел; МЗ.Method = Метод; МЗ.Записать();
КонецПроцедуры
Процедура Specification(Блок, Период, Строки) Экспорт
 Набор = РегистрыСведений.BenchSpecs.СоздатьНаборЗаписей();
 Набор.Отбор.Block.Установить(Блок); Набор.Отбор.Период.Установить(Период);
 Для Каждого Данные Из Строки Цикл
  Р = Набор.Добавить(); Р.Период = Период; Р.Block = Блок;
  Р.Item = Данные.Item; Р.Property = Данные.Property; Р.Qty = Данные.Quantity;
 КонецЦикла;
 Набор.Записать();
КонецПроцедуры
''', encoding='utf-8')
    return {'policy': f'CommonModule.{name}.Policy', 'specification': f'CommonModule.{name}.Specification'}


def observer():
    """Use service methods while retaining independently queried database snapshots."""
    code = frequency.observer()
    code = code.replace(' Ответ.Вставить("s_mixed_batch", ЗаписьДвухПериодов(Товары, Свойства));\n', '')
    mixed = code.index('Функция ЗаписьДвухПериодов(')
    start = code.index('Функция ЗаписьПолитики(')
    code = code[:mixed] + code[start:]
    start = code.index('Функция ЗаписьПолитики(')
    end = code.index('Функция СнимокПолитики(')
    wrappers = '''Функция ЗаписьПолитики(Отдел, Период, Метод)
 Попытка BenchFrequencyInput.Policy(Отдел, Период, Метод); Возврат "ok";
 Исключение Возврат ОписаниеОшибки(); КонецПопытки;
КонецФункции
Функция ЗаписьСостава(Товары, Свойства, Период, Количество)
 Попытка
  Строки = Новый Массив;
  Для Индекс = 1 По 2 Цикл
   Строки.Добавить(Новый Структура("Item,Property,Quantity", Товары[Индекс], Свойства[Индекс - 1], Количество + Индекс));
  КонецЦикла;
  BenchFrequencyInput.Specification(Товары[0], Период, Строки); Возврат "ok";
 Исключение Возврат ОписаниеОшибки(); КонецПопытки;
КонецФункции
'''
    return code[:start] + wrappers + code[end:]


def verify_service_controls(results):
    """Only assertions observed through the declared service; mixed-period raw writes excluded."""
    checks = frequency.verify_controls(results)
    del checks['s_mixed_batch']
    checks['year_platform_normalization'] = frequency.verify_annual(results['year_native'])
    return checks


def run(starter_source, starter_dt, binary, root):
    from .runtime import machine_identity, platform_binary, require_execution_mode
    require_execution_mode()
    if str(Path(binary).resolve()) != platform_binary():
        raise ValueError('Calibration binary must match the machine settings')
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    results = {}
    for variant in ('guarded', 'unguarded', 'year_native'):
        branch = root / variant; branch.mkdir()
        fixture = branch / 'fixture'; generate(starter_source, fixture, 'one')
        if variant != 'year_native':
            path = fixture / 'InformationRegisters/BenchPolicies.xml'
            text = path.read_text(encoding='utf-8-sig').replace('<InformationRegisterPeriodicity>Year</InformationRegisterPeriodicity>', '<InformationRegisterPeriodicity>Day</InformationRegisterPeriodicity>')
            path.write_text(text, encoding='utf-8')
        if variant == 'guarded': frequency.install_guard(fixture, 'BenchPolicies', 'Department', 'year')
        if variant in ('guarded', 'year_native'): frequency.install_guard(fixture, 'BenchSpecs', 'Block', 'week')
        paths = install_entry(fixture)
        from tools.frequency_entry_contract import validate_frequency_entries
        valid, errors = validate_frequency_entries(fixture, {'frequency_entry': paths})
        if errors or valid != paths: raise ValueError('Control service contract not validated: ' + str(errors))
        before = tree_manifest(fixture)
        evidence = branch / 'evidence'; evidence.mkdir()
        with case_workspace(evidence) as work:
            platform = OneC(binary, work / 'platform', 180)
            observed = inject(fixture, work / 'observed-src', observer())
            platform.restore(work / 'ib', starter_dt); platform.load(work / 'ib', observed)
            output = work / 'observations.json'
            platform.command(['ENTERPRISE', '/F', work / 'ib', '/C', output], 'observe', confined=work)
            results[variant] = json.loads(output.read_text(encoding='utf-8-sig'))
        if tree_manifest(fixture) != before: raise ValueError('Fixture changed during calibration')
        write_json(branch / 'result.json', results[variant])
    checks = verify_service_controls(results)
    summary = {'passed': all(checks.values()), 'checks': checks, 'observations': results,
               'entry_contract': paths, 'platform': machine_identity(), 'platform_binary_sha256': digest(binary),
               'starter_dt_sha256': digest(starter_dt), 'observer_sha256': hashlib.sha256(observer().encode('utf-8')).hexdigest(),
               'grading_status': 'not_assessed', 'reason': 'Service invocation alone does not prove that the UI uses this service'}
    write_json(root / 'summary.json', summary)
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True); p.add_argument('--starter', required=True)
    p.add_argument('--binary', required=True); p.add_argument('--output', required=True)
    a = p.parse_args()
    summary = run(a.source, a.starter, a.binary, a.output)
    print(json.dumps(summary, ensure_ascii=False))
    if not summary['passed']: raise SystemExit(1)
