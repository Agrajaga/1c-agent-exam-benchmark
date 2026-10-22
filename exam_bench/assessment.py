"""Narrow, deterministic retrospective mechanism assessment; not a full BSL analyzer.

Recognizes only the two frozen payroll implementations and simple local query
wrappers. Unsupported layouts fail closed. No model is invoked to assign points.
"""
import re
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

PROFILE_ID = 'payroll-mechanisms-retrospective-v1'
MD = '{http://v8.1c.ru/8.3/MDClasses}'
TOKEN = re.compile(r'//[^\n]*|"(?:""|[^"])*"|[\wА-Яа-яЁё]+|\s+|.', re.S)


def lex(text):
    """Keep positions; omit comments and whitespace; strings remain atomic."""
    return [(m.group(), m.start()) for m in TOKEN.finditer(text)
            if not m.group().isspace() and not m.group().startswith('//')]


def routines(text):
    tokens = lex(text)
    result = {}
    start = None
    for i, (value, pos) in enumerate(tokens):
        if value.lower() in ('функция', 'процедура'):
            if start is not None:
                raise ValueError('Nested routine unsupported')
            start = (tokens[i + 1][0].lower(), i, pos)
        elif value.lower() in ('конецфункции', 'конецпроцедуры'):
            if start is None:
                raise ValueError('Unmatched routine end')
            name, begin, offset = start
            result[name] = (tokens[begin:i + 1], offset, pos + len(value))
            start = None
    if start is not None:
        raise ValueError('Unclosed routine')
    return result


def compact(tokens):
    return ''.join(v.lower() for v, _ in tokens)


def payroll_findings(source, variant):
    """Explicit posting entry -> payroll routine -> verified uncached DB wrapper.

    PR06 requires a literal FROM the schedule's real table assigned to a local
    table, a loop consuming that table and its schedule resource. GEN20 requires
    a call to a verified query wrapper inside a lexical loop of that same
    payroll routine. One finding per mechanism, never one per loop iteration.
    Neither detects all other forms of these violations nor proves runtime sums.
    """
    source = Path(source)
    spec = {'none': ('УчетЗарплаты', 'Рассчитать', 'Таблица', 'Календарь', 'Часы'),
            'unica013': ('РасчетЗарплаты', 'Пересчитать', 'ЗапросТаблица', 'Графики', 'Значение')}[variant]
    module, method, wrapper, variable, resource = spec
    relative = f'CommonModules/{module}/Ext/Module.bsl'
    text = (source / relative).read_text(encoding='utf-8-sig')
    entry = routines((source/'Documents/НачислениеЗарплаты/Ext/ObjectModule.bsl').read_text(encoding='utf-8-sig'))
    if f'{module}.{method}('.lower() not in compact(entry['обработкапроведения'][0]):
        raise ValueError('Payroll posting route unsupported')
    helper = routines((source/'CommonModules/Учет/Ext/Module.bsl').read_text(encoding='utf-8-sig'))
    implementation = compact(helper[wrapper.lower()][0])
    if 'новыйзапрос(текст)' not in implementation or 'запрос.выполнить().выгрузить()' not in implementation:
        raise ValueError('Query wrapper semantics unsupported')
    properties = ET.parse(source/'CommonModules/Учет.xml').find('.//'+MD+'Properties')
    if properties.findtext(MD+'ReturnValuesReuse') != 'DontUse':
        raise ValueError('Cached wrapper requires separate assessment')
    tokens, _, _ = routines(text)[method.lower()]
    metadata = ET.parse(source/'CalculationRegisters/Начисления.xml')
    schedule = metadata.findtext('.//'+MD+'Schedule')
    schedule_value = metadata.findtext('.//'+MD+'ScheduleValue')
    if not schedule or not schedule.startswith('InformationRegister.'):
        raise ValueError('Schedule mapping unsupported')
    schedule_name = schedule.split('.')[1]
    if schedule_value != f'{schedule}.Resource.{resource}':
        raise ValueError('Schedule resource mapping unsupported')
    query_positions = []
    graph_positions = []
    depth = 0
    for i, (value, pos) in enumerate(tokens):
        low = value.lower()
        if low == 'цикл':
            depth += 1
        elif low == 'конеццикла':
            depth -= 1
            if depth < 0:
                raise ValueError('Invalid loop nesting')
        # Exact helper name; strings/comments cannot introduce a call.
        call = compact(tokens[i:i+4])
        if call == f'учет.{wrapper}('.lower():
            if depth:
                query_positions.append(pos)
            if i >= 2 and compact(tokens[i-2:i]) == (variable+'=').lower():
                query = tokens[i+4][0]
                if query.startswith('"') and re.search(r'\bИЗ\s+РегистрСведений\.' + re.escape(schedule_name) + r'(?=\s|"|$)', query, re.I):
                    graph_positions.append(pos)
    if depth:
        raise ValueError('Unclosed loop')
    body = compact(tokens)
    loop = re.search(r'длякаждого(\w+)из'+variable.lower()+r'цикл', body)
    if graph_positions and (not loop or loop[1]+'.'+resource.lower() not in body):
        raise ValueError('Graph data consumption unsupported')
    def finding(penalty, defect, positions):
        return {'penalty_id': penalty, 'defect_id': defect, 'evidence':
                [{'file': relative, 'line': text.count('\n', 0, p)+1} for p in positions],
                'proof_kind': 'scoped_static_mechanism', 'runtime_behavior_proved': False}
    findings = []
    if graph_positions:
        findings.append(finding('F1C-PR06', 'payroll.schedule_from_real_information_table', graph_positions))
    if query_positions:
        findings.append(finding('F1C-GEN20', 'payroll.database_reads_inside_record_loop', query_positions))
    return findings


