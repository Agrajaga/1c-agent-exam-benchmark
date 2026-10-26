"""Report catalogue disagreements and native calibration evidence without changing scores."""
import argparse
import json
from pathlib import Path

from exam_bench.common import grading_fingerprint

ROOT = Path(__file__).resolve().parents[1]
BOOK = ROOT / 'rules/1c-specialist-platform/rules.json'
TICKET = ROOT / 'tasks/1c-platform-official-sample/checks.json'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def audit(book, ticket, calibration=None, current=None):
    """The ticket describes a target; readiness describes the currently implemented subset."""
    rules = {r['id']: r for r in book['rules']}
    discrepancies = []
    for item in ticket['official_rules']:
        rule = rules[item['rule_id']]
        check = rule['stand_check']
        if item['coverage'] == 'not_implemented' and check['readiness'] in ('ready', 'partial'):
            discrepancies.append({'id': item['rule_id'], 'applicability': item['applicability'],
                                  'target_coverage': item['coverage'], 'current_readiness': check['readiness'],
                                  'implemented_description': check['how'], 'target_description': item['ticket_check']})
    requirements = [dict(id=r['id'], title=r['title'], reason=r['stand']['how'])
                    for r in ticket['requirements'] if r['stand']['status'] != 'checked']
    native = None
    if calibration is not None:
        files = calibration.get('implementation_files')
        native = {'accepted': calibration.get('accepted') is True,
                  'mode': calibration.get('mode', 'full'),
                  'current_grader': isinstance(files, dict) and files == current,
                  'query_parameter_passed': calibration.get('query_parameter_calibration', {}).get('passed') is True,
                  'positive_cases': len(calibration.get('positives', [])),
                  'negative_cases': len(calibration.get('negatives', []))}
    return {'schema_version': 1, 'discrepancies': discrepancies, 'partial_requirements': requirements,
            'native_calibration': native}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calibration', type=Path, help='local calibration summary.json, optional')
    parser.add_argument('--output', type=Path, help='write JSON here; otherwise print to stdout')
    args = parser.parse_args()
    result = audit(read(BOOK), read(TICKET), read(args.calibration) if args.calibration else None, grading_fingerprint())
    text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    else:
        print(text, end='')


if __name__ == '__main__':
    main()
