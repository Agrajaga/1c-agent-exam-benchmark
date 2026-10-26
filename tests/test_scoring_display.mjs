import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ruleCharge, rangeNote, practiceCharge} from '../site/scoring-display.js';

test('ranged penalties show the charged minimum separately from the source interval', () => {
  const rule = {id:'GEN01', penalty:{min:'0.5',max:'3.0'}};
  assert.equal(ruleCharge(rule, 'applicable'), '−0.5');
  assert.match(rangeNote(rule), /минимум 0.5/);
  assert.match(rangeNote(rule), /верхней границей/);
  assert.equal(ruleCharge(rule, 'not_applicable'), 'не применяется');
});
test('penalty gates do not claim automatic failure, real gates still do', () => {
  assert.match(ruleCharge({barrier:true,stand_effect:{kind:'penalty',rule:'GEN29'}},'applicable'), /^штраф/);
  assert.equal(ruleCharge({barrier:true},'applicable'), 'незачёт');
});
test('EXM06 references PR14 without inventing another penalty', () => {
  const rules = [{id:'PR14',number:'М7.14',penalty:{min:'0.5',max:'0.5'}}];
  assert.match(practiceCharge({penalty_via:'PR14'},rules), /PR14 \/ М7.14/);
  assert.equal(practiceCharge({},rules), 'без отдельного штрафа');
});
