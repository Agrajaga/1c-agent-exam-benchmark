import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('../site/api-cost.js', import.meta.url), 'utf8');
const {estimateApiCost} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));

const usage = {input: 20691000, fresh_input: 291000, cached_input: 20400000, output: 151000};
assert.ok(Math.abs(estimateApiCost('gpt-6.1-sol', usage) - 4.132) < 1e-9);
assert.equal(estimateApiCost('unknown-model', usage), null);
assert.equal(estimateApiCost('gpt-6.1-sol', {...usage, cached_input: null}), null);
assert.equal(estimateApiCost('gpt-6.1-sol', {...usage, input: 1}), null);
assert.equal(estimateApiCost('gpt-6.1-sol', {input: 0, fresh_input: 0, cached_input: 0, output: 0}), 0);
