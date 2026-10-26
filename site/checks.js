import {ruleCharge, rangeNote, practiceCharge} from './scoring-display.js';
const $ = id => document.getElementById(id);
// Only the final rule is shown: references to owner decisions and their history are dropped from displayed text.
const tidy = v => String(v ?? '')
  .replace(/\((?:решени[еяю])\s+(?:владельца\s+)?(?:[AАД]\d+|\d{1,2}\.\d{2}(?:\.\d{4})?)(?:\s+отозвано[^),]*)?(?:,\s*([^)]*))?\)/g, (m, rest) => rest ? '(' + rest + ')' : '')
  .replace(/[,;]?\s*[—–-]?\s*решени[еяю]\s+(?:владельца\s+)?(?:[AАД]\d+|\d{1,2}\.\d{2}(?:\.\d{4})?)(\s*:)?/g, (m, colon) => colon ? ':' : '')
  .replace(/\s+([,.;:)])/g, '$1').replace(/\(\s*\)/g, '').replace(/\s{2,}/g, ' ').trim();
const esc = v => tidy(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// One visual status per item: a dot and a word.
const REQ_STATUS = {
  checked: ['ok', 'Проверяется'], partial: ['part', 'Частично'], observed: ['seen', 'Наблюдается, без вердикта'],
  planned: ['off', 'Не проверяется'], blocked: ['wait', 'Ждёт решения'],
};
const RULE_STATUS = {ready: ['ok', 'Проверяется'], partial: ['part', 'Частично'], none: ['off', 'Не проверяется'], not_reproducible: ['na', 'Не воспроизводится на стенде'], not_checked: ['na', 'Отдельно не проверяется']};
const DECISION_STATUS = {resolved: ['ok', 'Принято'], partially_resolved: ['part', 'Принято частично'], open: ['wait', 'Нужно решение']};
const APPLIES = {applicable: 'Применимо к билету', conditional: 'Применимо, если в решении есть этот механизм', not_applicable: 'Не применимо к билету', unresolved: 'Применимость не решена'};
const KIND_CLASS = {requirement: 'k-req', rule: 'k-rule', scoring: 'k-score', procedure: 'k-proc', heading: 'k-head', info: 'k-info', example: 'k-ex', figure: 'k-fig', gap: 'k-gap'};
const VIEWS = ['document', 'ticket', 'rules', 'review', 'starter'];
const dot = ([cls, text]) => `<span class="st ${cls}"><i></i>${esc(text)}</span>`;
const paragraph = n => n.split('.').slice(0, 2).join('.');

let data, ticket, book, units, view = 'document', section = null, open = null;
const expanded = new Set();

// Long fragments (tables flattened to one cell per line in the source text) are clamped; the quote stays verbatim.
const quoteText = (id, text) => text.length > 480 && !expanded.has(id)
  ? `<p class="clamp">${esc(text)}</p><span class="expand" data-expand="${esc(id)}" role="button" tabindex="0">Показать весь фрагмент</span>`
  : `<p>${esc(text)}</p>`;
// "Б3.7.3 · стр. 377": readable number first, text-file line for cross-checking.
const place = src => `${esc(src.numbers.join(', '))} <span class="muted">· стр. ${src.lines.map(([a, b]) => a === b ? a : `${a}–${b}`).join(', ')}</span>`;

function item(id) {
  const r = ticket.requirements.find(x => x.id === id);
  if (r) return {kind: 'ticket', id, number: r.number, title: r.title};
  const g = book.rules.find(x => x.id === id);
  return g ? {kind: 'rules', id, number: g.number, title: g.title} : null;
}
const goChip = id => { const it = item(id); return it ? `<button class="ref-chip" data-goto="${it.kind}:${esc(id)}" title="${esc(it.title)} (${esc(id)})">${esc(it.number)}</button>` : ''; };
const docChip = uid => units[uid] ? `<button class="ref-chip doc-chip" data-goto="doc:${esc(uid)}" title="стр. ${units[uid].line}">${esc(units[uid].n)}</button>` : '';
const editHint = (file, id) => `<p class="edit">Править: <code>${esc(file)}</code> → <code>${esc(id)}</code></p>`;

function setView(next) {
  view = VIEWS.includes(next) ? next : 'document';
  section = null; open = null;
  document.querySelectorAll('.seg button').forEach(b => b.setAttribute('aria-selected', b.dataset.view === view));
  history.replaceState(null, '', '#' + view);
  render();
}

function sideNav(groups) {
  return `<nav class="side" aria-label="Разделы">${groups.map(g =>
    `<button class="${g.id === section ? 'on' : ''}" data-section="${esc(g.id)}"><span>${esc(g.title)}</span><small>${g.done}/${g.total}</small></button>`).join('')}</nav>`;
}

function renderTicket() {
  const outline = ticket.ledger.outline;
  const groups = ticket.sections.map((s, i) => {
    const reqs = ticket.requirements.filter(r => r.section === s.id);
    return {id: s.id, title: `${outline[i].id}. ${outline[i].title}`, total: reqs.length, done: reqs.filter(r => ['checked', 'partial'].includes(r.stand.status)).length};
  });
  section = section || groups.find(g => g.done)?.id || groups[0].id;
  // Requirements grouped by the exact sentences they were derived from, in document order.
  const fragments = [];
  for (const r of ticket.requirements.filter(r => r.section === section)) {
    const key = r.source.units.join();
    let f = fragments.find(x => x.key === key);
    if (!f) fragments.push(f = {key, source: r.source, reqs: []});
    f.reqs.push(r);
  }
  fragments.sort((a, b) => a.source.lines[0][0] - b.source.lines[0][0]);
  const file = `tasks/${ticket.ticket_id}/checks.json`;
  return sideNav(groups) + `<div class="frags">${fragments.map(f => `
    <article class="frag">
      <div class="quote"><span class="line">${place(f.source)}</span>${quoteText(f.key, f.source.quote)}</div>
      <ul class="derived">${f.reqs.map(r => `
        <li class="${open === r.id ? 'open' : ''}">
          <button data-open="${esc(r.id)}" aria-expanded="${open === r.id}"><span class="rid">${esc(r.number)}</span><span class="rtext">${esc(r.title)}${r.open_questions.length ? ` <span class="owner">· вопрос ${r.open_questions.map(q => esc(q.id)).join(', ')}</span>` : ''}</span>${dot(REQ_STATUS[r.stand.status])}</button>
          <div class="more">
            <p><b>Как проверяется.</b> ${esc(r.stand.how)}</p>
            ${r.open_questions.map(q => `<p class="q"><b>Вопрос ${esc(q.id)}.</b> ${esc(q.text)}<br><span class="muted">Пока стенд делает так: ${esc(q.interim)}</span></p>`).join('')}
            ${editHint(file, r.id)}
          </div>
        </li>`).join('')}</ul>
    </article>`).join('')}</div>`;
}

function renderRules() {
  const applied = Object.fromEntries(ticket.official_rules.map(x => [x.rule_id, x]));
  const decisions = Object.fromEntries(book.decisions.items.map(d => [d.id, d]));
  const outline = Object.fromEntries(book.ledger.outline.map(o => [o.id, o.title]));
  const sectionOf = r => r.number.split('.')[0];
  const ids = [...new Set(book.rules.map(sectionOf))].sort((a, b) => +a.slice(1) - +b.slice(1));
  const groups = ids.map(id => {
    const rules = book.rules.filter(r => sectionOf(r) === id);
    return {id, title: `${id}. ${outline[id]}`, total: rules.length, done: rules.filter(r => ['ready', 'partial'].includes(r.stand_check.readiness)).length};
  });
  const exam = book.examiner;
  if (exam) groups.push({id: 'EXM', title: 'Практики экзаменатора', total: exam.items.length, done: exam.items.filter(x => x.check.readiness === 'ready').length});
  const course = book.course;
  if (course) groups.push({id: 'CHS', title: 'Практики курса подготовки', total: course.items.length, done: course.items.filter(x => x.check.readiness === 'ready').length});
  if (book.standards) groups.push({id: 'STD', title: 'Практики стандартов 1С', total: book.standards.items.length, done: book.standards.items.filter(x => x.check.readiness === 'ready').length});
  section = section || groups[0].id;
  if (section === 'EXM') return sideNav(groups) + renderExaminer(exam, 'examiner');
  if (section === 'CHS') return sideNav(groups) + renderExaminer(course, 'chistov');
  if (section === 'STD') return sideNav(groups) + renderExaminer(book.standards, 'standards');
  const rules = book.rules.filter(r => sectionOf(r) === section).sort((a, b) => a.source.lines[0][0] - b.source.lines[0][0]);
  const file = `rules/${book.id}/rules.json`;
  return sideNav(groups) + `<div class="frags">${rules.map(r => {
    const a = applied[r.id];
    const touched = book.decisions.items.filter(d => d.anchors.rules.includes(r.id));
    return `<article class="frag rule-frag${a?.applicability === 'not_applicable' ? ' faded' : ''}${open === r.id ? ' open' : ''}">
      <button class="quote as-button" data-open="${esc(r.id)}" aria-expanded="${open === r.id}">
        <span class="line">${place(r.source)}</span>
        ${quoteText(r.id, r.source.quote)}
        <span class="meta"><span class="rid">${esc(r.number)}</span> ${esc(r.title)} <span class="alias">${esc(r.id)}</span>${touched.length ? ` · <span class="owner">уточнение ${touched.map(d => esc(d.id)).join(', ')}</span>` : ''}</span>
        <span class="right"><b class="pen">${esc(ruleCharge(r, a?.applicability))}</b>${dot(RULE_STATUS[r.stand_check.readiness])}</span>
      </button>
      <div class="more">
        ${touched.map(d => `<p class="decision"><b>${esc(d.id)}. ${esc(d.title)}.</b> ${esc(d.decision || '')} ${d.open_part ? `<span class="muted">Не решено: ${esc(d.open_part)}</span>` : ''}</p>`).join('')}
        <p><b>Как проверяется.</b> ${esc(r.stand_check.how)}</p>
        ${a ? `<p><b>${esc(APPLIES[a.applicability] || a.applicability)}.</b> ${esc(a.ticket_check)}</p>` : ''}
        ${a?.ticket_parameter ? `<p class="muted">Основание в билете: «${esc(a.ticket_parameter.source.quote)}»</p>` : ''}
        ${rangeNote(r) ? `<p class="muted">${esc(rangeNote(r))}</p>` : ''}
        ${!r.barrier ? `<p class="muted">Код штрафа стенда: F1C-${esc(r.id)}. Это идентификатор правила, не ошибка платформы 1С.</p>` : ''}
        ${editHint(file, r.id)}
      </div>
    </article>`;
  }).join('')}</div>`;
}

// Practices retain their origin; some are charged via an existing official rule.
function renderExaminer(exam, file) {
  const src = exam.source;
  const at = (t, video, link) => { if (link) return `<a href="${esc(link)}" target="_blank" rel="noopener">${esc(t)}</a>`; const [h, m, s] = t.split(':').map(Number); const url = video ? `https://www.youtube.com/watch?v=${video}` : src.url; return `<a href="${esc(url)}&t=${h * 3600 + m * 60 + s}s" target="_blank" rel="noopener">${esc(t)}</a>`; };
  return `<div class="frags">
    <article class="frag"><div class="quote"><p><b>${esc(src.title)}</b> — ${esc(src.publisher)}.</p>
      <p>${esc(src.speaker)}.</p><p class="muted">${esc(exam.note)} Таймкоды — ${esc(src.transcript)}.</p></div></article>
    ${exam.items.map(x => `<article class="frag rule-frag${open === x.id ? ' open' : ''}">
      <button class="quote as-button" data-open="${esc(x.id)}" aria-expanded="${open === x.id}">
        <span class="line">${esc(src.short || 'Белоусов П. С.')} <span class="muted">· ${x.at.map(esc).join(', ')}</span></span>
        <p>${esc(x.said)}</p>
        <span class="meta"><span class="rid">${esc(x.id)}</span> ${esc(x.title)}${x.related_rules.length ? ` · <span class="owner">см. ${x.related_rules.map(esc).join(', ')}</span>` : ''}</span>
        <span class="right"><b class="pen">${esc(practiceCharge(x, book.rules))}</b>${dot(RULE_STATUS[x.check.readiness])}</span>
      </button>
      <div class="more">
        <p><b>Как проверяется.</b> ${esc(x.check.how)}</p>
        ${x.penalty_via ? `<p><a href="checks.html#rules:${encodeURIComponent(x.penalty_via)}">Основание штрафа: ${esc(x.penalty_via)}</a> · отдельный штраф за эту практику не добавляется.</p>` : ''}
        <p class="links"><span class="muted">${x.link ? 'Источник:' : 'В видео:'}</span> ${x.at.map(t => at(t, x.video, x.link)).join(' ')}</p>
        ${editHint(`rules/${book.id}/${file}.json`, x.id)}
      </div>
    </article>`).join('')}</div>`;
}

function renderReview() {
  const questions = (ticket.questions || []).map(q => ({...q, requirements: q.requirement_ids}));
  const gaps = Object.values(units).filter(u => u.kind === 'gap');
  const card = (id, title, status, body, where, affects) => `<article class="frag review">
    <div class="review-head"><b>${esc(id)}</b><span class="review-title">${esc(title)}</span>${dot(status)}</div>
    <div class="review-body">${body}
      ${where.length ? `<p class="links"><span class="muted">Где в документе:</span> ${where.join(' ')}</p>` : ''}
      ${affects.length ? `<p class="links"><span class="muted">Затрагивает:</span> ${affects.join(' ')}</p>` : ''}</div></article>`;
  const types = book.decisions.types || {};
  const decisionCard = d => card(d.id, d.title, DECISION_STATUS[d.state],
    (d.type && d.type !== 'open' ? `<p><span class="type-tag t-${esc(d.type)}">${esc(types[d.type] || d.type)}</span></p>` : '')
    + (d.decision ? `<p><b>Решение.</b> ${esc(d.decision)}</p>` : '') + (d.open_part ? `<p><b>Не решено.</b> ${esc(d.open_part)}</p>` : ''),
    [...d.anchors.units, ...d.anchors.ticket_units].map(docChip),
    [...d.anchors.rules, ...d.anchors.requirements].map(goChip));
  const open = book.decisions.items.filter(d => d.state !== 'resolved');
  const done = book.decisions.items.filter(d => d.state === 'resolved');
  const qCard = q => {
    const where = q.requirements.flatMap(id => ticket.requirements.find(r => r.id === id).source.units);
    const body = q.state === 'open' ? `<p><b>Пока стенд делает так.</b> ${esc(q.interim)}</p>`
      : `<p><span class="type-tag t-ticket_parameter">Вопрос по билету</span></p><p><b>Ответ.</b> ${esc(q.answer)}</p>`;
    return card(q.id, q.text, q.state === 'open' ? DECISION_STATUS.open : DECISION_STATUS.resolved, body, [...new Set(where)].map(docChip), q.requirements.map(goChip));
  };
  const sorted = [...questions].sort((a, b) => a.id.localeCompare(b.id));
  const qCards = sorted.filter(q => q.state === 'open').map(qCard);
  const qDone = sorted.filter(q => q.state !== 'open').map(qCard);
  const gapCards = gaps.map(u => card(u.n, 'Предложение не разобрано', DECISION_STATUS.open, `<p class="quote-inline">«${esc(u.text)}»</p><p>${esc(u.note)}</p>`, [docChip(u.id)], []));
  // Only the clarifications themselves: open ones first, each card carries its own status.
  return `<div class="review-list">
    ${open.map(decisionCard).join('')}${qCards.join('')}${gapCards.join('')}
    ${done.map(decisionCard).join('')}${qDone.join('')}
    ${editHint(`rules/${book.id}/decisions.json`, 'A01…A18')}${editHint(`tasks/${ticket.ticket_id}/private/questions.json`, 'Q01…Q09')}</div>`;
}

function renderStarter() {
  const s = data.starters[ticket.starter];
  return `<div class="starter"><p>${esc(s.description)}</p>
    <dl class="kv"><dt>Файл</dt><dd><a href="${esc(s.source_url)}" target="_blank" rel="noopener">${esc(s.file)}</a></dd>
    <dt>Платформа</dt><dd>${esc(s.platform)}</dd><dt>SHA-256</dt><dd><code>${esc(s.sha256)}</code></dd></dl>
    <div class="objects">${Object.entries(s.objects).map(([k, v]) => `<div><h4>${esc(k)}</h4><p>${v.map(esc).join(', ')}</p></div>`).join('')}</div>
    ${editHint(`starters/${s.id}/starter.json`, s.id)}</div>`;
}

// Whole document: every sentence in order with its number and classification; table cells fold into one row.
const tags = (u, kinds) => (u.refs.length ? ' ' + u.refs.map(goChip).join('') : ` <span class="kind kb-${esc(u.kind)}">${esc(kinds[u.kind])}</span>`)
  + (u.note && u.kind !== 'heading' ? `<small class="note stand-note"><b>Пометка стенда</b>${esc(u.note)}</small>` : '');
const sentence = u => `<span class="sent ${KIND_CLASS[u.kind]}" id="u-${esc(u.id)}" title="${esc(u.n)} · стр. ${u.line}">${esc(u.text)}</span>`;
function lineHtml(us, kinds) {
  const same = us.every(u => u.kind === us[0].kind && u.refs.join() === us[0].refs.join() && (u.note || '') === (us[0].note || ''));
  return same ? us.map(sentence).join(' ') + tags(us[0], kinds) : us.map(u => sentence(u) + tags(u, kinds)).join(' ');
}
function renderDocument() {
  const parts = [book.ledger, ticket.ledger];
  const kinds = book.ledger.kinds;
  const body = parts.map(ledger => ledger.outline.map(sec => {
    const rows = [];
    let fold = null;
    for (const u of ledger.units.filter(u => u.line >= sec.first && u.line <= sec.last)) {
      if (u.kind === 'example' && fold && fold.refs === u.refs.join() && u.line - fold.lastLine <= 2) { fold.count++; fold.lastLine = u.line; continue; }
      if (u.kind === 'example') { fold = {count: 1, refs: u.refs.join(), lastLine: u.line, unit: u}; rows.push(fold); continue; }
      fold = null;
      const prev = rows[rows.length - 1];
      if (prev && !prev.unit && paragraph(prev.units[0].n) === paragraph(u.n) && u.kind !== 'heading' && prev.units[0].kind !== 'heading') prev.units.push(u); else rows.push({units: [u]});
    }
    if (!rows.length) return '';
    return `<h3 class="doc-part">${esc(sec.id)}. ${esc(sec.title)}</h3>` + rows.map(r => r.unit
      ? `<div class="doc-row k-ex"><span class="ln">${esc(paragraph(r.unit.n))}</span><div><span class="sent" id="u-${esc(r.unit.id)}">${esc(r.count > 1 ? `Таблица-образец: ${r.count} ячеек` : r.unit.text)}</span> <span class="kind kb-example">${esc(kinds.example)}</span> ${r.unit.refs.map(goChip).join('')}${r.unit.note ? `<small class="note stand-note"><b>Пометка стенда</b>${esc(r.unit.note)}</small>` : ''}</div></div>`
      : `<div class="doc-row"><span class="ln">${r.units[0].kind === 'heading' ? '' : esc(paragraph(r.units[0].n))}</span><div>${lineHtml(r.units, kinds)}</div></div>`).join('');
  }).join('')).join('');
  return `<div class="doc">${body}
    <p class="edit">Разметка: <code>rules/${esc(book.id)}/ledger.json</code> и <code>tasks/${esc(ticket.ticket_id)}/ledger.json</code>; после правки — <code>python3.12 tools/sync_sources.py</code></p></div>`;
}

function render() {
  const doc = book.sources.ATT83PL;
  const notes = {
    ticket: 'Текст условия билета по разделам. Под каждым фрагментом — требования, которые стенд из него вывел. Нажмите на требование, чтобы увидеть, как оно проверяется.',
    rules: 'Перечень ошибок со штрафами из методики 1С — общий для всех билетов. Нажмите на пункт: как стенд его проверяет и что он значит для этого билета.',
    review: 'Уточнения стенда к документу 1С и ответы на вопросы по билету.',
    document: '',
    starter: 'Конфигурация, с которой агент начинает работу. Общая для всех билетов.',
  };
  $('view-note').textContent = notes[view];
  $('view-note').hidden = !notes[view];
  $('view').className = 'trace v-' + view;
  $('view').innerHTML = {ticket: renderTicket, rules: renderRules, review: renderReview, document: renderDocument, starter: renderStarter}[view]();
  const active = document.querySelector('.side button.on');
  if (active) active.parentElement.scrollLeft = active.offsetLeft - 16; // keep the current section visible in the mobile strip
  $('legend').innerHTML = view === 'ticket' ? Object.values(REQ_STATUS).map(dot).join('') : view === 'rules' ? Object.values(RULE_STATUS).map(dot).join('') : '';
  $('doc-ref').innerHTML = `<a href="${esc(doc.url)}" target="_blank" rel="noopener">${esc(doc.file)}</a>`;
  $('source-line').innerHTML = `Источник: <a href="${esc(doc.url)}" target="_blank" rel="noopener">${esc(doc.file)}</a>, ${esc(doc.publisher)}, сверено ${esc(doc.verified_on)}. Номера: М — методика 1С, Б — билет, Т — требование стенда, A и Q — уточнения.`;
}

function goto(target, id) {
  if (target === 'doc') {
    setView('document'); render();
    const el = document.getElementById('u-' + id);
    if (el) { el.scrollIntoView({block: 'center'}); el.classList.add('flash'); }
    return;
  }
  setView(target);
  section = target === 'ticket' ? ticket.requirements.find(r => r.id === id).section : book.rules.find(r => r.id === id).number.split('.')[0];
  open = id; render();
  document.querySelector(`[data-open="${id}"]`)?.scrollIntoView({block: 'center'});
}

document.addEventListener('click', e => {
  const more = e.target.closest('[data-expand]');
  if (more) { e.stopPropagation(); expanded.add(more.dataset.expand); render(); return; }
  const go = e.target.closest('[data-goto]');
  if (go) { const [target, id] = go.dataset.goto.split(':'); goto(target, id); return; }
  const tab = e.target.closest('[data-view]'), sec = e.target.closest('[data-section]'), it = e.target.closest('[data-open]');
  if (tab) setView(tab.dataset.view);
  if (sec) { section = sec.dataset.section; open = null; render(); window.scrollTo({top: $('view').offsetTop - 16}); }
  if (it) { open = open === it.dataset.open ? null : it.dataset.open; render(); }
});

fetch('checks.json', {cache: 'no-store'}).then(r => r.json()).then(json => {
  data = json; ticket = data.tickets[0]; book = data.rulebooks[ticket.rulebook];
  units = Object.fromEntries([...book.ledger.units, ...ticket.ledger.units].map(u => [u.id, u]));
  const followHash = () => {
    const [target, encoded] = location.hash.slice(1).split(':');
    let id;
    try { id = decodeURIComponent(encoded || ''); } catch { id = ''; }
    const exists = target === 'rules' ? book.rules.some(r => r.id === id)
      : target === 'ticket' && ticket.requirements.some(r => r.id === id);
    if (exists) {
      goto(target, id);
      history.replaceState(null, '', `#${target}:${encodeURIComponent(id)}`);
    } else setView(target);
  };
  followHash();
  window.addEventListener('hashchange', followHash);
}).catch(err => { $('view').innerHTML = `<p class="empty">Не удалось загрузить данные: ${esc(err.message)}</p>`; });
