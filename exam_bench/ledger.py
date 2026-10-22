"""Line-and-sentence ledger of a source document: every sentence is classified exactly once.

The ledger is the single source of traceability. Rule and requirement sources (line numbers and
verbatim quotes) are derived from it, so a requirement cannot cite text the ledger does not assign to it.
"""
import re

# A sentence ends with . ! ? followed by a capital letter or an opening quote/bracket.
_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[А-ЯЁA-Z«"(])')

KINDS = {
    'requirement': 'Требование билета',
    'rule': 'Правило оценивания',
    'scoring': 'Порядок оценки',
    'procedure': 'Процедура экзамена',
    'heading': 'Заголовок',
    'info': 'Справочный текст',
    'example': 'Пример данных',
    'figure': 'Рисунок',
    'gap': 'Не разобрано — нужно решение',
}
NEEDS_REFS = {'requirement', 'rule', 'example'}


def units(lines, first=1, last=None):
    """Sentence units of non-empty lines first..last (1-based, inclusive), in document order."""
    last = last or len(lines)
    out = []
    for n in range(first, last + 1):
        text = lines[n - 1].strip()
        if not text:
            continue
        parts = [p.strip() for p in _SPLIT.split(text) if p.strip()]
        merged = []
        for p in parts:
            # "Рис.1." is a caption number, and a short trailing "Например:" introduces what follows.
            if merged and re.fullmatch(r'Рис\.\d+\.', merged[-1]):
                merged[-1] += ' ' + p
            elif merged and p.endswith(':') and len(p) < 20:
                merged[-1] += ' ' + p
            else:
                merged.append(p)
        for i, p in enumerate(merged, 1):
            out.append({'id': str(n) if len(merged) == 1 else f'{n}.{i}', 'line': n, 'text': p})
    return out


def check(ledger, lines, known_ids):
    """Problems that make the ledger incomplete or inconsistent with the document; empty list means complete."""
    problems = []
    expected = units(lines, *ledger['range'])
    got = [{k: u[k] for k in ('id', 'line', 'text')} for u in ledger['units']]
    if got != expected:
        missing = {u['id'] for u in expected} - {u['id'] for u in got}
        extra = {u['id'] for u in got} - {u['id'] for u in expected}
        problems.append(f'ledger text differs from the document: missing {sorted(missing)[:10]}, extra {sorted(extra)[:10]}'
                        + ('' if missing or extra else ', changed text in some units'))
    for u in ledger['units']:
        if u.get('kind') not in KINDS:
            problems.append(f"{u['id']}: unknown kind {u.get('kind')!r}")
        refs = u.get('refs', [])
        if u.get('kind') in NEEDS_REFS and not refs:
            problems.append(f"{u['id']}: kind {u['kind']} needs refs")
        for r in refs:
            if r not in known_ids:
                problems.append(f"{u['id']}: unknown ref {r}")
        if u.get('kind') == 'gap' and not u.get('note'):
            problems.append(f"{u['id']}: gap needs a note explaining what must be decided")
    return problems


def sources_by_ref(ledger, kinds=('requirement', 'rule')):
    """ref id -> {'units', 'lines', 'quote'} derived from the ledger units of the given kinds."""
    acc = {}
    for u in ledger['units']:
        if u['kind'] not in kinds:
            continue
        for r in u.get('refs', []):
            acc.setdefault(r, []).append(u)
    out = {}
    for ref, us in acc.items():
        lines, quote, prev = [], '', None
        for u in us:
            n = u['line']
            if lines and n <= lines[-1][1] + 1:
                lines[-1][1] = max(lines[-1][1], n)
            else:
                lines.append([n, n])
            quote += ('' if prev is None else (' ' if n == prev else '\n')) + u['text']
            prev = n
        out[ref] = {'units': [u['id'] for u in us], 'lines': lines, 'quote': quote}
    return out


def number(ledger):
    """Readable numbers from the authored outline: section, paragraph, sentence (e.g. "Б3.7.3").

    A paragraph is a run of consecutive units with the same classification (kind, refs, note); several
    sentences of one source line always stay in one paragraph. Headings carry the section number only.
    Returns {unit id: number}.
    """
    numbers = {}
    for section in ledger['outline']:
        units_in = [u for u in ledger['units'] if section['first'] <= u['line'] <= section['last']]
        paragraphs, prev = [], None
        for u in units_in:
            if u['kind'] == 'heading':
                numbers[u['id']] = section['id']
                prev = None
                continue
            signature = (u['kind'], tuple(u.get('refs', [])), u.get('note'))
            same_line = prev is not None and prev[0]['line'] == u['line']
            continues = prev is not None and prev[1] == signature and u['line'] - prev[0]['line'] <= 2
            if same_line or continues:
                paragraphs[-1].append(u)
            else:
                paragraphs.append([u])
            prev = (u, signature)
        for p, units_p in enumerate(paragraphs, 1):
            for s, u in enumerate(units_p, 1):
                numbers[u['id']] = f"{section['id']}.{p}" + (f'.{s}' if len(units_p) > 1 else '')
    missing = [u['id'] for u in ledger['units'] if u['id'] not in numbers]
    if missing:
        raise ValueError('Units outside the outline: ' + ', '.join(missing[:10]))
    return numbers
