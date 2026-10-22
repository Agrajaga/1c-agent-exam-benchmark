"""Separate acceptance for indexed subconto bindings, proved from the goods account metadata.

The original invalid submission and every source byte remain unchanged. No grader change.
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
        changes.append({'field': 'fields.ledger.' + role, 'before': value, 'after': replacement})
        clean['fields']['ledger'][role] = replacement
    if not changes:
        raise ValueError('No indexed subconto bindings to normalize')
    clean, _ = canonical_ledger(src, clean)
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
    write(job / 'binding-adapter-proof.json', {'scope': 'supplemental_indexed_subconto_adapter',
        'original_binding_sha256': digest(run / 'artifacts/binding.json'), 'normalized_binding_sha256': digest(job / 'binding-adapter.json'),
        'normalizer_sha256': digest(__file__), 'changes': changes,
        'basis': 'Ordered predefined subconto kinds of the declared goods account; all role types checked by the unchanged adapter.'})
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
