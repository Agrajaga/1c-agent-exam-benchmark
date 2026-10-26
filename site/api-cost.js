// Illustrative standard short-context API rates, USD per million tokens, checked 2026-10-27.
// Not a bill: counters do not establish request-level context tiers, cache writes or service tier.
export const API_PRICES = {
  'gpt-6.1-sol': {input: 2, cached: 0.10, output: 10},
  'gpt-6-astra': {input: 10, cached: 1, output: 50},
};
export const API_PRICE_SOURCE = 'https://developers.openai.com/api/docs/pricing';
export function estimateApiCost(model, tokens) {
  const rate = API_PRICES[model];
  const {input, cached_input: cached, fresh_input: fresh, output} = tokens || {};
  if (!rate || ![input, cached, fresh, output].every(n => Number.isSafeInteger(n) && n >= 0)
      || cached + fresh !== input) return null;
  return (fresh * rate.input + cached * rate.cached + output * rate.output) / 1e6;
}
