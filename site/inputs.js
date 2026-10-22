const $ = id => document.getElementById(id);
// Only the final rule is shown: references to owner decisions and their history are dropped from displayed text.
const tidy = v => String(v ?? '')
  .replace(/\((?:решени[еяю])\s+(?:владельца\s+)?(?:[AАД]\d+|\d{1,2}\.\d{2}(?:\.\d{4})?)(?:\s+отозвано[^),]*)?(?:,\s*([^)]*))?\)/g, (m, rest) => rest ? '(' + rest + ')' : '')
  .replace(/[,;]?\s*[—–-]?\s*решени[еяю]\s+(?:владельца\s+)?(?:[AАД]\d+|\d{1,2}\.\d{2}(?:\.\d{4})?)(\s*:)?/g, (m, colon) => colon ? ':' : '')
  .replace(/\s+([,.;:)])/g, '$1').replace(/\(\s*\)/g, '').replace(/\s{2,}/g, ' ').trim();
const esc = s => tidy(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const size = b => b > 1048576 ? (b / 1048576).toFixed(1) + ' МБ' : b > 1024 ? Math.round(b / 1024) + ' КБ' : b + ' Б';
const HARNESS = {'none': 'Без харнеса', 'unica-0.12.3': 'Unica 0.12.3', 'unica-0.13.0': 'Unica 0.13.0', 'shirokov-skills': 'Skills Широкова'};

function file(f) {
  const meta = [f.lines ? f.lines + ' строк' : null, size(f.bytes)].filter(Boolean).join(' · ');
  const head = `<code>${esc(f.path)}</code><span class="purpose">${esc(f.purpose)}</span><span class="meta">${esc(meta)}</span>`;
  if (f.kind === 'image') return `<li class="file"><details><summary>${head}</summary><img class="figure" src="${esc(f.href)}" alt="${esc(f.path)}" loading="lazy"></details></li>`;
  if (f.kind === 'text') return `<li class="file"><details data-src="${esc(f.href)}"><summary>${head}</summary><pre class="content">Загрузка…</pre></details></li>`;
  return `<li class="file"><div class="row"><code>${esc(f.path)}</code><span class="purpose">${esc(f.purpose)}</span><a class="meta" href="${esc(f.href)}" download>скачать · ${esc(size(f.bytes))}</a></div></li>`;
}

async function main() {
  const data = await (await fetch('inputs.json')).json();
  const past = data.runs.filter(r => !r.upcoming);
  const latest = past.map(r => r.worker.input_revision);
  $('facts').innerHTML = `<li>Текущая выдача: <b>${esc(data.input_revision)}</b></li>`
    + `<li>Прогоны на сайте получили: <b>${esc([...new Set(latest)].join(', ') || '—')}</b></li>`;
  $('prompt').textContent = data.prompt;
  const ticket = data.tickets[0];
  const order = p => ['task/statement.docx', 'task/statement.txt', 'task/assets/'].findIndex(x => p.startsWith(x));
  ticket.files.sort((a, b) => ((order(a.path) + 1 || 9) - (order(b.path) + 1 || 9)) || a.path.localeCompare(b.path));
  const task = `<li class="dir"><code>task/</code><span class="purpose">Материалы билета «${esc(ticket.title)}» — копия публичной части билета</span><ul>${ticket.files.map(file).join('')}</ul></li>`;
  // worker.json and v8project.yaml differ by environment: show each run's copy with a switch.
  const perRun = path => data.runs.filter(r => r.files && r.files[path] != null);
  const switcher = path => perRun(path).map((r, i) => `<button class="env-tab${i ? '' : ' on'}" data-file="${esc(path)}" data-run="${esc(r.run_id)}">${r.upcoming ? 'Текущая выдача' : esc(HARNESS[r.worker.harness] || r.worker.harness)}</button>`).join('');
  const workspaceItem = w => perRun(w.path).length
    ? `<li class="dir"><details><summary><code>${esc(w.path)}</code><span class="purpose">${esc(w.purpose)}</span><span class="meta">по окружениям</span></summary>
        <div class="env-tabs">${switcher(w.path)}</div><pre class="content" data-content="${esc(w.path)}">${esc(perRun(w.path)[0].files[w.path])}</pre></details></li>`
    : `<li class="dir"><div class="row"><code>${esc(w.path)}</code><span class="purpose">${esc(w.purpose)}</span></div></li>`;
  $('tree').innerHTML = task + data.workspace.map(workspaceItem).join('');
  document.addEventListener('click', e => {
    const b = e.target.closest('.env-tab');
    if (!b) return;
    const run = data.runs.find(r => r.run_id === b.dataset.run);
    b.parentElement.querySelectorAll('.env-tab').forEach(x => x.classList.toggle('on', x === b));
    b.closest('details').querySelector('[data-content]').textContent = run.files[b.dataset.file];
  });
  $('runs').innerHTML = `<table><thead><tr><th>Окружение</th><th>Модель</th><th>Лимит</th><th>Харнес</th><th>Выдача</th></tr></thead><tbody>${past.map(r => `<tr>
    <td>${esc(HARNESS[r.worker.harness] || r.worker.harness)}</td>
    <td>${esc(r.worker.model)}${r.worker.reasoning_effort ? ', ' + esc(r.worker.reasoning_effort) : ''}</td>
    <td>${Math.round(r.worker.solve_timeout_seconds / 60)} мин</td>
    <td>${r.harness.skills ? r.harness.skills + ' skills' : '—'}${r.harness.mcp.length ? ' · MCP' : ''}</td>
    <td>${esc(r.worker.input_revision)}</td></tr>`).join('')}</tbody></table>`;
  $('withheld').innerHTML = data.withheld.map(w => `<li>${esc(w)}</li>`).join('');
  document.addEventListener('toggle', async e => {
    const d = e.target;
    if (!d.open || !d.dataset.src || d.dataset.loaded) return;
    d.dataset.loaded = '1';
    const text = await (await fetch(d.dataset.src)).text();
    d.querySelector('.content').textContent = text;
  }, true);
}
main();
