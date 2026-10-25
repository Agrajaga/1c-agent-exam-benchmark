// One leaderboard table: accepted community results plus, on a local stand, this machine's own
// results highlighted with a send button. A row expands into violations and, locally, the agent log.
const $ = id => document.getElementById(id);
const node = (tag, text, cls) => { const n = document.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n; };
const number = v => String(v).replace('.', ',');
const grades = {unsatisfactory: 'Неудовлетворительно', satisfactory: 'Удовлетворительно', good: 'Хорошо', excellent: 'Отлично'};
const agents = {codex: 'Codex', claude: 'Claude Code'};
const tokens = n => n == null ? '—' : n >= 1e6 ? number((n / 1e6).toFixed(1)) + ' млн' : n >= 1e3 ? Math.round(n / 1e3) + ' тыс.' : String(n);
const minutes = s => s == null ? '—' : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
const harnessName = h => !h || h === 'none' ? 'Без харнеса' : h;
const systems = {Darwin: 'macOS', Windows: 'Windows', Linux: 'Linux'};
const arch = a => ({amd64: 'x64', x86_64: 'x64', arm64: 'arm64', aarch64: 'arm64'})[String(a).toLowerCase()] || a;
const isolation = {'dedicated-host': 'без песочницы', macos: 'песочница macOS', bubblewrap: 'песочница Linux'};
let rows = [], sort = {key: 'score', dir: -1}, local = null, submit = null;

function fromCommunity(r) {
  const v = r.result, c = r.conditions || {}, m = r.measurement || {};
  return {id: r.id, local: false, model: v.model, agent: c.client || (String(v.model).startsWith('claude') ? 'claude' : 'codex'),
    agentVersion: c.client_version, effort: c.reasoning_effort, harness: v.harness, e: v, limit: c.solve_timeout_seconds,
    tokens: c.tokens || {}, tools: c.tools || {}, env: m.environment || {}, author: m.operator || {}, date: v.created_at,
    download: r.download, sha: r.archive_sha256, verification: r.verification, regrade: r.regrade_required || []};
}

function fromLocal(item) {
  const e = item.evaluation, run = item.run || {}, m = item.measurement || {};
  return {id: item.job_id, local: true, item, model: run.model || e.model, agent: run.client || 'codex', agentVersion: run.client_version,
    effort: run.reasoning_effort, harness: item.harness, e, limit: run.solve_timeout_seconds, tokens: run.tokens || {},
    tools: run.tools || {}, env: m.environment || {}, author: m.operator || {}, date: e.created_at};
}

// A score from an earlier grader, or one the current code cannot reproduce, stays visible but is not ranked.
const REGRADE = {grader_changed: r => 'Оценено прежней версией грейдера; изменились: ' + r.files.join(', ') + '.',
  adapter_not_in_repository: () => 'Привязки адаптированы кодом, которого нет в репозитории.',
  original_submission_refused: () => 'Исходная сдача агента не прошла приёмку; оценены привязки без доказательства адаптера.'};
const stale = r => (r.regrade || []).length > 0;
const exact = r => r.e.score != null && !r.e.infrastructure_errors && !stale(r);
const value = r => Number(exact(r) ? r.e.score : Math.max(0, r.e.score_upper_bound ?? 0));
const keys = {score: r => value(r) + (exact(r) ? 0.001 : 0), solve: r => r.e.solve_seconds, tokens: r => r.tokens.fresh_input ?? -1,
  date: r => Date.parse(r.date) || 0};

function filtersMatch(r) {
  return ['agent', 'model', 'harness'].every(k => !$('f-' + k).value || String(r[k]) === $('f-' + k).value);
}

function fillFilter(id, values, label) {
  const select = $(id), current = select.value;
  select.replaceChildren(node('option', 'Все'), ...[...new Set(values)].sort().map(v => { const o = node('option', label(v)); o.value = v; return o; }));
  select.firstChild.value = '';
  if ([...select.options].some(o => o.value === current)) select.value = current;
}

function sub(parent, text) { if (text) parent.append(node('small', text)); return parent; }

