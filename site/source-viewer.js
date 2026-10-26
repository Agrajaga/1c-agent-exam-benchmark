// Source text is always inserted as text nodes, never interpreted as markup.
const el = (tag, text, cls) => {
  const n = document.createElement(tag);
  if (text != null) n.textContent = text;
  if (cls) n.className = cls;
  return n;
};
const cached = new Map();
const keywords = new Set(('процедура функция конецпроцедуры конецфункции экспорт асинх ожидать если тогда иначе ' +
  'иначеесли конецесли для каждого из цикл конеццикла пока возврат попытка исключение конецпопытки ' +
  'вызватьисключение новый перем значение истина ложь неопределено и или не продолжить прервать ' +
  'procedure function endprocedure endfunction export if then else elsif endif for each in do enddo ' +
  'return try except endtry new var true false undefined and or not').split(' '));

export function tokenizeBSL(line, state = {quoted: false}) {
  const tokens = [];
  const add = (text, kind) => { if (text) tokens.push({text, kind}); };
  let i = 0;
  while (i < line.length) {
    const start = i;
    if (state.quoted || line[i] === '"') {
      if (!state.quoted) { state.quoted = true; i++; }
      while (i < line.length) {
        if (line[i] === '"') {
          if (line[i + 1] === '"') { i += 2; continue; }
          i++; state.quoted = false; break;
        }
        i++;
      }
      add(line.slice(start, i), 'string'); continue;
    }
    if (line.slice(i, i + 2) === '//') { add(line.slice(i), 'comment'); break; }
    const word = /^[\p{L}_][\p{L}\p{N}_]*/u.exec(line.slice(i));
    if (word) { i += word[0].length; add(word[0], keywords.has(word[0].toLowerCase()) ? 'keyword' : 'text'); continue; }
    const number = /^\d+(?:[.,]\d+)?/.exec(line.slice(i));
    if (number) { i += number[0].length; add(number[0], 'number'); continue; }
    i++; add(line.slice(start, i), 'text');
  }
  return tokens;
}

function codeBlock(view, language) {
  const block = el('div', null, 'source-code');
  block.setAttribute('role', 'region');
  block.setAttribute('aria-label', language === 'bsl' ? 'Исходный код 1С' : 'Исходный XML');
  const state = {quoted: false};
  view.lines.forEach((text, index) => {
    const line = view.start_line + index;
    const row = el('div', null, 'source-line' + (line === view.marked_line ? ' source-marked' : ''));
    const number = el('span', String(line), 'source-number'); number.setAttribute('aria-hidden', 'true');
    const code = el('code', null, 'source-text');
    if (language === 'bsl') {
      for (const token of tokenizeBSL(text, state)) code.append(el('span', token.text, 'syntax-' + token.kind));
    } else code.textContent = text;
    if (!text) code.textContent = ' ';
    row.append(number, code); block.append(row);
  });
  return block;
}

function displayValue(value) {
  return ({Allow: 'Разрешено', Deny: 'Запрещено', true: 'Да', false: 'Нет'})[value] || value;
}

function metadataTree(view) {
  const root = el('ul', null, 'metadata-tree');
  let list = root;
  for (const item of view.tree) {
    const li = el('li', null, item.marked ? 'metadata-marked' : '');
    const line = el('div', null, 'metadata-label');
    line.append(el('span', item.label));
    if (item.value != null) line.append(el('strong', displayValue(item.value)));
    li.append(line); list.append(li);
    if (!item.marked) { const next = el('ul'); li.append(next); list = next; }
  }
  return root;
}

function renderView(container, view) {
  container.replaceChildren();
  const title = view.kind === 'bsl' ? (view.method ? 'Метод · ' + view.method : 'Фрагмент модуля') : 'Структура метаданных';
  container.append(el('h5', title, 'source-view-title'));
  if (view.kind === 'bsl') {
    container.append(el('p', view.method ? 'Выделена строка, указанная проверкой.' : 'Точная граница метода не найдена; показаны соседние строки.', 'source-hint'));
    if (view.truncated) container.append(el('p', 'Метод длинный: показан участок вокруг указанной строки.', 'source-hint'));
    container.append(codeBlock(view, 'bsl'));
  } else {
    container.append(metadataTree(view));
    const xml = el('details', null, 'source-xml');
    xml.append(el('summary', 'Показать соответствующий XML'));
    if (view.property_missing) xml.append(el('p', 'Свойство отсутствует в XML; выделен раздел, в котором оно могло бы быть задано.', 'source-hint'));
    xml.append(codeBlock(view, 'xml'));
    container.append(xml);
  }
  const file = el('details', null, 'source-file');
  file.append(el('summary', 'Файл и контрольная сумма'), el('p', view.file), el('code', 'SHA-256 ' + view.sha256));
  container.append(file);
}

async function load(ref) {
  if (!cached.has(ref)) cached.set(ref, fetch(ref, {cache: 'no-store'}).then(r => {
    if (!r.ok) throw new Error('Исходники для этой оценки недоступны');
    return r.json();
  }).catch(error => { cached.delete(ref); throw error; }));
  return cached.get(ref);
}

export function sourceEvidence(charge, index, ref) {
  const details = el('details', null, 'source-evidence');
  details.append(el('summary', 'Показать код или метаданные'));
  const body = el('div', null, 'source-evidence-body'); details.append(body);
  let loaded = false;
  details.addEventListener('toggle', async () => {
    if (!details.open || loaded) return;
    body.textContent = 'Загружаем исходники решения…';
    try {
      const data = await load(ref);
      const entry = data.charges?.[index];
      if (!entry || entry.id !== charge.id || entry.reason !== charge.reason) throw new Error('Исходники относятся к другой оценке');
      const views = entry.contexts || [];
      body.replaceChildren();
      if (!views.length) {
        body.append(el('p', 'Проверка не сохранила точное место в исходниках. Для этой ошибки доступна исходная диагностика ниже.', 'source-hint'));
      } else {
        const content = el('div');
        if (views.length > 1) {
          const label = el('label', 'Место в решении ', 'source-choice');
          const select = el('select', null, 'field');
          views.forEach((v, i) => { const option = el('option', `${i + 1}. ${v.kind === 'bsl' ? (v.method || 'Модуль') : 'Метаданные'} · строка ${v.marked_line}`); option.value = String(i); select.append(option); });
          select.addEventListener('change', () => renderView(content, views[Number(select.value)]));
          label.append(select); body.append(label);
        }
        body.append(content); renderView(content, views[0]);
      }
      loaded = true;
    } catch (error) { body.textContent = error.message || 'Не удалось открыть исходники решения'; }
  });
  return details;
}
