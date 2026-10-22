"""The solver's own list of ambiguous places in the ticket, compared afterwards with the stand's answers.

Not part of grading: it never changes a verdict. It shows where the agent and the checker read the
statement differently, so a failed requirement can be told apart from a different reading.
"""
import json
import re
from pathlib import Path

FILE = 'interpretations.json'
FIELDS = ('quote', 'question', 'interpretation', 'implementation')
LIMIT = 50


def read(out):
    """{'status': present|missing|invalid, 'items': [...], 'reason'?}. Missing is recorded, not a submission error."""
    path = Path(out) / FILE
    if not path.is_file():
        return {'status': 'missing', 'items': []}
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        items = data['items']
        if data.get('schema_version') != 1 or not isinstance(items, list) or len(items) > LIMIT:
            raise ValueError('schema_version 1 and at most %d items expected' % LIMIT)
        clean = []
        for item in items:
            if not isinstance(item, dict) or not all(isinstance(item.get(k), str) and item[k].strip() for k in FIELDS[:3]):
                raise ValueError('each item needs non-empty quote, question and interpretation')
            clean.append({k: str(item.get(k) or '')[:2000] for k in FIELDS})
        return {'status': 'present', 'items': clean}
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return {'status': 'invalid', 'items': [], 'reason': str(exc)[:300]}


def _words(text):
    return {w for w in re.findall(r'[а-яёa-z0-9]+', text.lower().replace('ё', 'е')) if len(w) > 2}


def locate(quote, ledger):
    """Ticket sentences the quote refers to: exact containment first, otherwise the best word overlap (>= 60%)."""
    norm = lambda s: re.sub(r'\s+', ' ', s.lower().replace('ё', 'е')).strip(' .,;:«»"')
    q = norm(quote)
    exact = [u for u in ledger['units'] if q and (q in norm(u['text']) or norm(u['text']) in q and len(norm(u['text'])) > 20)]
    if exact:
        return exact
    words = _words(quote)
    if not words:
        return []
    scored = sorted(((len(words & _words(u['text'])) / len(words), u) for u in ledger['units']), key=lambda x: -x[0])
    return [scored[0][1]] if scored and scored[0][0] >= 0.6 else []


def compare(items, ledger, requirements, questions):
    """Each agent interpretation with the ticket place it cites and the stand's questions/answers for that place."""
    unit_reqs = {}
    for r in requirements:
        for u in r['source']['units']:
            unit_reqs.setdefault(u, []).append(r['id'])
    by_req = {}
    for q in questions:
        for rid in q.get('requirement_ids', []):
            by_req.setdefault(rid, []).append(q)
    out = []
    for item in items:
        units = locate(item['quote'], ledger)
        reqs = sorted({rid for u in units for rid in unit_reqs.get(u['id'], [])})
        stand = {q['id']: q for rid in reqs for q in by_req.get(rid, [])}
        out.append({**item, 'places': [u['n'] for u in units], 'requirements': reqs,
                    'stand_questions': [{'id': q['id'], 'question': q['text'], 'answer': q.get('answer'), 'state': q['state']}
                                        for q in sorted(stand.values(), key=lambda q: q['id'])]})
    return out
