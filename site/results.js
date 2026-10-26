import {$, node, get, post, ask, duration, scoreText, gradeText, checksText, harnessLabel, date} from './local.js';
import {renderSubmit} from './submit.js';

const STATES = {queued: 'В очереди', preparing: 'Подготовка', solving: 'Агент решает', checking_gates: 'Загрузка в 1С',
  grading: 'Проверка в 1С', publishing: 'Оценка', failed: 'Остановлен', invalid_submission: 'Нет корректной сдачи',
  rejected: 'Не прошла условия', finished: 'Завершён'};
let signature = '';

async function refresh() {
  let results, community, readiness;
  try {
    [results, community, readiness] = await Promise.all([get('api/results').then(r => r.results), get('api/community'), get('api/readiness')]);
  } catch {
    $('empty').hidden = false;
    $('empty').textContent = 'Локальный стенд не запущен. Эта страница работает только из клона репозитория.';
    return;
  }
  const next = JSON.stringify([results, community.action, readiness.steps[0]]);
  if (next === signature) return;
  signature = next;
  const githubReady = readiness.steps.find(s => s.id === 'github')?.state === 'ok';
  $('empty').hidden = results.length > 0;
  $('rows').replaceChildren(...results.map(item => {
    const e = item.evaluation, tr = node('tr');
    const when = node('td', date(item.started_unix));
    const env = node('td', harnessLabel(item.harness));
    env.append(node('small', [item.agent === 'claude' ? 'Claude Code' : 'Codex', e?.model || item.model].filter(Boolean).join(' · ')));
    if (item.mode === 'regrade') env.append(node('small', e?.binding_compatibility
      ? 'Дополнительная оценка с адаптацией привязок' : 'Повторная оценка сохранённой сдачи'));
    const score = node('td');
    if (e) {
      score.append(node('b', scoreText(e)));
      if (gradeText(e)) score.append(node('small', gradeText(e)));
    } else {
      score.append(node('span', STATES[item.phase] || item.phase, 'badge' + (item.phase === 'finished' ? '' : item.error ? ' fail' : ' warn')));
      if (item.error) score.append(node('small', item.error));
    }
    const checks = node('td', e ? checksText(e) : '—', 'num');
    const time = node('td', e ? duration(e.solve_seconds) : '—', 'num');
    const send = node('td');
    const box = node('div', null, 'actions');
    if (e) {
      renderSubmit(box, item, community, githubReady, refresh);
    }
    const action = community.action?.id === item.job_id ? community.action : null;
    if (item.deletable && !action?.pr_url) {
      const remove = node('button', 'Удалить', 'btn small');
      remove.disabled = action?.phase === 'working';
      remove.addEventListener('click', async () => {
        remove.disabled = true;
        try {
          if (!await ask('Удалить результат из «Моих результатов»? Исходные материалы запуска сохранятся для повторных оценок.', 'Удалить')) return;
          await post('api/community/delete', {id: item.job_id});
          await refresh();
        } catch (error) {
          box.append(node('p', error.message, 'message error'));
        } finally {
          remove.disabled = false;
        }
      });
      box.append(remove);
    }
    send.append(box);
    tr.append(when, env, score, checks, time, send);
    return tr;
  }));
}

refresh();
setInterval(refresh, 5000);
