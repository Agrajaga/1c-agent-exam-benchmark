"""Penalty signs of business processes and recalculations in the exported metadata (no 1C run).

Business processes (М8): the route, the route map in the process form, the list of the current user's open tasks, the
full task list, and the addressing set-up of the task. Whether personal or role addressing is needed (М8.4, М8.5) and
whether the addressing register data is right (М8.8) depend on the route and the staff of the ticket, given as a picture
and a table; they are not judged here. Recalculations (М7.10, М7.12): leading calculation types of a register that has
a recalculation, and the dimensions of the recalculation object.

signs(src) -> {penalty: (status, reason)} with status violation, no_violation_found or not_assessed. Whether a rule
applies to the ticket at all is decided by the caller (the catalogue applicability).
"""
import re
from pathlib import Path


def read(path):
    return Path(path).read_text(encoding='utf-8-sig', errors='replace') if Path(path).is_file() else ''


def prop(text, name):
    m = re.search(r'<' + name + r'>([^<]*)</' + name + '>', text)
    return m.group(1) if m else None


def business_processes(src):
    src = Path(src)
    out = {}
    tasks = sorted(src.glob('Tasks/*.xml'))
    processes = sorted(src.glob('BusinessProcesses/*.xml'))
    code = {f.relative_to(src).as_posix(): read(f) for f in src.rglob('*.bsl') if 'BenchmarkObserver' not in f.parts}

    # М8.1: the process part exists: a task, and every business process has a route from start through an action to the end.
    broken = []
    for bp in processes:
        flow = read(bp.parent / bp.stem / 'Ext' / 'Flowchart.xml')
        kinds = set(re.findall(r'<(Start|Activity|Completion)\s+id=', flow))
        if kinds != {'Start', 'Activity', 'Completion'}:
            broken.append('%s: в маршруте нет %s' % (bp.stem, ', '.join(sorted({'Start', 'Activity', 'Completion'} - kinds))))
    if not tasks and not processes:
        out['F1C-BP01'] = ('violation', 'в решении нет ни задач, ни бизнес-процессов')
    elif broken:
        out['F1C-BP01'] = ('violation', '; '.join(broken))
    else:
        out['F1C-BP01'] = ('no_violation_found', 'задачи есть; маршрут каждого бизнес-процесса ведёт от старта через действие к завершению')

    # М8.2: the process form shows the route map with the current state (a GraphicalSchema filled by ПолучитьКартуМаршрута()).
    missing = []
    for bp in processes:
        form_ref = prop(read(bp), 'DefaultObjectForm') or ''
        form = form_ref.rsplit('.', 1)[-1]
        form_xml = read(bp.parent / bp.stem / 'Forms' / form / 'Ext' / 'Form.xml') if form else ''
        module = read(bp.parent / bp.stem / 'Forms' / form / 'Ext' / 'Form' / 'Module.bsl') if form else ''
        if not ('GraphicalSchema' in form_xml and 'ПолучитьКартуМаршрута' in module):
            missing.append(bp.stem)
    if missing:
        out['F1C-BP02'] = ('violation', 'в форме бизнес-процесса нет карты маршрута с текущим состоянием: ' + ', '.join(missing))
    elif processes:
        out['F1C-BP02'] = ('no_violation_found', 'форма бизнес-процесса показывает карту маршрута')
    else:
        out['F1C-BP02'] = ('not_assessed', 'бизнес-процессов нет')

    # М8.3: a list of the current user's open tasks: the platform's ЗадачиПоИсполнителю with a filter on not done.
    by_executive = []
    for form in src.glob('Tasks/*/Forms/*/Ext/Form.xml'):
        text = read(form)
        main = prop(text, 'MainTable') or ''
        query = prop(text, 'QueryText') or ''
        own = main.endswith('.TasksByExecutive') or 'ЗадачиПоИсполнителю' in query
        open_only = re.search(r'<dcsset:left xsi:type="dcscor:Field">Выполнена</dcsset:left>\s*<dcsset:comparisonType>Equal</dcsset:comparisonType>\s*<dcsset:right xsi:type="xs:boolean">false', text) \
            or re.search(r'НЕ\s+\w*\.?Выполнена|Выполнена\s*=\s*ЛОЖЬ', query, re.I)
        if own and open_only:
            by_executive.append(form.parent.parent.name)
    if not tasks:
        out['F1C-BP03'] = ('not_assessed', 'задач нет')
    elif by_executive:
        out['F1C-BP03'] = ('no_violation_found', 'список невыполненных задач текущего пользователя: ' + ', '.join(sorted(by_executive)))
    else:
        out['F1C-BP03'] = ('violation', 'нет списка задач на ЗадачиПоИсполнителю с отбором невыполненных')

    # М8.6, М8.7: addressing attributes and the addressing register.
    excess, unlinked = [], []
    for task in tasks:
        text = read(task)
        main = (prop(text, 'MainAddressingAttribute') or '').rsplit('.', 1)[-1]
        attrs = re.findall(r'<AddressingAttribute uuid="[^"]*">.*?<Name>(\w+)</Name>.*?<AddressingDimension>([^<]*)</AddressingDimension>', text, re.S)
        register = (prop(text, 'Addressing') or '').split('.', 1)[-1]
        dims = re.findall(r'<Dimension uuid="[^"]*">\s*<Properties>\s*<Name>(\w+)</Name>', read(src / 'InformationRegisters' / (register + '.xml'))) if register else []
        flows = ' '.join(read(f) for f in src.glob('BusinessProcesses/*/Ext/Flowchart.xml'))
        set_in_route = {a for a, value in re.findall(r'<AddressingAttribute ref="[^"]*\.AddressingAttribute\.(\w+)">\s*<Value([^>]*)>', flows) if 'nil="true"' not in value}
        for name, dimension in attrs:
            if not dimension.strip():
                unlinked.append('%s.%s' % (task.stem, name))
            elif name != main and name not in set_in_route and not any(re.search(r'\.\s*' + name + r'\s*=', c) for c in code.values()):
                excess.append('признак %s.%s нигде не заполняется' % (task.stem, name))
        linked = {d.rsplit('.', 1)[-1] for _, d in attrs if d.strip()}
        excess += ['измерение %s.%s не связано с признаком адресации' % (register, d) for d in dims if d not in linked]
    if not tasks:
        out['F1C-BP06'] = out['F1C-BP07'] = ('not_assessed', 'задач нет')
    else:
        out['F1C-BP06'] = ('violation', '; '.join(excess)) if excess else ('no_violation_found', 'каждый признак адресации заполняется маршрутом или кодом, каждое измерение регистра адресации связано с признаком')
        out['F1C-BP07'] = ('violation', 'признаки адресации без связи с измерением регистра адресации: ' + ', '.join(unlinked)) if unlinked \
            else ('no_violation_found', 'признаки адресации связаны с измерениями регистра адресации')

    # М8.9: the full task list is reachable: the task is in a subsystem (its standard list command is in the interface).
    content = ' '.join(read(s) for s in src.rglob('Subsystems/*.xml'))
    hidden = [t.stem for t in tasks if 'Task.' + t.stem + '<' not in content]
    if not tasks:
        out['F1C-BP09'] = ('not_assessed', 'задач нет')
    else:
        out['F1C-BP09'] = ('violation', 'задачи не входят ни в одну подсистему — полного списка в интерфейсе нет: ' + ', '.join(hidden)) if hidden \
            else ('no_violation_found', 'задачи входят в подсистему: полный список доступен')
    return out


