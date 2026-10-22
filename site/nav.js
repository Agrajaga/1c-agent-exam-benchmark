// One menu for every page. Without the local server (GitHub Pages) only the leaderboard exists.
const nav = document.querySelector('nav.tabs');
const here = location.pathname.split('/').pop() || 'index.html';
const section = {'inputs.html': 'checks.html'}[here] || here;
const repository = 'https://github.com/zeegin/1c-agent-exam-benchmark';

function link(href, label, current) {
  const a = document.createElement('a');
  a.href = href; a.textContent = label;
  if (href === current) a.setAttribute('aria-current', 'page');
  return a;
}

function draw(local) {
  const items = local
    ? [['index.html', 'Замер'], ['results.html', 'Мои результаты'], ['leaderboard.html', 'Рейтинг'], ['checks.html', 'Методика']]
    : [['leaderboard.html', 'Рейтинг']];
  // On Pages the leaderboard is also served as index.html.
  const current = !local && section === 'index.html' ? 'leaderboard.html' : section;
  nav.replaceChildren(...items.map(([href, label]) => link(href, label, current)));
  if (!local) nav.append(link(repository + '#readme', 'Как участвовать'));
}

if (nav) {
  nav.setAttribute('aria-label', 'Разделы сайта');
  // The exam name sits above the menu on every page.
  const badge = document.createElement('div');
  badge.className = 'eyebrow site-badge';
  badge.textContent = 'Экзамен 1С:Специалист по платформе';
  nav.before(badge);
  draw(true);
  draw(await fetch('api/readiness', {cache: 'no-store'}).then(r => r.ok).catch(() => false));
}
