// Numeric SemVer ordering: a final release follows its prereleases, RC10 follows RC2.
function compareVersions(a, b) {
  const parse = v => /^(\d+)\.(\d+)\.(\d+)(?:-([^+]+))?(?:\+.*)?$/.exec(v || '');
  const x = parse(a), y = parse(b);
  if (!x || !y) return String(a || '').localeCompare(String(b || ''), 'en', {numeric: true});
  for (let i = 1; i <= 3; i++) {
    if (Number(x[i]) !== Number(y[i])) return Number(x[i]) - Number(y[i]);
  }
  if (!x[4] || !y[4]) return Number(!x[4]) - Number(!y[4]);
  const p = x[4].split('.'), q = y[4].split('.');
  for (let i = 0; i < Math.max(p.length, q.length); i++) {
    if (p[i] === q[i]) continue;
    if (p[i] === undefined || q[i] === undefined) return p[i] === undefined ? -1 : 1;
    const pn = /^\d+$/.test(p[i]), qn = /^\d+$/.test(q[i]);
    if (pn && qn) return Number(p[i]) - Number(q[i]);
    if (pn !== qn) return pn ? -1 : 1;
    return p[i] < q[i] ? -1 : 1;
  }
  return 0;
}

export function groupHarnessVersions(items) {
  const families = new Map();
  for (const item of items) {
    const family = item.family || item.id;
    if (!families.has(family)) families.set(family, []);
    families.get(family).push(item);
  }
  return [...families].map(([family, versions]) => {
    versions.sort((a, b) => compareVersions(b.version, a.version));
    return {family, latest: versions[0], older: versions.slice(1)};
  });
}

export function harnessChoices(items, includeOlder, selected) {
  // Keep an explicitly selected older version visible; never silently switch an exam's tools.
  return groupHarnessVersions(items).flatMap(g => [g.latest,
    ...g.older.filter(h => includeOlder || h.id === selected)]);
}
