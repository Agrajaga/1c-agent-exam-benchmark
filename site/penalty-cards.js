// Presentation only: never enrich or rewrite the saved charge objects.
const textNode = (tag, text, cls) => {
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (cls) element.className = cls;
  return element;
};
const amount = value => String(value ?? '—').replace('.', ',');
const lookup = (table, id) => table && Object.hasOwn(table, id) ? {id, ...table[id]} : null;
const rendered = new WeakMap();

export async function loadPenaltyMetadata() {
  try {
    const response = await fetch('penalty-info.json', {cache: 'no-store'});
    return response.ok ? await response.json() : {};
  } catch { return {}; } // Old exports still show the complete original diagnostic.
}

export function describeCharge(charge, metadata = {}) {
  const id = String(charge.id ?? ''), reason = String(charge.reason ?? '');
  const rule = lookup(metadata.rules, id.replace(/^F1C-/, ''));
  const requirementId = /^не выполнено требование: ([A-Z]+\d+)\b/.exec(reason)?.[1];
  const requirement = lookup(metadata.requirements, requirementId);
  let title = requirement ? `Не выполнено: ${requirement.title}` : rule?.title || 'Нарушение, отмеченное стендом';
  let summary = requirementId
    ? 'Проверочный сценарий стенда не подтвердил выполнение требования. Подробности результата сохранены в исходной диагностике.'
    : 'Стенд зафиксировал нарушение этого правила. Подробности проверки сохранены в исходной диагностике.';
  const expected = {
    BU13: 'Себестоимость списания должна учитывать товар на всех складах компании, а количество — уменьшаться на складе продажи. Требование не прошло проверку.',
    BU14: 'Стенд проверяет проводку списания себестоимости: дебет «Прибыли и убытки», кредит «Товары». Полученный результат не соответствует требованию.',
    PR13: 'При вводе командировки задним числом тариф за затронутые периоды должен измениться. Проверка не получила ожидаемый результат.',
    F05: 'Проверка не подтвердила сохранение дополнительных значений после записи формы.',
  };
  if (requirement && expected[requirementId]) summary = expected[requirementId];
  const comparisons = [];
  if (requirementId === 'PR13') {
    const pattern = /pr_backdate\s+(\S+)\s+tariff\s+(\d{4}-\d{2}):\s*([+-]?\d+(?:\.\d+)?),\s*expected\s+([+-]?\d+(?:\.\d+)?)/g;
    for (const match of reason.matchAll(pattern)) {
      comparisons.push({subject: match[1], period: match[2], actual: match[3], expected: match[4]});
    }
  }
  if (requirementId === 'F05' && /\bwritten True, stored /.test(reason)) {
    const stored = /\bstored \[([^\]]*)\]/.exec(reason)?.[1] || '';
    const empty = [...stored.matchAll(/\('([^']+)', ''\)/g)].map(m => m[1].replace(/^BENCH_/, ''));
    if (empty.length) summary = `Запись формы завершилась успешно, но при чтении хранилища обнаружены пустые значения: ${empty.join(', ')}.`;
  }
  if (/^текст запроса не разбирается платформой:/.test(reason)) {
    title = 'Платформа 1С не смогла разобрать запрос';
    summary = 'В тексте запроса обнаружена ошибка. Сообщение платформы и место ошибки приведены в исходной диагностике.';
  } else if (id === 'F1C-GEN15' && reason.includes('индексы таблицы начинаются')) {
    summary = 'По структуре запроса и индексам базы стенд не нашёл индекс, начинающийся с полей отбора.';
  } else if (id === 'F1C-PR14' && reason.includes('фактического периода действия')) {
    summary = 'Анализ исходников обнаружил повторную запись рассчитанного набора с пересчётом фактического периода действия. Места записи перечислены ниже.';
  } else if (id === 'F1C-BU06' && /ресурс [\p{L}\p{N}_]+ балансовый/u.test(reason)) {
    const resource = /ресурс ([\p{L}\p{N}_]+) балансовый/u.exec(reason)[1];
    title = `Для ресурса «${resource}» включён балансовый учёт`;
    summary = 'Стенд считает эту настройку ресурса несоответствующей требованиям бухгалтерского учёта задачи.';
  } else if (id === 'F1C-BU06' && reason.includes('не указан ни у одного ресурса')) {
    summary = 'Признак учёта плана счетов не связан ни с одним ресурсом регистра. По проверке стенда он не влияет на учёт ресурсов.';
  } else if (id === 'F1C-BU07' && reason.includes('не указан ни у одного ресурса')) {
    summary = 'Признаки учёта субконто созданы в плане счетов, но не связаны с ресурсами регистра. По проверке стенда они не влияют на учёт ресурсов.';
  } else if (id === 'F1C-GEN20' && reason.startsWith('данные базы читаются в цикле')) {
    summary = 'Анализ исходников обнаружил признаки повторного чтения информационной базы внутри цикла по данным.';
  } else if (id === 'F1C-GEN28' && reason.startsWith('оперативное проведение разрешено')) {
    title = 'Для документа начислений разрешено оперативное проведение';
    summary = 'У документа с движениями по регистру расчёта разрешено оперативное проведение. Стенд учитывает это как нарушение методики проведения.';
  } else if (id === 'F1C-GEN21' && reason.startsWith('данные графика без отбора')) {
    title = 'Данные графика запрашиваются без отбора по регистратору';
    summary = 'Анализ исходников не обнаружил ограничения данных графика по документу-регистратору в проверяемом запросе.';
  } else if (reason.startsWith('разыменование поля составного типа без ВЫРАЗИТЬ')) {
    title = 'Обращение к реквизиту составной ссылки без приведения типа';
    summary = 'Анализ исходников отметил обращения через точку без ВЫРАЗИТЬ. Поля, которые детектор отнёс к составным типам, перечислены в исходной диагностике.';
  }
  const locations = [...new Set(reason.match(/\b(?:CommonModules|Documents|Catalogs|Reports|DataProcessors|CalculationRegisters|AccumulationRegisters|AccountingRegisters)\/[^\s;:]+\.bsl:\d+/g) || [])];
  return {title, summary, rule, requirement, comparisons, locations,
    original: `${id} · −${amount(charge.points)} · ${reason}`};
}