function violations(r) {
  const box = node('div', null, 'details-grid');
  const charges = node('div'); charges.append(node('h4', 'Штрафы'));
  if (r.e.charges?.length) {
    const list = node('ul');
    list.append(...r.e.charges.map(c => node('li', `${c.id} · −${number(c.points)} · ${c.reason || ''}`)));
    charges.append(list);
  } else charges.append(node('p', 'Нет', 'why'));
  const failed = node('div'); failed.append(node('h4', 'Не пройденные требования'));
  const bad = (r.e.rules || []).filter(x => x.verdict === 'fail');
  if (bad.length) {
    const list = node('ul');
    list.append(...bad.map(x => node('li', x.id + (x.reason ? ' · ' + x.reason : ''))));
    failed.append(list);
  } else failed.append(node('p', 'Нет', 'why'));
  const notes = node('div'); notes.append(node('h4', 'Покрытие'));
  notes.append(node('p', `Проверок пройдено: ${r.e.counts?.pass || 0}, не пройдено: ${r.e.counts?.fail || 0}, `
    + `не определено: ${r.e.counts?.inconclusive || 0}. Пунктов каталога без оценки: ${r.e.not_assessed ?? '—'}.`, 'why'));
  if (stale(r)) notes.append(node('p', 'Требуется пересчёт, место не присваивается. ' + r.regrade.map(x => REGRADE[x.id]?.(x) || x.id).join(' '), 'why'));
  if (r.e.binding_compatibility) notes.append(node('p', 'Оценено с адаптацией привязок: исходная сдача не загрузилась без неё.', 'why'));
  if (r.tools?.mcp_calls != null) notes.append(node('p', `Вызовов MCP-инструментов: ${r.tools.mcp_calls}, с ошибкой: ${r.tools.failed_calls || 0}.`, 'why'));
  box.append(charges, failed, notes);
  if (r.local) {
    const log = node('button', 'Открыть лог агента', 'btn small');
    log.addEventListener('click', () => showLog(r));
    box.append(log);
  }
  return box;
}

