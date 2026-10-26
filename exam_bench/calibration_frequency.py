"""Native diagnostic controls for OU03/OU08; never assigns a score to a submission.

The observer writes directly to information registers, which may bypass solution
forms and APIs. Its results therefore describe only this specific access path.
"""
import argparse
import hashlib
import json
from pathlib import Path

from .calibration import generate
from .common import digest, tree_manifest, write_json
from .grader import HELPERS_CORE
from .observer import inject
from .platform import OneC
from .workspaces import case_workspace


def install_guard(source, register, key, interval):
    """Fixture's explicit server-side guard, not injected into submitted solutions."""
    module = Path(source) / 'InformationRegisters' / register / 'Ext' / 'RecordSetModule.bsl'
    module.parent.mkdir(parents=True, exist_ok=True)
    start = 'НачалоГода(Н.Период)' if interval == 'year' else 'НачалоНедели(Н.Период)'
    end = 'ДобавитьМесяц(Начало, 12)' if interval == 'year' else 'Начало + 7 * 24 * 3600'
    module.write_text(f'''Процедура ПередЗаписью(Отказ, Замещение)
 Новые = Новый Массив;
 Для Каждого Н Из ЭтотОбъект Цикл
  Начало = {start}; Конец = {end};
  Для Каждого Другой Из Новые Цикл
   Если Другой.Ключ = Н.{key} И Другой.Период >= Начало И Другой.Период < Конец И Другой.Период <> Н.Период Тогда
    ВызватьИсключение "BENCH_FREQUENCY_GUARD";
   КонецЕсли;
  КонецЦикла;
  Новые.Добавить(Новый Структура("Ключ,Период", Н.{key}, Н.Период));
  Запрос = Новый Запрос("ВЫБРАТЬ ПЕРВЫЕ 1 С.Период ИЗ РегистрСведений.{register} КАК С ГДЕ С.{key} = &Ключ И С.Период >= &Начало И С.Период < &Конец И С.Период <> &Период");
  Запрос.УстановитьПараметр("Ключ", Н.{key}); Запрос.УстановитьПараметр("Начало", Начало);
  Запрос.УстановитьПараметр("Конец", Конец); Запрос.УстановитьПараметр("Период", Н.Период);
  Если Не Запрос.Выполнить().Пустой() Тогда ВызватьИсключение "BENCH_FREQUENCY_GUARD"; КонецЕсли;
 КонецЦикла;
КонецПроцедуры
''', encoding='utf-8')


