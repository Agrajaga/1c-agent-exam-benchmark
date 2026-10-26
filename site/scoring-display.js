// Display the stand's current policy separately from the unchanged source quotations.
export function ruleCharge(rule, applicability) {
  if (applicability === 'not_applicable') return 'не применяется';
  if (rule.stand_effect?.kind === 'penalty') return `штраф · ${rule.stand_effect.rule} (A02)`;
  return rule.barrier ? 'незачёт' : `−${rule.penalty.min}`;
}

export function rangeNote(rule) {
  return !rule.barrier && rule.penalty && rule.penalty.min !== rule.penalty.max
    ? `В источнике штраф ${rule.penalty.min}–${rule.penalty.max}. Стенд начисляет минимум ${rule.penalty.min} за доказанный дефект (A01); один дефект — один наименьший применимый штраф (A02). При неполном покрытии итоговый балл является верхней границей.` : '';
}

export function practiceCharge(practice, rules) {
  if (practice.penalty) return `−${practice.penalty.points} · ${practice.penalty.rule}`;
  const via = rules.find(r => r.id === practice.penalty_via);
  return via ? `учитывается по ${via.id} / ${via.number} · ${via.penalty.min}` : 'без отдельного штрафа';
}
