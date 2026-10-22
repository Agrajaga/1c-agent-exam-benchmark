// "Send to the leaderboard": build the package, show what goes into the PR, send only after confirmation.
import {node, post} from './local.js';

const PR = /^https:\/\/github\.com\/zeegin\/1c-agent-exam-benchmark\/pull\/\d+$/;

function button(label, cls, onClick, disabled) {
  const b = node('button', label, 'btn ' + cls);
  b.disabled = disabled;
  b.addEventListener('click', async () => {
    b.disabled = true;
    try { await onClick(); } catch (error) { b.parentElement?.append(node('p', error.message, 'message error')); }
  });
  return b;
}

export function renderSubmit(box, item, community, githubReady, refresh) {
  const action = community?.action?.id === item.job_id ? community.action : null;
  const otherBusy = community?.action?.phase === 'working' && !action;
  const working = action?.phase === 'working';
  const url = item.pr_url || action?.pr_url;
  const prepared = item.prepared || (action?.action === 'prepare' && action.phase === 'finished');
  const children = [];
  if (url && PR.test(url)) {
    const a = node('a', 'Открыть PR', 'btn small'); a.href = url; a.target = '_blank'; a.rel = 'noopener';
    children.push(node('span', 'Отправлено в рейтинг ', 'badge pass'), a);
  } else if (working) {
    children.push(node('span', action.action === 'pr' ? 'Создаём PR в вашем форке…' : 'Собираем пакет: DT из XML в свежей базе…', 'badge warn'));
  } else if (prepared) {
    const download = node('a', 'Скачать пакет', 'btn small');
    download.href = 'api/community/download?id=' + encodeURIComponent(item.job_id);
    children.push(download, button('Отправить PR', 'small primary', async () => {
      await post('api/community/pr', {id: item.job_id}); await refresh();
    }, otherBusy || !githubReady));
    if (action?.measurement) {
      const review = node('details');
      review.append(node('summary', 'Что уйдёт в PR'), node('pre', JSON.stringify({
        author: action.measurement.operator, hardware: action.measurement.environment.hardware, os: action.measurement.environment.os,
        conditions: action.conditions, files: action.file_count, bytes: action.bytes}, null, 2), 'review'));
      children.push(review);
    }
  } else {
    children.push(button('Отправить в рейтинг', 'small primary', async () => {
      await post('api/community/prepare', {id: item.job_id}); await refresh();
    }, otherBusy || !githubReady));
  }
  if (!githubReady && !url) children.push(node('small', 'Нужен вход в GitHub на странице «Замер».'));
  if (action?.phase === 'failed') children.push(node('p', action.error || 'Действие не выполнено.', 'message error'));
  box.replaceChildren(...children);
}