def observer():
    # Existing reference fixture fields. A set replaces a single block/version atomically.
    return '''Функция Run() Экспорт
 Авто = Новый Массив; Ответ = Новый Структура;
 Отдел = Справочники.Подразделения.СоздатьЭлемент(); Отдел.Наименование = "FREQ_Department"; Отдел.УстановитьНовыйКод(); ЗаполнитьОбязательные(Отдел, Неопределено, Неопределено, Авто); Отдел.Записать();
 Товары = Новый Массив;
 Для Каждого Имя Из СтрРазделить("Block,A,B,BlockBatch", ",") Цикл
  Т = Справочники.Номенклатура.СоздатьЭлемент(); Т.Наименование = "FREQ_" + Имя; Т.УстановитьНовыйКод(); ЗаполнитьОбязательные(Т, Неопределено, Неопределено, Авто); Т.Записать(); Товары.Добавить(Т.Ссылка);
 КонецЦикла;
 Свойства = Новый Массив;
 Для Индекс = 1 По 2 Цикл
  Х = Справочники.BenchProperties.СоздатьЭлемент(); Х.Наименование = "FREQ_Property" + Формат(Индекс, "ЧГ=0"); Х.Item = Товары[Индекс]; Х.УстановитьНовыйКод(); ЗаполнитьОбязательные(Х, Неопределено, Неопределено, Авто); Х.Записать(); Свойства.Добавить(Х.Ссылка);
 КонецЦикла;
 Ответ.Вставить("p_initial", ЗаписьПолитики(Отдел.Ссылка, Дата(2025,1,1), Перечисления.УчетнаяПолитика.ФИФО));
 Ответ.Вставить("p_correction", ЗаписьПолитики(Отдел.Ссылка, Дата(2025,1,1), Перечисления.УчетнаяПолитика.ЛИФО));
 Ответ.Вставить("p_same_year", ЗаписьПолитики(Отдел.Ссылка, Дата(2025,6,1), Перечисления.УчетнаяПолитика.ФИФО));
 Ответ.Вставить("p_next_year", ЗаписьПолитики(Отдел.Ссылка, Дата(2026,1,1), Перечисления.УчетнаяПолитика.ЛИФО));
 Ответ.Вставить("s_initial", ЗаписьСостава(Товары, Свойства, Дата(2025,12,30), 1));
 Ответ.Вставить("s_correction", ЗаписьСостава(Товары, Свойства, Дата(2025,12,30), 2));
 Ответ.Вставить("s_same_week", ЗаписьСостава(Товары, Свойства, Дата(2026,1,1), 3));
 Ответ.Вставить("s_next_week", ЗаписьСостава(Товары, Свойства, Дата(2026,1,5), 4));
 Ответ.Вставить("s_mixed_batch", ЗаписьДвухПериодов(Товары, Свойства));
 Ответ.Вставить("policy_records", СнимокПолитики(Отдел.Ссылка));
 Ответ.Вставить("spec_records", СнимокСостава(Товары[0]));
 Возврат Ответ;
КонецФункции
Функция ЗаписьДвухПериодов(Товары, Свойства)
 Попытка
  Набор = РегистрыСведений.BenchSpecs.СоздатьНаборЗаписей(); Набор.Отбор.Block.Установить(Товары[3]);
  Для Индекс = 1 По 2 Цикл
   Р = Набор.Добавить(); Р.Период = ?(Индекс = 1, Дата(2025,12,30), Дата(2026,1,1)); Р.Block = Товары[3]; Р.Item = Товары[Индекс]; Р.Property = Свойства[Индекс - 1]; Р.Qty = Индекс;
  КонецЦикла;
  Набор.Записать(); Возврат "ok";
 Исключение Возврат ОписаниеОшибки(); КонецПопытки;
КонецФункции
Функция ЗаписьПолитики(Отдел, Период, Метод)
 Попытка
  МЗ = РегистрыСведений.BenchPolicies.СоздатьМенеджерЗаписи(); МЗ.Период = Период; МЗ.Department = Отдел; МЗ.Method = Метод; МЗ.Записать();
  Возврат "ok";
 Исключение Возврат ОписаниеОшибки(); КонецПопытки;
КонецФункции
Функция ЗаписьСостава(Товары, Свойства, Период, Количество)
 Попытка
  Набор = РегистрыСведений.BenchSpecs.СоздатьНаборЗаписей(); Набор.Отбор.Block.Установить(Товары[0]); Набор.Отбор.Период.Установить(Период);
  Для Индекс = 1 По 2 Цикл
   Р = Набор.Добавить(); Р.Период = Период; Р.Block = Товары[0]; Р.Item = Товары[Индекс]; Р.Property = Свойства[Индекс - 1]; Р.Qty = Количество + Индекс;
  КонецЦикла;
  Набор.Записать(); Возврат "ok";
 Исключение Возврат ОписаниеОшибки(); КонецПопытки;
КонецФункции
Функция СнимокПолитики(Отдел)
 З = Новый Запрос("ВЫБРАТЬ С.Период, С.Method ИЗ РегистрСведений.BenchPolicies КАК С ГДЕ С.Department = &Отдел УПОРЯДОЧИТЬ ПО С.Период"); З.УстановитьПараметр("Отдел", Отдел);
 Рез = Новый Массив; Для Каждого С Из З.Выполнить().Выгрузить() Цикл Рез.Добавить(Новый Структура("date,method", Формат(С.Период, "ДФ=yyyy-MM-dd"), Строка(С.Method))); КонецЦикла; Возврат Рез;
КонецФункции
Функция СнимокСостава(Блок)
 З = Новый Запрос("ВЫБРАТЬ С.Период, С.Item, С.Qty ИЗ РегистрСведений.BenchSpecs КАК С ГДЕ С.Block = &Блок УПОРЯДОЧИТЬ ПО С.Период, С.Item"); З.УстановитьПараметр("Блок", Блок);
 Рез = Новый Массив; Для Каждого С Из З.Выполнить().Выгрузить() Цикл Рез.Добавить(Новый Структура("date,item,qty", Формат(С.Период, "ДФ=yyyy-MM-dd"), Строка(С.Item), С.Qty)); КонецЦикла; Возврат Рез;
КонецФункции
''' + HELPERS_CORE