def kinds_in(item, tag):
    """Calculation type names listed under <tag> of a predefined calculation type."""
    block = re.search(r'<' + tag + r'>(.*?)</' + tag + '>', item, re.S)
    return set(re.findall(r'\.(\w+)</CalculationType>', block.group(1))) if block else set()


def recalculations(src):
    src = Path(src)
    out = {}
    registers = [r for r in sorted(src.glob('CalculationRegisters/*.xml')) if list((r.parent / r.stem / 'Recalculations').glob('*.xml'))]
    if not registers:
        reason = 'перерасчётов в решении нет'
        return {'F1C-PR10': ('not_assessed', reason), 'F1C-PR12': ('not_assessed', reason)}
    # М7.12: every recalculation dimension is linked to a dimension of its register.
    wrong = []
    for register in registers:
        for recalc in sorted((register.parent / register.stem / 'Recalculations').glob('*.xml')):
            text = read(recalc)
            dims = re.findall(r'<Dimension uuid="[^"]*">(.*?)</Dimension>', text, re.S)
            if not dims:
                wrong.append('%s.%s: нет измерений' % (register.stem, recalc.stem))
            wrong += ['%s.%s: измерение %s не связано с измерением регистра' % (register.stem, recalc.stem, prop(d, 'Name'))
                      for d in dims if not (prop(d, 'RegisterDimension') or '').strip()]
    out['F1C-PR12'] = ('violation', '; '.join(wrong)) if wrong else ('no_violation_found', 'измерения перерасчётов связаны с измерениями регистров')
    # М7.10: a kind computed from a base is recalculated when the base changes only if a base kind is among its leading kinds.
    missing = []
    for register in registers:
        chart = (prop(read(register), 'ChartOfCalculationTypes') or '').split('.', 1)[-1]
        predefined = read(src / 'ChartsOfCalculationTypes' / chart / 'Ext' / 'Predefined.xml')
        for item in predefined.split('<Item id=')[1:]:
            name = prop(item, 'Name')
            base, leading = kinds_in(item, 'Base'), kinds_in(item, 'Leading')
            if base and not base & leading:
                missing.append('%s.%s: база %s, ведущих среди них нет' % (chart, name, ', '.join(sorted(base))))
    out['F1C-PR10'] = ('violation', '; '.join(missing)) if missing else ('no_violation_found', 'у видов расчёта с базой базовые виды указаны ведущими')
    return out