function reference(parent, label, entry, target, methodology) {
  if (!entry) return;
  const line = textNode('p', label + ': ', 'penalty-basis');
  const caption = `${entry.number} · ${entry.title} (${entry.id})`;
  const value = textNode(methodology ? 'a' : 'span', caption);
  if (methodology) value.href = `checks.html#${target}:${encodeURIComponent(entry.id)}`;
  line.append(value); parent.append(line);
}

export function renderCharges(container, charges, metadata = {}, {methodology = false} = {}) {
  const signature = JSON.stringify(charges);
  const previous = rendered.get(container);
  // Polling the unchanged evaluation must not close a diagnostic the reader opened.
  if (previous?.signature === signature && previous.metadata === metadata && previous.methodology === methodology) return;
  container.classList.add('penalty-list');
  container.replaceChildren(...charges.map(charge => {
    const description = describeCharge(charge, metadata);
    const card = textNode('li', null, 'penalty-card');
    card.append(textNode('h4', `−${amount(charge.points)} · ${description.title}`, 'penalty-title'),
      textNode('p', description.summary, 'penalty-explanation'));
    if (description.comparisons.length) {
      const table = textNode('table', null, 'penalty-comparison');
      const header = textNode('tr');
      for (const label of ['Проверка', 'Период', 'Ожидалось', 'Получено']) header.append(textNode('th', label));
      const head = textNode('thead'); head.append(header); table.append(head);
      const body = textNode('tbody');
      for (const item of description.comparisons) {
        const row = textNode('tr');
        for (const value of [item.subject, item.period, amount(item.expected), amount(item.actual)]) row.append(textNode('td', value));
        body.append(row);
      }
      table.append(body); card.append(table);
    }
    reference(card, 'Основание штрафа', description.rule, 'rules', methodology);
    reference(card, 'Не выполнено требование', description.requirement, 'ticket', methodology);
    card.append(textNode('p', `Код штрафа: ${charge.id}`, 'penalty-basis'));
    if (description.locations.length) {
      const locations = textNode('details', null, 'penalty-locations');
      locations.append(textNode('summary', `Места в исходниках: ${description.locations.length} (один штраф)`));
      const list = textNode('ul');
      for (const location of description.locations) list.append(textNode('li', location));
      locations.append(list); card.append(locations);
    }
    const original = textNode('details', null, 'penalty-original');
    original.append(textNode('summary', 'Исходная диагностика'), textNode('pre', description.original));
    card.append(original);
    return card;
  }));
  rendered.set(container, {signature, metadata, methodology});
}