def grade_for(score, policy):
    """Exam grade for a known score, by the owner policy intervals (half-open, as in the 1C document)."""
    score = Decimal(str(score))
    for interval in policy['grade_intervals']:
        lower, upper = interval['lower'], interval['upper']
        above = lower is None or (score >= Decimal(lower) if interval['lower_inclusive'] else score > Decimal(lower))
        below = upper is None or (score <= Decimal(upper) if interval['upper_inclusive'] else score < Decimal(upper))
        if above and below:
            return interval['grade']
    return None


def score_bound(findings, catalogue, policy, whole_catalogue_checked=False):
    """Score after the penalties proved so far.

    Owner policy v4: a ranged penalty is charged at its minimum (A01), and one defect yields one penalty —
    the applicable item with the smallest minimum (A02). The score is 5 minus the charges; it is final only
    when the whole catalogue was checked, otherwise it is an upper bound (unchecked rules may add penalties).
    """
    if policy['range_selection'] != 'minimum' or policy['overlap']['different_penalty_ids_for_same_defect'] != 'smallest_applicable':
        raise ValueError('Scoring implementation does not match the owner policy')
    entries = {item['id']: item for item in catalogue['items']}
    waived = set(policy['additional_document_types']['waived_penalty_ids'])
    by_defect = {}
    for item in findings:
        official = entries[item['penalty_id']]
        if item['penalty_id'] in waived:
            continue
        if official['applicability'] not in ('applicable', 'conditional'):
            raise ValueError('Inapplicable penalty')
        by_defect.setdefault(item['defect_id'], {})[item['penalty_id']] = item
    charges = []
    for defect, candidates in by_defect.items():
        best = min(candidates, key=lambda pid: (Decimal(entries[pid]['deduction']['minimum']), pid))
        deduction = entries[best]['deduction']
        charges.append({**candidates[best], 'points': deduction['minimum'], 'range': [deduction['minimum'], deduction['maximum']],
                        'source': entries[best]['source'], 'also_applicable': sorted(set(candidates) - {best})})
    total = sum((Decimal(c['points']) for c in charges), Decimal(0))
    initial = Decimal(policy['initial_points'])
    upper = initial - total
    # Bonuses: never awarded (A12).
    if policy['bonus_policy'] != 'not_awarded':
        raise ValueError('New bonus policy requires bound review')
    proven_fail = upper < Decimal('2.2')
    grade = 'unsatisfactory' if proven_fail else (grade_for(upper, policy) if whole_catalogue_checked else None)
    return {'charges': charges, 'deductions': str(total),
            'score_upper_bound': str(upper), 'score': str(upper) if whole_catalogue_checked else None,
            'grade': grade, 'grade_proof': 'upper_bound_below_pass_threshold' if proven_fail else 'whole_catalogue_checked' if grade else 'insufficient_coverage',
            # Only an upper bound below the pass threshold proves failure; otherwise the outcome is open.
            'attestation': 'not_passed_by_confirmed_penalties' if proven_fail else 'undetermined',
            'clamping_applied': False, 'bonuses_awarded': '0',
            'whole_catalogue_checked': whole_catalogue_checked}


def tariff_runtime_findings(observation, calibration, relative_file):
    """One calibrated candidate-code fault, with its functional consequence.

    Other observer errors are inconclusive. Control must have identical inputs,
    independently expected tariff rows and the one-variable rename as sole edit.
    """
    if not calibration.get('same_fixture') or not calibration.get('sole_variable_rename') or not calibration.get('positive_equal'):
        return []
    error = observation.get('error', '')
    match = re.search(r'\{ОбщийМодуль\.УчетЗарплаты\.Модуль\((\d+)\)\}: Поле объекта недоступно для записи \(Документы\)', error)
    if observation.get('rows') is not None or not match:
        return []
    return [{'penalty_id': penalty, 'defect_id': 'payroll.assignment_to_readonly_documents_manager',
             'evidence': [{'file': relative_file, 'line': int(match[1])}],
             'proof_kind': 'real_platform_error_with_one_edit_positive_control',
             'runtime_behavior_proved': True}
            for penalty in ('F1C-GEN12', 'F1C-GEN01')]
