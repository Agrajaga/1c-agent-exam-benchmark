"""Validate the curator crosswalk; does not grade any candidate solution."""
import hashlib
import json
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / 'tasks/1c-platform-official-sample'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(value, message):
    if not value:
        raise ValueError(message)


import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exam_bench.grader import PROFILE as GRADER_PROFILE


def main():
    m = json.loads((TASK / 'private/official-assessment-mapping.json').read_text())
    policy_path = TASK / m['owner_policy']['path']
    policy = json.loads(policy_path.read_text())
    check(sha(policy_path) == m['owner_policy']['sha256'], 'Owner policy drift')
    check(policy['policy_id'] == m['owner_policy']['id'], 'Wrong policy version')
    check(policy['range_selection'] == 'minimum', 'Owner minimum-penalty policy (A01, v4) not applied')
    check(not policy['is_official_1c_policy'] and not m['owner_policy']['integrated_into_grader'], 'False official/integrated policy claim')
    check(policy['overlap']['different_penalty_ids_for_same_defect'] == 'smallest_applicable', 'One defect must yield one penalty (A02, v4)')
    check(policy['overlap']['counting_unit'] == 'defect_id', 'Unexpected counting unit')
    check(policy['overlap']['repeated_observations_of_same_pair'] == 'one_penalty_instance', 'Test repetition multiplies penalties')
    intervals = policy['grade_intervals']
    check(m['scoring']['grade_intervals'] == intervals, 'Threshold policy drift')
    def classify(value):
        value = Decimal(value)
        matches = []
        for interval in intervals:
            low, high = interval['lower'], interval['upper']
            lower_ok = low is None or (value >= Decimal(low) if interval['lower_inclusive'] else value > Decimal(low))
            upper_ok = high is None or (value <= Decimal(high) if interval['upper_inclusive'] else value < Decimal(high))
            if lower_ok and upper_ok:
                matches.append(interval['grade'])
        check(len(matches) <= 1, 'Overlapping grade intervals')
        return matches[0] if matches else 'out_of_policy'
    examples = {'-1': 'unsatisfactory', '0': 'unsatisfactory', '2.19999': 'unsatisfactory',
                '2.2': 'satisfactory', '3.49999': 'satisfactory', '3.5': 'good',
                '4.49999': 'good', '4.5': 'excellent', '5': 'excellent', '5.00001': 'out_of_policy'}  # half-open, as in the document (A03, v3)
    for value, expected_grade in examples.items():
        check(classify(value) == expected_grade, f'Wrong grade at {value}')
    check(policy['shared_invoice_types']['duplicate_types_between_sections'] == 'forbidden', 'Invoice duplication allowed')
    check(policy['additional_document_types']['allowed'] is True, 'Additional documents forbidden')
    check(policy['required_section_acceptance']['unsupported_binding_without_observation_route']['benchmark_attestation'] == 'not_attested', 'Unverifiable section accepted')
    check(policy['required_section_acceptance']['unsupported_binding_without_observation_route']['official_absence_gate_established'] is False, 'Compatibility confused with absence')
    check(policy['required_section_acceptance']['alternative_validated_observation_route'] == 'use_route_and_grade_real_observations', 'Alternative observation route ignored')
    check(set(policy['recalculation']['modes']) == {'required', 'prohibited', 'not_specified'}, 'Missing ticket mode')
    check(policy['recalculation']['current_task_mode'] == 'prohibited', 'Wrong recalculation mode for selected task')
    execution_policy = json.loads((ROOT / 'profiles/ai-exam-execution-policy.json').read_text())
    check(policy['execution_budget']['series'] == {k: v['solve_timeout_seconds'] for k, v in execution_policy['series'].items()} == {'exam': 18000, 'fast': 1800}, 'Wrong AI time series (A09, v3)')
    check(execution_policy['maximum_ai_solve_timeout_seconds'] == 18000, 'Wrong upper time limit')
    check(execution_policy['human_exam_minutes'] == 300, 'Human exam limit changed')
    source = ROOT / 'sources/1c/ATT83PL.txt'
    lines = source.read_text().splitlines()
    check(sha(source) == m['source']['text_sha256'], 'Source text changed')
    check(sha(ROOT / 'sources/1c/ATT83PL.rtf') == m['source']['artifact_sha256'], 'RTF changed')
    provenance = json.loads((TASK / 'private/source-map.json').read_text())
    check(m['source']['artifact_sha256'] == provenance['source_sha256'], 'Wrong official artifact')
    check(m['source']['text_sha256'] == provenance['source_text_sha256'], 'Wrong source locator')
    check(sha(TASK / 'private/rules.json') == m['pinned_inputs']['rules_sha256'], 'Rule specification drift')
    # The pin belongs to the historical pilot, not today's executable grader.
    check(sha(TASK / m['pinned_inputs']['grader_path']) == m['pinned_inputs']['grader_sha256'], 'Historical pilot grader drift')
    groups = {'GEN': 'любой учетной', 'OU': 'оперативному', 'BU': 'бухгалтерскому',
              'PR': 'периодическим', 'BP': 'бизнес-процессам', 'UI': 'управляемым'}
    counts = Counter()
    expected = {}
    group = None
    first = None
    for number, text in enumerate(lines, 1):
        if 'Список наиболее часто встречающихся ошибок' in text:
            group = next(k for k, v in groups.items() if v in text)
            first = None
            continue
        if number >= 269:
            break
        if not group or not text.strip() or text.strip() in ('Описание ошибки', 'Балл'):
            continue
        if re.fullmatch(r'\d+[,.]\d+(?:\s*[-–]\s*\d+[,.]\d+)?', text.strip()):
            counts[group] += 1
            key = f'F1C-{group}{counts[group]:02}'
            values = [Decimal(t.strip().replace(',', '.')) for t in re.split('[-–]', text)]
            expected[key] = (first, number, values[0], values[-1])
            first = None
        elif first is None:
            first = number
    check(dict(counts) == {'GEN': 33, 'OU': 4, 'BU': 11, 'PR': 17, 'BP': 9, 'UI': 1}, 'Source catalog changed')
    items = m['items']
    check(len(items) == len(expected) == 75, 'Incomplete penalty catalog')
    check(len({x['id'] for x in items}) == 75, 'Duplicate penalty ID')
    check({x['id'] for x in items} == set(expected), 'Unexpected or missing source ID')
    rules = json.loads((TASK / 'private/rules.json').read_text())['rules']
    rule_ids = {r['id'] for r in rules}
    for item in items:
        lo, hi, lower, upper = expected[item['id']]
        check(item['source']['lines'] == [lo, hi], f"{item['id']}: wrong source span")
        check(Decimal(item['deduction']['minimum']) == lower and Decimal(item['deduction']['maximum']) == upper,
              f"{item['id']}: wrong penalty range")
        check(lower <= upper, 'Invalid deduction interval')
        check(set(item['linked_rule_ids']) <= rule_ids, f"{item['id']}: nonexistent rule")
        check(set(item['current_coverage']['pilot_assertion_rule_ids']) <= set(GRADER_PROFILE['rules']), 'Unknown pilot assertion')
        check(item['applicability'] in {'applicable', 'conditional', 'unresolved', 'not_applicable'}, 'Unknown applicability')
        check(item['mapping_relation'] in m['definitions'], 'Unknown relation')
        check(not item['deduction']['automatic_eligible'], 'Uncalibrated penalty enabled')
        check(not item['current_coverage']['official_penalty_fully_verified'], 'False full-coverage claim')
        check(item['planned_check']['implementation'] == 'not_implemented' and item['planned_check']['execution'] == 'not_run', 'Planned check presented as executed')
    check(not m['ready'] and not m['scoring']['enabled'] and not m['ai_judge'], 'Unsafe profile status')
    check(not m['scoring']['historical_results_rewritten'], 'History rewrite claim')
    by_id = {item['id']: item for item in items}
    check(by_id['F1C-GEN33']['applicability'] == 'applicable' and by_id['F1C-GEN33']['owner_override'] is None, 'Official GEN33 penalty must apply (A07 withdrawn, v3)')
    check(policy['additional_document_types']['waived_penalty_ids'] == [], 'No official penalty may be waived')
    check(by_id['F1C-PR12']['applicability_by_ticket_mode']['required'] == 'applicable', 'Required recalculation configuration waived')
    check(by_id['F1C-PR12']['applicability_by_ticket_mode']['prohibited'] == 'not_applicable', 'Forbidden mechanism demanded')
    issues = {issue['id']: issue for issue in m['open_issues']}
    for issue_id in ('A01', 'A02', 'A03', 'A04', 'A05', 'A06', 'A07', 'A08', 'A09', 'A10', 'A11', 'A12', 'A13'):
        check(issues[issue_id]['state'] == 'resolved' and issues[issue_id]['resolution_authority'] == 'benchmark_owner', 'Owner decision left unresolved: ' + issue_id)
    check(all(by_id[f'F1C-BP0{i}']['applicability'] == 'not_applicable' for i in range(1, 10)), 'Business-process penalties applied to a ticket without that task (A05)')
    check(by_id['F1C-GEN26']['applicability'] == 'not_applicable', 'Interview penalty applied without an interview (A09)')
    check(by_id['F1C-GEN32']['applicability'] == 'applicable', 'Demo data penalty must apply (A10)')
    check(policy['bonus_policy'] == 'not_awarded' and policy['score_clamping'] == 'none', 'Bonus/limit policy (A12) changed')
    check(set(m['rule_index']) == rule_ids, 'Incomplete reverse index')
    for rule in rule_ids:
        expected_links = {relation: [i['id'] for i in items if rule in i['linked_rule_ids'] and i['mapping_relation'] == relation]
                          for relation in m['definitions']}
        check(m['rule_index'][rule] == expected_links, f'Inconsistent reverse links: {rule}')
    check(len({g['id'] for g in m['gates']}) == len(m['gates']), 'Duplicate gate')
    check(any(g['id'] == 'F1C-GATE-CORE' and g['source_lines'] == [23, 23] for g in m['gates']), 'Missing core-section barrier')
    for gate in m['gates']:
        check(set(gate['linked_rule_ids']) <= rule_ids, 'Unknown gate rule')
        check(1 <= gate['source_lines'][0] <= gate['source_lines'][1] <= len(lines), 'Invalid gate source')
    check(len({q['id'] for q in m['open_issues']}) == len(m['open_issues']), 'Duplicate scoring issue')
    for path in (TASK / 'official-assessment-mapping.md', TASK / 'owner-scoring-policy.md', ROOT / 'README.md'):
        for target in re.findall(r'(?<!!)\[[^\]]*\]\(([^)]+)\)', path.read_text()):
            if target.startswith(('https://', 'http://')):
                continue
            local = re.sub(r':\d+$', '', target.split('#', 1)[0])
            check((path.parent / local).exists(), f'Broken link: {target}')
    print(json.dumps({'status': 'passed', 'penalties': 75, 'categories': dict(counts),
                      'applicability': dict(Counter(i['applicability'] for i in items)),
                      'owner_grade_examples_verified': len(examples),
                      'owner_decisions_resolved': 7,
                      'remaining_open_issues': sum(i['state'] == 'open' for i in m['open_issues']),
                      'partially_resolved_issues': sum(i['state'] == 'partially_resolved' for i in m['open_issues']),
                      'automatic_penalties': 0, 'solution_tests_executed': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
