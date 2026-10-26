"""Read period metadata for OU03/OU08 as preliminary evidence, without grading the solution.

Periodicity alone cannot prove that the business rule is enforced: code can replace
an existing period or use a separate validation mechanism. Runtime scenarios are
required before this evidence can affect a score.
"""
import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path


def inspect(source, binding):
    source = Path(source).resolve()
    objects = (binding.get('ou') or {}).get('objects') or {}
    result = []
    for rule, role in [('OU03', 'policies'), ('OU08', 'specification')]:
        ref = objects.get(role, '')
        parts = ref.split('.')
        if len(parts) != 2 or parts[0] != 'InformationRegister' or not parts[1] or any(x in parts[1] for x in ('/', '\\', ':')):
            result.append({'rule': rule, 'status': 'not_observed', 'reason': 'Регистр не объявлен или привязка недопустима'})
            continue
        path = source / 'InformationRegisters' / (parts[1] + '.xml')
        try:
            tree = ET.parse(path)
            registers = [e for e in tree.getroot().iter() if e.tag.rsplit('}', 1)[-1] == 'InformationRegister']
            props = next(e for e in registers[0] if e.tag.rsplit('}', 1)[-1] == 'Properties')
            period = next(e.text for e in props if e.tag.rsplit('}', 1)[-1] == 'InformationRegisterPeriodicity')
        except (OSError, ET.ParseError, IndexError, StopIteration):
            result.append({'rule': rule, 'status': 'not_observed', 'reason': 'Периодичность регистра не найдена'})
            continue
        result.append({'rule': rule, 'status': 'evidence_only', 'register': ref,
                       'periodicity': period, 'source': path.relative_to(source).as_posix(),
                       'reason': 'Периодичность не доказывает ограничение частоты изменений; требуется проверка при записи'})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--binding', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.source, json.loads(args.binding.read_text(encoding='utf-8-sig'))), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
