// Exercise the page's real event handlers with controlled network and dialog replies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
  constructor(tag, text) { this.tag = tag; this.textContent = text; this.children = []; this.handlers = {}; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  addEventListener(event, handler) { this.handlers[event] = handler; }
}

async function page(item, action = null) {
  const rows = new Element('tbody'), empty = new Element('p');
  const requests = [];
  let answer = false, failure = null, items = [item], confirmations = 0;
  const context = {
    $: id => id === 'rows' ? rows : empty,
    node: (tag, text) => new Element(tag, text),
    date: () => 'date', harnessLabel: x => x, duration: () => '',
    renderSubmit: () => {},
    get: async url => url === 'api/results' ? {results: items} : url === 'api/community' ? {action} : {steps: []},
    ask: async () => { confirmations++; return answer; },
    post: async (url, data) => { requests.push({url, data}); if (failure) throw Error(failure); items = []; },
  };
  const source = fs.readFileSync(path.join(__dirname, '../site/results.js'), 'utf8')
    .replace(/^import .*\n/gm, '').replace(/\nrefresh\(\);\nsetInterval[^]*$/, '');
  vm.createContext(context);
  vm.runInContext(source, context);
  await context.refresh();
  const box = rows.children[0].children.at(-1).children[0];
  return {rows, box, requests, get confirmations() { return confirmations; },
    button: box.children.find(e => e.tag === 'button'),
    confirm: () => { answer = true; }, fail: message => { failure = message; }};
}

(async () => {
  const item = {job_id: 'demo-test', phase: 'failed', deletable: true, started_unix: 1};
  let p = await page(item);
  assert.equal(p.button.textContent, 'Удалить');
  await p.button.handlers.click();
  assert.equal(p.confirmations, 1);
  assert.equal(p.requests.length, 0, 'cancel must not send a request');
  assert.equal(p.rows.children.length, 1);
  assert.equal(p.button.disabled, false);

  p.confirm();
  await p.button.handlers.click();
  assert.equal(p.requests[0].url, 'api/community/delete');
  assert.equal(p.requests[0].data.id, 'demo-test');
  assert.equal(p.rows.children.length, 0, 'successful deletion refreshes history');

  p = await page(item); p.confirm(); p.fail('Результат уже отправлен в рейтинг');
  await p.button.handlers.click();
  assert.equal(p.rows.children.length, 1);
  assert.equal(p.box.children.at(-1).textContent, 'Результат уже отправлен в рейтинг');
  assert.equal(p.button.disabled, false, 'failed request can be retried');

  assert.equal((await page({...item, deletable: false})).button, undefined);
  assert.equal((await page(item, {id: item.job_id, phase: 'finished', pr_url: 'https://github.com/x/pull/1'})).button, undefined);
  assert.equal((await page(item, {id: item.job_id, phase: 'working'})).button.disabled, true);
  console.log('Result deletion UI: cancel, success, failure, PR and busy guards passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