def verify_controls(results):
    """Check the saved database states as well as the reported write outcomes."""
    good, bad = results['guarded'], results['unguarded']
    checks = {k: good.get(k) == 'ok' and bad.get(k) == 'ok' for k in ('p_initial','p_correction','p_next_year','s_initial','s_correction','s_next_week')}
    checks.update({k: 'BENCH_FREQUENCY_GUARD' in good.get(k, '') and bad.get(k) == 'ok' for k in ('p_same_year', 's_same_week', 's_mixed_batch')})
    policy = lambda x: sorted(r['date'] for r in x.get('policy_records', []))
    specs = lambda x: sorted((r['date'], r['item'], r['qty']) for r in x.get('spec_records', []))
    checks['guarded_policy_versions'] = policy(good) == ['2025-01-01', '2026-01-01']
    checks['unguarded_policy_versions'] = policy(bad) == ['2025-01-01', '2025-06-01', '2026-01-01']
    initial = [('2025-12-30', 'FREQ_A', 3), ('2025-12-30', 'FREQ_B', 4)]
    later = [('2026-01-05', 'FREQ_A', 5), ('2026-01-05', 'FREQ_B', 6)]
    within = [('2026-01-01', 'FREQ_A', 4), ('2026-01-01', 'FREQ_B', 5)]
    checks['guarded_atomic_rows_and_correction'] = specs(good) == sorted(initial + later)
    checks['unguarded_atomic_rows_and_correction'] = specs(bad) == sorted(initial + within + later)
    return checks


def verify_annual(annual):
    """A second date in the same year corrects the first platform period."""
    records = annual.get('policy_records', [])
    return (all(annual.get(k) == 'ok' for k in ('p_initial', 'p_correction', 'p_same_year', 'p_next_year'))
            and len(records) == 2 and [r.get('date') for r in records] == ['2025-01-01', '2026-01-01']
            and records[0].get('method') == 'FIFO' and records[1].get('method') == 'LIFO')


def run(starter_source, starter_dt, binary, root):
    from .runtime import machine_identity, platform_binary, require_execution_mode
    require_execution_mode()
    if str(Path(binary).resolve()) != platform_binary():
        raise ValueError('Calibration binary must match the machine settings')
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    results, manifests = {}, {}
    for name in ('guarded', 'unguarded', 'year_native'):
        branch = root / name; branch.mkdir()
        fixture = branch / 'fixture'; generate(starter_source, fixture, 'one')
        # Reference policy uses Year; make it Day so the explicit guard is exercised.
        if name != 'year_native':
            p = fixture / 'InformationRegisters/BenchPolicies.xml'
            xml = p.read_text(encoding='utf-8-sig').replace('<InformationRegisterPeriodicity>Year</InformationRegisterPeriodicity>', '<InformationRegisterPeriodicity>Day</InformationRegisterPeriodicity>')
            p.write_text(xml, encoding='utf-8')
        if name == 'guarded':
            install_guard(fixture, 'BenchPolicies', 'Department', 'year')
        if name in ('guarded', 'year_native'):
            install_guard(fixture, 'BenchSpecs', 'Block', 'week')
        before = tree_manifest(fixture)
        manifests[name] = hashlib.sha256(json.dumps(before, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
        evidence = branch / 'evidence'; evidence.mkdir()
        with case_workspace(evidence) as work:
            platform = OneC(binary, work / 'platform', 180)
            observed = inject(fixture, work / 'observed-src', observer())
            platform.restore(work / 'ib', starter_dt); platform.load(work / 'ib', observed)
            output = work / 'observations.json'
            platform.command(['ENTERPRISE', '/F', work / 'ib', '/C', output], 'observe', confined=work)
            results[name] = json.loads(output.read_text(encoding='utf-8-sig'))
        if tree_manifest(fixture) != before:
            raise ValueError('Fixture was modified during native calibration')
        write_json(branch / 'result.json', results[name])
    # Only the fixture's own controlled outcomes are evaluated, never a submitted solution.
    checks = verify_controls(results)
    annual = results['year_native']
    checks['year_platform_normalization'] = verify_annual(annual)
    summary = {'passed': all(checks.values()), 'checks': checks, 'observations': results,
               'platform': machine_identity(), 'platform_binary_sha256': digest(binary), 'starter_dt_sha256': digest(starter_dt),
               'observer_sha256': hashlib.sha256(observer().encode('utf-8')).hexdigest(), 'fixture_sha256': manifests,
               'grading_status': 'not_assessed', 'reason': 'Direct register writes may bypass the solution entry path'}
    write_json(root / 'summary.json', summary)
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True); p.add_argument('--starter', required=True); p.add_argument('--binary', required=True); p.add_argument('--output', required=True)
    a = p.parse_args()
    result = run(a.source, a.starter, a.binary, a.output)
    print(json.dumps(result, ensure_ascii=False))
    if not result['passed']:
        raise SystemExit(1)
