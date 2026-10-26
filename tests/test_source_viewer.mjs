import assert from 'node:assert/strict';
import {test} from 'node:test';
import {tokenizeBSL} from '../site/source-viewer.js';

test('BSL highlighting preserves text and distinguishes strings, comments and keywords', () => {
  const line = 'Если А = "КонецЕсли // <img>" Тогда // комментарий';
  const tokens = tokenizeBSL(line);
  assert.equal(tokens.map(t => t.text).join(''), line);
  assert.deepEqual(tokens.filter(t => t.kind === 'keyword').map(t => t.text), ['Если', 'Тогда']);
  assert.equal(tokens.find(t => t.kind === 'string').text, '"КонецЕсли // <img>"');
  assert.equal(tokens.find(t => t.kind === 'comment').text, '// комментарий');
});

test('multiline strings retain their state and escaped quotes are not boundaries', () => {
  const state = {quoted: false};
  tokenizeBSL('Текст = "Первая строка', state);
  assert.equal(state.quoted, true);
  const tokens = tokenizeBSL('|Вторая ""часть"""; Возврат;', state);
  assert.equal(state.quoted, false);
  assert.equal(tokens[0].kind, 'string');
  assert.equal(tokens.find(t => t.text === 'Возврат').kind, 'keyword');
});