async function showLog(r) {
  const dialog = node('dialog', null, 'ask prompt-dialog log-dialog');
  const close = node('button', 'Закрыть', 'btn');
  close.addEventListener('click', () => { dialog.close(); dialog.remove(); });
  dialog.addEventListener('cancel', () => dialog.remove());
  const body = node('div', 'Загружаем…', 'log');
  dialog.append(node('h2', `Лог агента · ${r.model}`), body, close);
  document.body.append(dialog); dialog.showModal();
  try {
    const response = await fetch('api/results/log?id=' + encodeURIComponent(r.id), {cache: 'no-store'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    body.replaceChildren(...data.steps.map(s => {
      if (s.kind === 'message') return node('p', s.text, 'log-message');
      const d = node('details', null, 'log-step');
      d.append(node('summary', (s.kind === 'command' ? '$ ' : '⚙ ') + s.text + (s.exit_code ? `  · код ${s.exit_code}` : '')));
      const out = [s.output, s.result].filter(Boolean).join('\n— ответ —\n');
      if (out) d.append(node('pre', out, 'review'));
      return d;
    }));
  } catch (error) { body.textContent = error.message || 'Лог недоступен'; }
}

function render() {
  const visible = rows.filter(filtersMatch).sort((a, b) => sort.dir * (keys[sort.key](a) - keys[sort.key](b)) || a.e.solve_seconds - b.e.solve_seconds);
  // Places count only accepted results with an exact score, in score order.
  const ranked = rows.filter(r => !r.local && exact(r)).sort((a, b) => value(b) - value(a) || a.e.solve_seconds - b.e.solve_seconds);
  const places = new Map(ranked.map((r, i) => [r.id, i + 1]));
  for (const th of document.querySelectorAll('.sort')) th.dataset.dir = th.dataset.key === sort.key ? (sort.dir > 0 ? 'asc' : 'desc') : '';
  $('rows').replaceChildren(...visible.flatMap(r => {
    const tr = node('tr', null, 'row-main' + (r.local ? ' mine' : ''));
    const place = node('td', r.local ? 'ваш' : places.has(r.id) ? String(places.get(r.id)) : '—', 'num place');
    const score = node('td');
    score.append(node('b', exact(r) ? `${number(r.e.score)} из 5` : `не выше ${number(Math.max(0, r.e.score_upper_bound))} из 5`, 'score-value'));
    sub(score, grades[r.e.grade]);
    if (stale(r)) { const b = node('span', 'требуется пересчёт', 'badge warn'); b.title = r.regrade.map(x => REGRADE[x.id]?.(x) || x.id).join(' '); score.append(b); }
    const total = Object.values(r.e.counts || {}).reduce((a, b) => a + b, 0);
    sub(score, `проверок ${r.e.counts?.pass || 0} из ${total}`);
    const who = node('td'); who.append(node('b', r.model));
    sub(who, [agents[r.agent] || r.agent, r.agentVersion, r.effort].filter(Boolean).join(' · '));
    sub(who, harnessName(r.harness));
    const time = node('td', minutes(r.e.solve_seconds), 'num'); sub(time, r.limit ? `лимит ${Math.round(r.limit / 60)} мин` : '');
    const tok = node('td', tokens(r.tokens.fresh_input), 'num');
    sub(tok, `кеш ${tokens(r.tokens.cached_input)}`); sub(tok, `выход ${tokens(r.tokens.output)}`);
    const env = r.env, hw = env.hardware || {};
    const pc = node('td', [systems[env.os?.system] || env.os?.system, env.os?.architecture && arch(env.os.architecture)].filter(Boolean).join(' ') || '—', 'pc');
    sub(pc, [hw.cpu, hw.logical_cpus && hw.logical_cpus + ' потоков', hw.ram_bytes && Math.round(hw.ram_bytes / 1073741824) + ' ГБ'].filter(Boolean).join(' · '));
    sub(pc, [env.platform_version && '1С ' + env.platform_version, isolation[env.isolation] || env.isolation].filter(Boolean).join(' · '));
    const author = node('td');
    if (r.author?.github) { const a = node('a', r.author.name || r.author.github); a.href = 'https://github.com/' + r.author.github; author.append(a); sub(author, '@' + r.author.github); }
    else author.append(node('span', r.author?.name || '—'));
    sub(author, r.date ? new Date(r.date).toLocaleDateString('ru-RU') : '');
    sub(author, r.local ? 'не отправлен' : r.verification === 'contributor_reported' ? 'заявлено участником' : r.verification);
    const cellActions = node('td'), act = node('div', null, 'row-actions');
    cellActions.append(act);
    if (r.local && submit) { const box = node('div', null, 'actions'); submit(box, r.item, local.community, local.githubReady, load); act.append(box); }
    else if (r.download) { const a = node('a', 'Скачать', 'btn small'); a.href = r.download; a.download = ''; a.title = 'Решение XML и DT, оценка, параметры · SHA-256 ' + r.sha; act.append(a); }
    const more = node('button', 'Подробнее', 'btn small row-more');
    act.append(more);
    tr.append(place, score, who, time, tok, pc, author, cellActions);
    const detail = node('tr', null, 'row-detail' + (r.local ? ' mine' : '')); detail.hidden = true;
    const cell = node('td'); cell.colSpan = 8; cell.append(violations(r)); detail.append(cell);
    more.addEventListener('click', () => { detail.hidden = !detail.hidden; more.textContent = detail.hidden ? 'Подробнее' : 'Скрыть'; });
    return [tr, detail];
  }));
  const mine = visible.filter(r => r.local).length;
  $('summary').textContent = `${visible.length} из ${rows.length}` + (mine ? ` · ваших неотправленных: ${mine}` : '');
  $('empty').hidden = visible.length > 0;
  $('empty').textContent = rows.length ? 'Нет результатов с такими условиями.' : 'Пока нет результатов. Сделайте замер и отправьте его в рейтинг.';
}

async function load() {
  let community = [];
  try {
    const response = await fetch('community.json', {cache: 'no-store'});
    if (response.ok) community = (await response.json()).results.map(fromCommunity);
  } catch { /* the table still shows local results */ }
  const sent = new Set(community.map(r => r.id));
  let mine = [];
  try {
    const [results, state, readiness] = await Promise.all(['api/results', 'api/community', 'api/readiness']
      .map(u => fetch(u, {cache: 'no-store'}).then(r => { if (!r.ok) throw new Error(); return r.json(); })));
    if (!submit) ({renderSubmit: submit} = await import('./submit.js'));
    local = {community: state, githubReady: readiness.steps.find(s => s.id === 'github')?.state === 'ok'};
    mine = results.results.filter(i => i.evaluation && i.mode === 'run' && !sent.has(i.job_id)).map(fromLocal);
  } catch { local = null; }
  rows = [...community, ...mine];
  fillFilter('f-agent', rows.map(r => r.agent), v => agents[v] || v);
  fillFilter('f-model', rows.map(r => r.model), v => v);
  fillFilter('f-harness', rows.map(r => r.harness), harnessName);
  render();
}

for (const id of ['f-agent', 'f-model', 'f-harness']) $(id).addEventListener('change', render);
for (const th of document.querySelectorAll('.sort')) th.addEventListener('click', () => {
  sort = {key: th.dataset.key, dir: sort.key === th.dataset.key ? -sort.dir : (th.dataset.key === 'solve' || th.dataset.key === 'tokens' ? 1 : -1)};
  render();
});
load();
