import assert from 'node:assert/strict';
import {test} from 'node:test';

let cards;
try { cards = await import('../site/penalty-cards.js'); }
catch (error) { if (error.code !== 'ERR_MODULE_NOT_FOUND') throw error; }

const metadata = {
  rules: {GEN01: {number: 'М4.1', title: 'Полнота и обоснованность решения'},
    GEN12: {number: 'М4.12', title: 'Дефекты исполняемого кода'},
    PR14: {number: 'М7.14', title: 'Избыточная перезапись фактических периодов'}},
  requirements: {BU13: {number: 'Т3.13', title: 'Средняя по номенклатуре всей компании'},
    PR13: {number: 'Т4.13', title: 'Командировка задним числом'},
    F05: {number: 'Т5.5', title: 'Ввод и сохранение дополнительных значений'}},
};
function describe(charge, data = metadata) {
  assert.equal(typeof cards?.describeCharge, 'function', 'The structured charge presenter must exist');
  return cards.describeCharge(charge, data);
}

test('a failed requirement is named and linked to its own requirement and penalty', () => {
  const c = Object.freeze({id: 'F1C-GEN01', points: '0.5', reason: 'не выполнено требование: BU13'});
  const before = JSON.stringify(metadata);
  const d = describe(c);
  assert.match(d.title, /Средняя по номенклатуре всей компании/);
  assert.match(d.summary, /всех складах/);
  assert.equal(d.rule.id, 'GEN01');
  assert.equal(d.requirement.id, 'BU13');
  assert.equal(d.requirement.number, 'Т3.13');
  assert.equal(d.original, 'F1C-GEN01 · −0,5 · не выполнено требование: BU13');
  assert.equal(JSON.stringify(metadata), before);
});

test('tariff comparisons preserve observed and expected amounts without changing the diagnostic', () => {
  const reason = 'не выполнено требование: PR13 — pr_backdate E4/B tariff 2025-01: 2160, expected 1680.00; pr_backdate E4/B tariff 2025-02: 1920, expected 1680.00';
  const d = describe({id: 'F1C-GEN01', points: '0.5', reason});
  assert.deepEqual(d.comparisons.map(x => [x.period, x.actual, x.expected]),
    [['2025-01', '2160', '1680.00'], ['2025-02', '1920', '1680.00']]);
  assert.ok(d.original.endsWith(reason));
});

test('form success and empty values are explained only when the diagnostic proves them', () => {
  const prefix = 'не выполнено требование: F05 — ';
  const d = describe({id: 'F1C-GEN01', points: '0.5', reason: prefix + "typed ['C1', 'C2'], written True, stored [('BENCH_Валюта', ''), ('BENCH_Срок', '')]"});
  assert.match(d.summary, /Запись формы завершилась успешно/);
  assert.match(d.summary, /Валюта.*Срок/);
  const failed = describe({id: 'F1C-GEN01', points: '0.5', reason: prefix + 'written False'});
  assert.doesNotMatch(failed.summary, /завершилась успешно/);
});

test('unknown and missing metadata still show the complete original message', () => {
  const reason = '<img src=x onerror=alert(1)> неизвестная диагностика\nвторая строка';
  const d = describe({id: 'F1C-NEW01', points: '1.0', reason}, {});
  assert.equal(d.title, 'Нарушение, отмеченное стендом');
  assert.ok(d.original.endsWith(reason));
  assert.equal(d.rule, null);
  assert.deepEqual(d.comparisons, []);
});

test('locations are deduplicated for reading but the original is preserved verbatim', () => {
  const location = 'CommonModules/РасчетЗарплаты/Ext/Module.bsl:29';
  const reason = `после расчёта набор с периодом действия перезаписывается целиком, с пересчётом фактического периода действия: ${location} Набор.Записать(); ${location} Набор.Записать()`;
  const d = describe({id: 'F1C-PR14', points: '0.5', reason});
  assert.equal(d.locations.length, 1);
  assert.equal(d.locations[0], location);
  assert.ok(d.original.endsWith(reason));
});

test('unrecognized detail is not turned into fabricated actual values', () => {
  const d = describe({id: 'F1C-GEN01', points: '0.5', reason: 'не выполнено требование: PR13 — другой формат'});
  assert.deepEqual(d.comparisons, []);
  assert.match(d.original, /другой формат/);
  assert.doesNotMatch(d.summary, /1680|2160|1920/);
});

test('Cyrillic resource names get a concrete accounting explanation', () => {
  const d = describe({id: 'F1C-BU06', points: '1.5', reason: 'ресурс Количество балансовый'});
  assert.equal(d.title, 'Для ресурса «Количество» включён балансовый учёт');
  assert.match(d.summary, /настройку ресурса/);
});

test('ordinary and subconto accounting flags keep distinct explanations', () => {
  const ordinary = describe({id: 'F1C-BU06', points: '1.5',
    reason: 'признак учёта Количественный плана счетов не указан ни у одного ресурса регистра — не действует'});
  const subconto = describe({id: 'F1C-BU07', points: '1.0',
    reason: 'признак учёта субконто Суммовой заведён в плане счетов, но не указан ни у одного ресурса регистра — не действует'});
  assert.match(ordinary.summary, /не связан/);
  assert.doesNotMatch(ordinary.summary, /субконто/);
  assert.match(subconto.summary, /Признаки учёта субконто/);
});
