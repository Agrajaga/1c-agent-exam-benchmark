"""Calibrate OU03/OU08 metadata and history checks on actual 1C control configurations."""
from pathlib import Path

from .calibration import generate
from .common import tree_manifest, write_json
from .grader import grade
from .ou import static_signs


def run(starter_source, starter_dt, binary, root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    controls = []
    for label, policy, spec, expected in [
        ('year_day', 'Year', 'Day', ('pass', 'pass')),
        ('day_day', 'Day', 'Day', ('inconclusive', 'pass')),
        ('year_second', 'Year', 'Second', ('pass', 'inconclusive')),
    ]:
        folder = root / label
        folder.mkdir()
        src = folder / 'src'
        binding = generate(starter_source, src, 'one')
        for name, old, value in [('BenchPolicies', 'Year', policy), ('BenchSpecs', 'Day', spec)]:
            path = src / 'InformationRegisters' / (name + '.xml')
            text = path.read_text(encoding='utf-8-sig')
            marker = '<InformationRegisterPeriodicity>' + old + '</InformationRegisterPeriodicity>'
            if text.count(marker) != 1:
                raise ValueError('Control fixture periodicity is missing or ambiguous: ' + name)
            path.write_text(text.replace(marker, '<InformationRegisterPeriodicity>' + value + '</InformationRegisterPeriodicity>'), encoding='utf-8')
        before = tree_manifest(src)
        actual_periods = static_signs(src, binding)['periodicity']
        evaluation = grade(src, binding, starter_dt, binary, folder / 'grade', ['ou_history'])
        verdicts = {r['id']: r['verdict'] for r in evaluation['rules'] if r['id'] in ('OU03', 'OU08')}
        passed = (not evaluation['errors'] and tree_manifest(src) == before
                  and actual_periods == {'policies': policy, 'specification': spec}
                  and (verdicts.get('OU03'), verdicts.get('OU08')) == expected)
        controls.append({'case': label, 'periodicity': actual_periods, 'expected': dict(zip(('OU03', 'OU08'), expected)),
                         'verdicts': verdicts, 'errors': evaluation['errors'], 'passed': passed})
    summary = {'passed': all(x['passed'] for x in controls), 'controls': controls,
               'limitations': ['Дневная периодичность не подтверждает запрет второй версии за календарную неделю',
                               'Иная периодичность сама по себе не доказывает дефект решения']}
    write_json(root / 'summary.json', summary)
    return summary
