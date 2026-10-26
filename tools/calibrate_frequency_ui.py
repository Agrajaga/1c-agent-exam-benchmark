"""Diagnostic 1C standard-form control, not an assessment of submitted solutions.

Runs positive and negative fixture configurations in clean databases. Opens the
platform's default record forms programmatically; this alone does not prove that
a user's solution exposes those forms, provides permissions or uses that entry path.
"""
import argparse
import hashlib
import json
from pathlib import Path

from exam_bench.calibration import generate
from exam_bench.calibration_frequency import install_guard
from exam_bench.common import digest, tree_manifest, write_json
from exam_bench.grader import HELPERS_CORE
from exam_bench.observer import inject
from exam_bench.platform import OneC
from exam_bench.runtime import machine_identity, platform_binary, require_execution_mode
from exam_bench.workspaces import case_workspace


def server_code():
    return '''Функция Run() Экспорт
 Авто = Новый Массив;
 Эл = Справочники.Подразделения.СоздатьЭлемент(); Эл.Наименование = "FREQ_FormDep"; Эл.УстановитьНовыйКод(); ЗаполнитьОбязательные(Эл, Неопределено, Неопределено, Авто); Эл.Записать();
 Товары = Новый Массив;
 Для Каждого Имя Из СтрРазделить("Block,A,B", ",") Цикл
  Т = Справочники.Номенклатура.СоздатьЭлемент(); Т.Наименование = "FREQ_Form" + Имя; Т.УстановитьНовыйКод(); ЗаполнитьОбязательные(Т, Неопределено, Неопределено, Авто); Т.Записать(); Товары.Добавить(Т.Ссылка);
 КонецЦикла;
 Для Индекс = 1 По 2 Цикл
  Х = Справочники.BenchProperties.СоздатьЭлемент(); Х.Наименование = "FREQ_FormProperty" + Формат(Индекс, "ЧГ=0"); Х.Item = Товары[Индекс]; Х.УстановитьНовыйКод(); ЗаполнитьОбязательные(Х, Неопределено, Неопределено, Авто); Х.Записать();
 КонецЦикла;
 Возврат Новый Структура("seed", "ok");
КонецФункции
Функция Dept() Экспорт
 Возврат Справочники.Подразделения.НайтиПоНаименованию("FREQ_FormDep", Истина);
КонецФункции
Функция Policy() Экспорт
 Возврат Перечисления.УчетнаяПолитика.ФИФО;
КонецФункции
Функция Item(Имя) Экспорт
 Возврат Справочники.Номенклатура.НайтиПоНаименованию("FREQ_Form" + Имя, Истина);
КонецФункции
Функция Property(Индекс) Экспорт
 Возврат Справочники.BenchProperties.НайтиПоНаименованию("FREQ_FormProperty" + Формат(Индекс, "ЧГ=0"), Истина);
КонецФункции
Функция PolicySnapshot() Экспорт
 З = Новый Запрос("ВЫБРАТЬ С.Период ИЗ РегистрСведений.BenchPolicies КАК С ГДЕ С.Department = &Отдел УПОРЯДОЧИТЬ ПО С.Период"); З.УстановитьПараметр("Отдел", Dept());
 Рез = Новый Массив; Для Каждого С Из З.Выполнить().Выгрузить() Цикл Рез.Добавить(Формат(С.Период, "ДФ=yyyy-MM-dd")); КонецЦикла; Возврат Рез;
КонецФункции
Функция SpecSnapshot() Экспорт
 З = Новый Запрос("ВЫБРАТЬ С.Период, С.Item, С.Qty ИЗ РегистрСведений.BenchSpecs КАК С ГДЕ С.Block = &Блок УПОРЯДОЧИТЬ ПО С.Период, С.Item"); З.УстановитьПараметр("Блок", Item("Block"));
 Рез = Новый Массив; Для Каждого С Из З.Выполнить().Выгрузить() Цикл Рез.Добавить(Новый Структура("date,item,qty", Формат(С.Период, "ДФ=yyyy-MM-dd"), Строка(С.Item), С.Qty)); КонецЦикла; Возврат Рез;
КонецФункции
''' + HELPERS_CORE


def client_code():
    return '''Процедура ClientRun(Результат)
 Попытка
  Форма = ПолучитьФорму("РегистрСведений.BenchSpecs.ФормаЗаписи");
  Элементы = Новый Массив;
  Для Каждого Э Из Форма.Элементы Цикл
   Попытка Элементы.Добавить(Новый Структура("name,visible,enabled", Э.Имя, Э.Видимость, Э.Доступность)); Исключение КонецПопытки;
  КонецЦикла;
  Результат.Вставить("elements", Элементы);
 Исключение Результат.Вставить("elements_error", ОписаниеОшибки()); КонецПопытки;
 Даты = Новый Массив; Даты.Добавить(Дата(2025,1,1)); Даты.Добавить(Дата(2025,6,1)); Даты.Добавить(Дата(2026,1,1));
 Отчет = Новый Массив;
 Для Каждого Д Из Даты Цикл
  Попытка
   Ф = ПолучитьФорму("РегистрСведений.BenchPolicies.ФормаЗаписи");
   Ф.Запись.Период = Д; Ф.Запись.Department = BenchmarkObserver.Dept(); Ф.Запись.Method = BenchmarkObserver.Policy();
   Р = Ф.Записать(); Если Р Тогда Отчет.Добавить("ok"); Иначе Отчет.Добавить("not_written"); КонецЕсли;
  Исключение Отчет.Добавить(ОписаниеОшибки()); КонецПопытки;
 КонецЦикла;
 Результат.Вставить("policy", Отчет); Результат.Вставить("policy_snapshot", BenchmarkObserver.PolicySnapshot());
 Даты = Новый Массив; Даты.Добавить(Дата(2025,12,30)); Даты.Добавить(Дата(2026,1,1)); Даты.Добавить(Дата(2026,1,5));
 Отчет = Новый Массив;
 Для Каждого Д Из Даты Цикл
  Для Индекс = 1 По 2 Цикл
   Попытка
    Ф = ПолучитьФорму("РегистрСведений.BenchSpecs.ФормаЗаписи");
    Ф.Запись.Период = Д; Ф.Запись.Block = BenchmarkObserver.Item("Block");
    Ф.Запись.Item = BenchmarkObserver.Item(?(Индекс = 1, "A", "B")); Ф.Запись.Property = BenchmarkObserver.Property(Индекс); Ф.Запись.Qty = Индекс;
    Р = Ф.Записать(); Если Р Тогда Отчет.Добавить("ok"); Иначе Отчет.Добавить("not_written"); КонецЕсли;
   Исключение Отчет.Добавить(ОписаниеОшибки()); КонецПопытки;
  КонецЦикла;
 КонецЦикла;
 Результат.Вставить("spec", Отчет); Результат.Вставить("spec_snapshot", BenchmarkObserver.SpecSnapshot());
КонецПроцедуры
'''


