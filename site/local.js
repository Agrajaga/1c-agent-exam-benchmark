// Helpers shared by the local stand pages: requests with the CSRF token and result formatting.
let token = null;

export const $ = id => document.getElementById(id);

export function node(tag, text, cls) {
  const n = document.createElement(tag);
  if (text != null) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}

export async function get(path) {
  const response = await fetch(path, {cache: 'no-store'});
  if (!response.ok) throw new Error('Локальный стенд не отвечает');
  const data = await response.json();
  if (data.csrf) token = data.csrf;
  return data;
}

export async function post(path, data = {}) {
  if (!token) await get('api/readiness');
  const response = await fetch(path, {method: 'POST', body: JSON.stringify(data),
    headers: {'Content-Type': 'application/json', 'X-Demo-Token': token}});
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || 'Действие не выполнено');
  return result;
}

// In-page confirmation: embedded browsers may silently answer window.confirm() with false.
export function ask(text, yes = 'Да, продолжить') {
  return new Promise(resolve => {
    const dialog = node('dialog', null, 'ask');
    const buttons = node('div', null, 'actions');
    const ok = node('button', yes, 'btn primary'), cancel = node('button', 'Отмена', 'btn');
    buttons.append(ok, cancel);
    dialog.append(node('p', text), buttons);
    const close = answer => { dialog.close(); dialog.remove(); resolve(answer); };
    ok.addEventListener('click', () => close(true));
    cancel.addEventListener('click', () => close(false));
    dialog.addEventListener('cancel', e => { e.preventDefault(); close(false); });
    document.body.append(dialog);
    dialog.showModal();
    ok.focus();
  });
}

export const duration = seconds => {
  const s = Math.max(0, Math.round(seconds));
  return s >= 3600 ? `${Math.floor(s / 3600)}:${String(Math.floor(s / 60) % 60).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
    : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};

const number = value => String(value).replace('.', ',');
const grades = {unsatisfactory: 'Неудовлетворительно', satisfactory: 'Удовлетворительно', good: 'Хорошо', excellent: 'Отлично'};

export function scoreText(e) {
  if (e.score != null) return `${number(e.score)} из 5`;
  return `не выше ${number(Math.max(0, e.score_upper_bound))} из 5`;
}

export const gradeText = e => grades[e.grade] || '';

export function checksText(e) {
  const total = Object.values(e.counts || {}).reduce((a, b) => a + b, 0);
  return `${e.counts?.pass || 0} из ${total}`;
}

export const harnessLabel = id => id === 'none' ? 'Без харнеса' : id;

export const date = unix => new Date(unix * 1000).toLocaleString('ru-RU', {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});
