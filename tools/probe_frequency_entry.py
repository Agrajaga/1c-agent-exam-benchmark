"""Observe declared service entry candidates in an isolated 1C copy, without grading.

The exported method may be unused or may have UI-specific validation outside it.
This tool records observations and never treats those observations as an exam verdict.
"""
import argparse
import json
from pathlib import Path

from exam_bench import calibration_frequency_entries as template
from exam_bench.common import tree_manifest, write_json
from exam_bench.observer import inject
from exam_bench.ou import IDENT, manager, literal
from exam_bench.platform import OneC, PlatformError
from tools.frequency_entry_contract import validate_frequency_entries
from exam_bench.workspaces import case_workspace


def observer(binding):
    ou = binding['ou']; obj = ou['objects']; fields = ou['fields']
    entries = ou['frequency_entry']
    spec = fields['specification']; policy = fields['policies']
    refs = (obj['departments'], binding['objects']['items'], obj['properties'], obj['policies'], obj['specification'])
    names = [ref.split('.', 1)[1] for ref in refs]
    simple = [fields['properties']['owner'], spec['block'], spec['item'], spec['property'], spec['quantity'], policy['department'], policy['method']]
    if not all(IDENT.fullmatch(x) for x in names + simple): raise ValueError('A required reference is not a simple identifier')
    for role in ('fifo', 'lifo'):
        value = fields['policy_values'][role]
        parts = value.split('.') if isinstance(value, str) else []
        if len(parts) != 3 or parts[0] != 'Enum' or not all(IDENT.fullmatch(p) for p in parts[1:]):
            raise ValueError('A policy value is not an enumeration reference')
    code = template.observer()
    replacements = {
        'Справочники.Подразделения': manager(obj['departments']),
        'Справочники.Номенклатура': manager(binding['objects']['items']),
        'Справочники.BenchProperties': manager(obj['properties']),
        'РегистрыСведений.BenchPolicies': manager(obj['policies']),
        'РегистрыСведений.BenchSpecs': manager(obj['specification']),
        'РегистрСведений.BenchPolicies': 'РегистрСведений.' + names[3],
        'РегистрСведений.BenchSpecs': 'РегистрСведений.' + names[4],
        'Х.Item =': 'Х.' + fields['properties']['owner'] + ' =',
        'С.Method': 'С.' + policy['method'], 'С.Department': 'С.' + policy['department'],
        'С.Block': 'С.' + spec['block'], 'С.Item': 'С.' + spec['item'], 'С.Qty': 'С.' + spec['quantity'],
        'BenchFrequencyInput.Policy': '.'.join(entries['policy'].split('.')[1:]),
        'BenchFrequencyInput.Specification': '.'.join(entries['specification'].split('.')[1:]),
        'Перечисления.УчетнаяПолитика.ФИФО': literal(fields['policy_values']['fifo']),
        'Перечисления.УчетнаяПолитика.ЛИФО': literal(fields['policy_values']['lifo']),
    }
    for old, new in replacements.items(): code = code.replace(old, new)
    return code


def run(source, binding, starter, binary, root):
    from exam_bench.runtime import platform_binary, require_execution_mode
    require_execution_mode()
    if str(Path(binary).resolve()) != platform_binary(): raise ValueError('Platform binary differs from machine settings')
    source = Path(source).resolve(); root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    def unassessed(reason, errors=None):
        result = {'grading_status': 'not_assessed', 'reason': reason, 'errors': errors or {}}
        write_json(root / 'service-observation.json', result)
        return result
    if not isinstance(binding, dict):
        return unassessed('binding должен быть объектом')
    valid, errors = validate_frequency_entries(source, binding.get('ou'))
    if errors or set(valid) != {'policy', 'specification'}:
        return unassessed('Для этого диагностического сценария нужны обе действительные процедуры', errors)
    try:
        code = observer(binding)
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as e:
        return unassessed('Неполная или неподдерживаемая привязка объектов и полей', {'binding': str(e)[:300]})
    before = tree_manifest(source)
    try:
        with case_workspace(root) as work:
            platform = OneC(binary, work / 'platform', 180)
            observed = inject(source, work / 'observed-src', code)
            platform.restore(work / 'ib', starter); platform.load(work / 'ib', observed)
            output = work / 'observations.json'
            platform.command(['ENTERPRISE', '/F', work / 'ib', '/C', output], 'observe', confined=work)
            data = json.loads(output.read_text(encoding='utf-8-sig'))
    except (PlatformError, OSError, ValueError) as e:
        return unassessed('Ошибка среды или наблюдателя; сценарий не оценён', {'observation': str(e)[:300]})
    if tree_manifest(source) != before: raise ValueError('Source changed during observation')
    if not isinstance(data, dict) or 'error' in data:
        return unassessed('Не удалось выполнить наблюдение; сценарий не оценён', {'observation': str(data)[:300]})
    result = {'grading_status': 'not_assessed', 'reason': 'Declared service alone does not prove use by the user interface',
              'entry_contract': valid, 'observation': data}
    write_json(root / 'service-observation.json', result)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True); p.add_argument('--binding', required=True)
    p.add_argument('--starter', required=True); p.add_argument('--binary', required=True); p.add_argument('--output', required=True)
    a = p.parse_args()
    print(json.dumps(run(a.source, json.loads(Path(a.binding).read_text(encoding='utf-8-sig')), a.starter, a.binary, a.output), ensure_ascii=False))
