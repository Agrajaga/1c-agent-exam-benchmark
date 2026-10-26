"""The three agent inputs stay consistent: starter, rulebook, and per-ticket checks."""
import json
import unittest
from pathlib import Path
from exam_bench.grader import PROFILE

ROOT = Path(__file__).parents[1]


def read(path):
    return json.loads((ROOT / path).read_text())


class ChecksCatalogueTest(unittest.TestCase):
    def setUp(self):
        self.tickets = [read(p.relative_to(ROOT)) for p in sorted((ROOT / 'tasks').glob('*/checks.json'))]
        self.assertTrue(self.tickets)

    def test_ticket_references_existing_starter_and_rulebook(self):
        for t in self.tickets:
            self.assertTrue((ROOT / 'starters' / t['starter'] / 'starter.json').is_file())
            book = read(f"rules/{t['rulebook']}/rules.json")
            ids = {r['id'] for r in book['rules']}
            self.assertEqual({r['rule_id'] for r in t['official_rules']}, ids, 'every rule needs a ticket applicability')
            for r in book['rules']:
                self.assertTrue(r['stand_check']['how'] and r['stand_check']['methods'], r['id'])
                self.assertIn(r['stand_check']['readiness'], book['readiness'])

    def test_requirements_match_private_rules_and_grader(self):
        for t in self.tickets:
            private = read(f"tasks/{t['ticket_id']}/private/rules.json")['rules']
            self.assertEqual([r['id'] for r in t['requirements']], [r['id'] for r in private])
            claimed = {r['id'] for r in t['requirements'] if r['stand']['status'] in ('checked', 'partial')}
            self.assertEqual(claimed, set(PROFILE['rules']), 'site must not claim checks the grader does not run')
            sections = {s['id'] for s in t['sections']}
            self.assertTrue(all(r['section'] in sections for r in t['requirements']))

    def test_document_ledgers_are_complete_and_drive_every_source(self):
        """Every sentence of the source document is classified once; sources are derived from it, not typed."""
        from exam_bench.ledger import check, sources_by_ref
        text = ROOT / 'sources/1c/ATT83PL.txt'
        lines = text.read_text(encoding='utf-8').split('\n')
        for t in self.tickets:
            book = read(f"rules/{t['rulebook']}/rules.json")
            for items, ledger_path in ((book['rules'], f"rules/{t['rulebook']}/ledger.json"),
                                       (t['requirements'], f"tasks/{t['ticket_id']}/ledger.json")):
                ledger = read(ledger_path)
                ids = {i['id'] for i in items}
                self.assertEqual(check(ledger, lines, ids), [], ledger_path)
                derived = sources_by_ref(ledger)
                self.assertEqual(set(derived), ids, f'{ledger_path}: every item needs at least one sentence')
                for item in items:
                    self.assertEqual({k: item['source'][k] for k in ('units', 'lines', 'quote')}, derived[item['id']], item['id'])
            decisions = book['sources']['owner-scoring-policy-v4']['decisions']
            for r in book['rules']:
                self.assertTrue(set(r['owner_decisions']) <= set(decisions), r['id'])

    def test_ticket_and_rule_ranges_cover_the_whole_document(self):
        for t in self.tickets:
            rules_range = read(f"rules/{t['rulebook']}/ledger.json")['range']
            ticket_range = read(f"tasks/{t['ticket_id']}/ledger.json")['range']
            self.assertEqual(rules_range[1] + 1, ticket_range[0], 'no lines between the rules part and the ticket')
            self.assertEqual(rules_range[0], 1)

    def test_readable_numbers_are_unique_and_current(self):
        from exam_bench.ledger import number
        for t in self.tickets:
            book = read(f"rules/{t['rulebook']}/rules.json")
            for ledger_path in (f"rules/{t['rulebook']}/ledger.json", f"tasks/{t['ticket_id']}/ledger.json"):
                ledger = read(ledger_path)
                numbers = number(ledger)
                self.assertEqual({u['id']: u['n'] for u in ledger['units']}, numbers, 'run tools/sync_sources.py')
            for items in (book['rules'], t['requirements']):
                labels = [i['number'] for i in items]
                self.assertEqual(len(labels), len(set(labels)), 'numbers must be unique')

    def test_owner_decisions_are_anchored_to_existing_places(self):
        for t in self.tickets:
            book = read(f"rules/{t['rulebook']}/rules.json")
            decisions = read(f"rules/{t['rulebook']}/decisions.json")['items']
            rule_units = {u['id'] for u in read(f"rules/{t['rulebook']}/ledger.json")['units']}
            ticket_units = {u['id'] for u in read(f"tasks/{t['ticket_id']}/ledger.json")['units']}
            rules = {r['id'] for r in book['rules']}
            reqs = {r['id'] for r in t['requirements']}
            for d in decisions:
                a = d['anchors']
                self.assertTrue(a['units'] or a['rules'], d['id'])
                self.assertTrue(set(a['units']) <= rule_units and set(a['ticket_units']) <= ticket_units, d['id'])
                self.assertTrue(set(a['rules']) <= rules and set(a['requirements']) <= reqs, d['id'])
                self.assertTrue(d['decision'] or d['open_part'], d['id'])

    def test_no_oracle_values_published(self):
        for t in self.tickets:
            text = json.dumps(t, ensure_ascii=False)
            self.assertNotIn('"oracle"', text)
            self.assertNotIn('expected', text)


if __name__ == '__main__':
    unittest.main()
