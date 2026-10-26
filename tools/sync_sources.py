#!/usr/bin/env python3
"""Derive every rule and requirement source (sentences, lines, quote) from the document ledgers.

Edit the ledger (which sentence belongs to which rule), then run this tool; never edit `source` by hand.
`--check` fails if the stored sources differ from the ledgers, without writing anything.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from exam_bench.ledger import check, sources_by_ref, number

SECTION_NUMBER = {'G': 1, 'OU': 2, 'BU': 3, 'PR': 4, 'F': 5}

DOCUMENT = ROOT / 'sources/1c/ATT83PL.txt'
TICKET_HEADS = ('Общие требования', 'Оперативный учет', 'Бухгалтерский учет', 'Сложные периодические расчеты', 'Управляемые формы')
RULE_HEADS = ('Список наиболее часто встречающихся ошибок', 'Оценка результата выполнения задания', 'Форма проведения экзамена')


def heading(lines, n, prefixes):
    for k in range(n, 0, -1):
        text = lines[k - 1].strip()
        if text.startswith(prefixes):
            return {'line': k, 'text': text}
    return None


def sync(pairs, lines, write):
    changed = []
    for items_path, ledger_path, key, heads in pairs:
        doc = json.loads(items_path.read_text())
        ledger = json.loads(ledger_path.read_text())
        items = doc[key]
        problems = check(ledger, lines, {i['id'] for i in items})
        if problems:
            raise SystemExit(f'{ledger_path}: ' + '; '.join(problems[:10]))
        # Readable numbers: document units (М6.4.2 / Б3.7.3), rules by their paragraph, requirements Т<section>.<n>.
        numbers = number(ledger)
        for u in ledger['units']:
            if u.get('n') != numbers[u['id']]:
                u['n'] = numbers[u['id']]
                changed.append(u['id'])
        if write:
            ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=1) + '\n')
        derived = sources_by_ref(ledger)
        for item in items:
            # A rule is numbered by its own item: the first sentence that belongs to it alone and is not
            # a general principle (those carry a note); several rules in one paragraph get sentence numbers.
            own = [u for u in ledger['units'] if u.get('refs') == [item['id']]]
            own = [u for u in own if not u.get('note')] or own
            first = numbers[own[0]['id']] if own else numbers[derived[item['id']]['units'][0]] if item['id'] in derived else None
            paragraph = '.'.join(first.split('.')[:2]) if first else None
            shared = paragraph and any(u.get('refs') and u['refs'] != [item['id']] and '.'.join(numbers[u['id']].split('.')[:2]) == paragraph
                                       and u['kind'] == 'rule' and not u.get('note') for u in ledger['units'])
            label = (f"Т{SECTION_NUMBER[item['section']]}.{int(''.join(c for c in item['id'] if c.isdigit()))}"
                     if key == 'requirements' else first if shared else paragraph)
            if item.get('number') != label:
                item['number'] = label
                changed.append(item['id'])
            if item['id'] not in derived:
                raise SystemExit(f"{item['id']} has no sentence in {ledger_path.name}")
            d = derived[item['id']]
            source = {'document': ledger['document'], 'units': d['units'], 'lines': d['lines'], 'quote': d['quote'],
                      'context': heading(lines, d['lines'][0][0], heads)}
            if 'clause_id' in item.get('source', {}):
                source['clause_id'] = item['source']['clause_id']
            source['numbers'] = [numbers[u] for u in d['units']]
            if item.get('source') != source:
                changed.append(item['id'])
                item['source'] = source
        if key == 'requirements':
            questions = {q['id']: q for q in json.loads((items_path.parent / 'private/questions.json').read_text())['questions']}
            private_rules = {r['id']: r for r in json.loads((items_path.parent / 'private/rules.json').read_text())['rules']}
            for item in items:
                blocked = [q for q in (private_rules.get(item['id'], {}).get('blocked_by') or []) if q in questions]
                # Only still-open questions block a requirement; answered ones disappear from the review list.
                fresh = [{'id': q, 'text': questions[q]['title'], 'interim': questions[q]['boundary'], 'state': questions[q]['state']}
                         for q in blocked if questions[q]['state'] == 'open']
                if item.get('open_questions') != fresh:
                    item['open_questions'] = fresh
                    changed.append(item['id'])
            # Every ticket question with its state, the stand's interim rule and the owner's answer, for the review page.
            listing = [{'id': q['id'], 'text': q['title'], 'state': q['state'], 'interim': q['boundary'], 'answer': q.get('answer'),
                        'requirement_ids': [i['id'] for i in items if q['id'] in (private_rules.get(i['id'], {}).get('blocked_by') or [])
                                            + (private_rules.get(i['id'], {}).get('resolved_questions') or [])]}
                       for q in questions.values()]
            if doc.get('questions') != listing:
                doc['questions'] = listing
                changed.append('questions')
        if write and changed:
            items_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n')
    return changed


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--check', action='store_true')
    args = p.parse_args()
    lines = DOCUMENT.read_text().split('\n')
    pairs = [(ROOT / 'rules/1c-specialist-platform/rules.json', ROOT / 'rules/1c-specialist-platform/ledger.json', 'rules', RULE_HEADS)]
    for ticket in sorted((ROOT / 'tasks').glob('*/checks.json')):
        pairs.append((ticket, ticket.parent / 'ledger.json', 'requirements', TICKET_HEADS))
    changed = sync(pairs, lines, write=not args.check)
    if args.check and changed:
        raise SystemExit('Sources differ from ledgers: ' + ', '.join(changed[:20]))
    print(json.dumps({'updated' if not args.check else 'differs': changed}, ensure_ascii=False))


if __name__ == '__main__':
    main()