def verify_controls(results):
    good, bad = results['guarded'], results['unguarded']
    guard = lambda v: isinstance(v, str) and 'BENCH_FREQUENCY_GUARD' in v
    ok = lambda v: v == 'ok'
    gp, bp, gs, bs = good.get('policy', []), bad.get('policy', []), good.get('spec', []), bad.get('spec', [])
    rows = lambda snapshot: sorted((r.get('date'), r.get('item'), r.get('qty')) for r in snapshot)
    pair = lambda date: [(date, 'FREQ_FormA', 1), (date, 'FREQ_FormB', 2)]
    expected = sorted(pair('2025-12-30') + pair('2026-01-05'))
    all_rows = sorted(pair('2025-12-30') + pair('2026-01-01') + pair('2026-01-05'))
    fields = {r.get('name') for r in good.get('elements', []) if r.get('visible') is True and r.get('enabled') is True}
    return {'policy_outcomes': len(gp) == len(bp) == 3 and ok(gp[0]) and guard(gp[1]) and ok(gp[2]) and all(map(ok, bp)),
            'policy_snapshots': good.get('policy_snapshot') == ['2025-01-01', '2026-01-01'] and bad.get('policy_snapshot') == ['2025-01-01', '2025-06-01', '2026-01-01'],
            'spec_outcomes': len(gs) == len(bs) == 6 and all(map(ok, gs[:2] + gs[4:])) and all(map(guard, gs[2:4])) and all(map(ok, bs)),
            'spec_snapshots': rows(good.get('spec_snapshot', [])) == expected and rows(bad.get('spec_snapshot', [])) == all_rows,
            'form_elements': {'Период', 'Block', 'Item', 'Property', 'Qty', 'ФормаЗаписать'} <= fields}


def run(starter_source, starter_dt, binary, root):
    require_execution_mode()
    if str(Path(binary).resolve()) != platform_binary():
        raise ValueError('Binary must match machine settings')
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    results = {}
    for name in ('guarded', 'unguarded'):
        branch = root / name; branch.mkdir()
        fixture = branch / 'fixture'; generate(starter_source, fixture, 'one')
        p = fixture / 'InformationRegisters/BenchPolicies.xml'
        xml = p.read_text(encoding='utf-8-sig').replace('<InformationRegisterPeriodicity>Year</InformationRegisterPeriodicity>', '<InformationRegisterPeriodicity>Day</InformationRegisterPeriodicity>')
        p.write_text(xml, encoding='utf-8')
        if name == 'guarded':
            install_guard(fixture, 'BenchPolicies', 'Department', 'year')
            install_guard(fixture, 'BenchSpecs', 'Block', 'week')
        before = tree_manifest(fixture)
        evidence = branch / 'evidence'; evidence.mkdir()
        with case_workspace(evidence) as work:
            adapter = OneC(binary, work / 'platform', 180)
            observed = inject(fixture, work / 'observed-src', server_code(), client_code())
            adapter.restore(work / 'ib', starter_dt); adapter.load(work / 'ib', observed)
            output = work / 'observations.json'
            adapter.command(['ENTERPRISE', '/F', work / 'ib', '/C', output], 'observe', confined=work)
            results[name] = json.loads(output.read_text(encoding='utf-8-sig'))
        if tree_manifest(fixture) != before:
            raise ValueError('Fixture was modified during calibration')
    checks = verify_controls(results)
    summary = {'passed': all(checks.values()), 'checks': checks, 'observations': results,
               'platform': machine_identity(), 'platform_binary_sha256': digest(binary), 'starter_dt_sha256': digest(starter_dt),
               'observer_sha256': hashlib.sha256((server_code() + client_code()).encode('utf-8')).hexdigest(),
               'grading_status': 'not_assessed', 'limitations': ['Form invoked programmatically; navigation, rights and actual user access unverified', 'Separate record writes do not prove atomic composition changes']}
    write_json(root / 'summary.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True); parser.add_argument('--starter', required=True)
    parser.add_argument('--binary', required=True); parser.add_argument('--output', required=True)
    args = parser.parse_args()
    summary = run(args.source, args.starter, args.binary, args.output)
    print(json.dumps(summary, ensure_ascii=False))
    if not summary['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
