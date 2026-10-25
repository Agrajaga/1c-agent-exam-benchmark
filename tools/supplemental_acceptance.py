"""Separate acceptance for subconto bindings the submission check refused when the attempt was made.

Indexed names (СубконтоДт1) are proved from the goods account metadata; kind names (Номенклатура,
СубконтоДт.Номенклатура) are expanded by the current canonical_ledger. The original invalid submission,
its status and every source byte remain unchanged; the grade is a separate one.
"""
import argparse
import copy
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET
from tools.community_results import ROOT, check_id, read, write, digest


def normalize(src, original):
    from exam_bench.submission import subconto_kinds, check_bindings, strip_extras, canonical_ledger
    clean, _ = strip_extras(original)
    account = clean['objects']['accounts'].split('.', 1)[1]
    ns = '{http://v8.1c.ru/8.3/xcf/predef}'
    tree = ET.parse(Path(src) / 'ChartsOfAccounts' / account / 'Ext/Predefined.xml')
    goods = [n for n in tree.iter(ns + 'Item') if n.findtext(ns + 'Code') == clean['account_codes']['goods']]
    if len(goods) != 1:
        raise ValueError('Exactly one predefined goods account is required')
    ordered = [n.attrib['name'].removeprefix('ChartOfCharacteristicTypes.') for n in goods[0].findall(ns + 'ExtDimensionTypes/' + ns + 'ExtDimensionType')]
    kinds = subconto_kinds(Path(src), clean['objects']['accounts'])
    changes = []
    for role in ('item_debit', 'item_credit', 'warehouse_debit', 'warehouse_credit'):
        value = clean['fields']['ledger'][role]
        match = re.fullmatch(r'Субконто(Дт|Кт)([1-9][0-9]*)', value)
        if not match:
            continue
        if match[1] != ('Дт' if role.endswith('debit') else 'Кт'):
            raise ValueError('Subconto side differs from its ledger role')
        index = int(match[2]) - 1
        if index >= len(ordered) or ordered[index] not in kinds:
            raise ValueError('No predefined kind at this goods-account position')
        replacement = ordered[index]
        changes.append({'field': 'fields.ledger.' + role, 'before': value, 'after': replacement, 'kind': 'indexed'})
        clean['fields']['ledger'][role] = replacement
    named, _ = canonical_ledger(src, clean)
    for role in ('item_debit', 'item_credit', 'warehouse_debit', 'warehouse_credit'):
        before, after = clean['fields']['ledger'][role], named['fields']['ledger'][role]
        if before != after:
            changes.append({'field': 'fields.ledger.' + role, 'before': before, 'after': after, 'kind': 'named'})
    if not changes:
        raise ValueError('No subconto bindings to normalize')
    clean = named
    # Trusted metadata type checking must accept every projected role.
    check_bindings(src, clean)
    return clean, changes


def prepare(run_id, root=ROOT):
    check_id(run_id)
    run = root / '.local/runs' / run_id
    original = read(run / 'artifacts/binding.json')
    normalized, changes = normalize(run / 'artifacts/src', original)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    job_id = 'demo-' + stamp + '-adapter'
    job = root / '.local/demo/jobs' / job_id
    job.mkdir(parents=True)
    write(job / 'binding-adapter.json', normalized)
    indexed = any(c['kind'] == 'indexed' for c in changes)
    write(job / 'binding-adapter-proof.json', {
        'scope': 'supplemental_indexed_subconto_adapter' if indexed else 'supplemental_named_subconto_adapter',
        'original_binding_sha256': digest(run / 'artifacts/binding.json'), 'normalized_binding_sha256': digest(job / 'binding-adapter.json'),
        'normalizer_sha256': digest(__file__), 'canonical_ledger_sha256': digest(ROOT / 'exam_bench/submission.py'), 'changes': changes,
        'basis': ('Ordered predefined subconto kinds of the declared goods account; ' if indexed else '') +
                 'kind names expanded only to exactly one predefined kind of the account chart on the role side; all role types checked.'})
    write(job / 'status.json', {'job_id': job_id, 'run_id': run_id, 'mode': 'regrade', 'harness': read(run / 'plan.json')['harness'],
        'binding_adapter': True, 'phase': 'queued', 'started_unix': __import__('time').time(), 'pid': None})
    write(root / '.local/demo/current.json', {'job_id': job_id})
    return job_id


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('run'); a = p.parse_args()
    job_id = prepare(a.run)
    print(job_id, flush=True)
    from tools.demo_runner import work
    work(job_id)
