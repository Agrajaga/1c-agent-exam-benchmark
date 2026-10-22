"""Examiner's practices for periodic calculations that the official list of errors does not price.

Source: П. С. Белоусов, examiner and co-author of the exam task book, webinar of 1С:Учебный центр №1 «Подготовка к
1С: Специалисту по Платформе — тема "Расчеты"» (rules/1c-specialist-platform/examiner.json). They do not change the
score: they are reported next to the penalties so a solution can be compared with how the examiner solves the task.

signs(src) -> {id: (status, reason)} with status violation, no_violation_found or not_assessed.
"""
import re
from pathlib import Path

from .codescan import IDENT, lex


def read(path):
    return Path(path).read_text(encoding='utf-8-sig', errors='replace') if Path(path).is_file() else ''


def prop(text, name):
    m = re.search(r'<' + name + r'>([^<]*)</' + name + '>', text)
    return m.group(1) if m else None


def code_of(src):
    out = []
    for path in sorted(Path(src).rglob('*.bsl')):
        if 'BenchmarkObserver' in path.parts:
            continue
        code, strings = lex(read(path))
        out.append((path.relative_to(src).as_posix(), code, strings))
    return out


def schedule_queries(modules):
    """[(file, line, text, alias, params)]: query texts that read a ДанныеГрафика virtual table."""
    out = []
    for file, _, strings in modules:
        for text, line in strings:
            for m in re.finditer(r'РегистрРасчета\.(' + IDENT + r')\.ДанныеГрафика(\s*\(((?:[^()]|\([^()]*\))*)\))?(?:\s+КАК\s+(' + IDENT + '))?', text, re.I):
                out.append((file, line, text, m.group(4), m.group(3) or ''))
    return out


SCHEDULE_FIELD = r'(' + IDENT + r'?(?:ФактическийПериодДействия|ПериодДействия|ПериодРегистрации|БазовыйПериод))'


def unwrapped(text, alias):
    """Schedule values selected without ЕСТЬNULL: fields «<resource><period>» outside an ЕСТЬNULL(...) call."""
    select = re.search(r'ВЫБРАТЬ(.*?)\bИЗ\b', text, re.S | re.I)
    if not select:
        return []
    fields = select.group(1)
    # Blank every ЕСТЬNULL(...) so what stays is outside it.
    while True:
        m = re.search(r'ЕСТЬNULL\s*\(((?:[^()]|\([^()]*\))*)\)', fields, re.I)
        if not m:
            break
        fields = fields[:m.start()] + ' ' * (m.end() - m.start()) + fields[m.end():]
    prefix = (re.escape(alias) + r'\.') if alias else r'(?<![\wЁё.])'
    return re.findall((r'(?<![\wЁё])' if alias else '') + prefix + SCHEDULE_FIELD + r'(?![\wЁё])', fields)


def signs(src):
    src = Path(src)
    out = {}
    registers = sorted(src.glob('CalculationRegisters/*.xml'))
    if not registers:
        reason = 'регистров расчёта в решении нет'
        return {k: ('not_assessed', reason) for k in ('EXM01', 'EXM02', 'EXM03', 'EXM04', 'EXM05')}
    names = {r.stem for r in registers}
    modules = code_of(src)

    # EXM01 (1:19:40): calculation tasks are not operational; operational posting of the accrual document is denied.
    allowed = []
    for doc in sorted(src.glob('Documents/*.xml')):
        text = read(doc)
        if any('CalculationRegister.' + n + '<' in text for n in names) and prop(text, 'RealTimePosting') == 'Allow':
            allowed.append(doc.stem)
    out['EXM01'] = ('violation', 'оперативное проведение разрешено у документов с движениями по регистрам расчёта: ' + ', '.join(allowed)) if allowed \
        else ('no_violation_found', 'у документов с движениями по регистрам расчёта оперативное проведение запрещено')

    queries = schedule_queries(modules)
    # EXM02 (1:55:22): data of the schedule is taken only for the records being calculated: a filter by registrator.
    unfiltered = ['%s:%d' % (f, line) for f, line, text, alias, params in queries
                  if 'Регистратор' not in params and not re.search(r'\bГДЕ\b[^;]*\bРегистратор\b', text, re.I)]
    if not queries:
        out['EXM02'] = out['EXM03'] = ('not_assessed', 'данные графика запросом не читаются')
    else:
        out['EXM02'] = ('violation', 'данные графика без отбора по регистратору: ' + ', '.join(unfiltered)) if unfiltered \
            else ('no_violation_found', 'данные графика отбираются по регистратору')
        # EXM03 (1:59:01): the virtual table has a row for every record even with an empty schedule; its values are NULL
        # then, so they are wrapped in ЕСТЬNULL before arithmetic.
        bare = ['%s:%d %s' % (f, line, ', '.join(sorted(set(fields)))) for f, line, text, alias, _ in queries for fields in [unwrapped(text, alias)] if fields]
        out['EXM03'] = ('violation', 'значения графика выбираются без ЕСТЬNULL: ' + '; '.join(bare)) if bare \
            else ('no_violation_found', 'значения графика обёрнуты в ЕСТЬNULL')

    # EXM04 (2:43:43): a calculation type identifies an algorithm; unless the ticket asks for types added by users,
    # every type is predefined.
    charts = {(prop(read(r), 'ChartOfCalculationTypes') or '').split('.', 1)[-1] for r in registers} - {''}
    empty = [c for c in sorted(charts) if not re.search(r'<Item\b', read(src / 'ChartsOfCalculationTypes' / c / 'Ext' / 'Predefined.xml'))]
    # Owner decision (Д15): when users add calculation types themselves, the algorithm is chosen by an enum attribute
    # of the chart («Способ расчёта») — that is the examiner's exception, not a missing predefined type.
    by_method = [c for c in empty if re.search(r'<Attribute uuid="[^"]*">.*?<v8:Type>cfg:EnumRef\.', read(src / 'ChartsOfCalculationTypes' / (c + '.xml')), re.S)]
    empty = [c for c in empty if c not in by_method]
    out['EXM04'] = ('violation', 'в планах видов расчёта нет предопределённых видов: ' + ', '.join(empty)) if empty \
        else ('no_violation_found', 'виды расчёта предопределены' + ('; алгоритм выбирается реквизитом-перечислением: ' + ', '.join(by_method) if by_method else ''))

    # EXM05 (2:33:43): the calculation code is used at posting and at recalculation, so it belongs to a common module
    # («желательно, если претендуете на 5»; not required).
    calc = [f for f, code, _ in modules if re.search(r'\.\s*Результат\s*=[^=]', code)]
    if not calc:
        out['EXM05'] = ('not_assessed', 'присваиваний результата расчёта в коде нет')
    else:
        common = [f for f in calc if f.startswith('CommonModules/')]
        out['EXM05'] = ('no_violation_found', 'расчёт в общем модуле: ' + ', '.join(sorted(set(common)))) if common \
            else ('violation', 'расчёт только в модулях объектов: ' + ', '.join(sorted(set(calc))))
    return out


def course(src):
    """Practices of the course «СпецКурс 1С 8.3» (rules/<book>/chistov.json): {id: (status, reason)}, never scored."""
    src = Path(src)
    out = {}
    changed = []
    for module in sorted(src.glob('Documents/*/Ext/ObjectModule.bsl')) + sorted(src.glob('Catalogs/*/Ext/ObjectModule.bsl')):
        owner = module.parent.parent
        body = read(owner.parent / (owner.name + '.xml')).split('<TabularSection', 1)[0]
        names = set(re.findall(r'<Attribute uuid="[^"]*">\s*<Properties>\s*<Name>(\w+)</Name>', body)) | {'Дата', 'Номер', 'Наименование', 'Код', 'Комментарий'}
        code = lex(read(module))[0]
        for m in re.finditer(r'Процедура\s+(ПриЗаписи|ОбработкаПроведения)\s*\(.*?КонецПроцедуры', code, re.S):
            hit = [a.group(1) for a in re.finditer(r'(?:^|;)\s*(?:ЭтотОбъект\.)?([\wЁё]+)\s*=(?!=)', m.group(0), re.M) if a.group(1) in names]
            if hit:
                changed.append('%s.%s: %s' % (owner.name, m.group(1), ', '.join(sorted(set(hit)))))
    out['CHS01'] = ('violation', 'реквизиты объекта меняются после записи: ' + '; '.join(changed)) if changed \
        else ('no_violation_found', 'в ПриЗаписи и ОбработкаПроведения реквизиты объекта не меняются')
    # CHS03 (owner decision Д5, unscored): a field of a composite reference type dereferenced in a query without
    # ВЫРАЗИТЬ joins every table of the type (#std654).
    composite = composite_fields(src)
    dotted = ['%s: %s' % (file, m.group(0)) for file, _, strings in code_of(src) for text, _ in strings
              for m in re.finditer(r'(?<![\wЁё.])[\wЁё]+\.(' + '|'.join(map(re.escape, sorted(composite))) + r')\.[\wЁё]+', text) if composite]
    out['CHS03'] = ('violation', 'разыменование поля составного типа без ВЫРАЗИТЬ: ' + '; '.join(sorted(set(dotted))[:3])) if dotted \
        else ('no_violation_found', 'поля составного типа в запросах приводятся через ВЫРАЗИТЬ или не разыменовываются')
    if not list(src.glob('CalculationRegisters/*.xml')):
        out['CHS02'] = ('not_assessed', 'регистров расчёта в решении нет')
        return out
    length = []
    for file, code, strings in code_of(src):
        for text in [code] + [t for t, _ in strings]:
            length += ['%s: %s' % (file, m.group(0).strip()[:100]) for m in re.finditer(
                r'[^;\n]*БазовыйПериодКонец[^;\n]*-[^;\n]*БазовыйПериодНачало[^;\n]*|РАЗНОСТЬДАТ\s*\([^)]*БазовыйПериод[^)]*\)', text, re.I)]
    out['CHS02'] = ('violation', 'дни базы — длина базового периода: ' + '; '.join(length[:3])) if length \
        else ('no_violation_found', 'дни базы не считаются длиной базового периода')
    return out


def composite_fields(src):
    """Names of query fields of a composite reference type: fields with several reference types in the metadata, the
    registrar of a register written by several document kinds, subconto of accounting registers."""
    src = Path(src)
    names = set()
    for path in src.rglob('*.xml'):
        if path.parent.name == 'Ext':
            continue
        for m in re.finditer(r'<(?:Dimension|Resource|Attribute) uuid="[^"]*">\s*<Properties>\s*<Name>(\w+)</Name>(.*?)</Properties>', read(path), re.S):
            if len(re.findall(r'<v8:Type>cfg:\w+Ref\.', m.group(2))) > 1:
                names.add(m.group(1))
    writers = {}
    for doc in src.glob('Documents/*.xml'):
        for ref in re.findall(r'<xr:Item xsi:type="xr:MDObjectRef">(\w+Register\.\w+)</xr:Item>', read(doc)):
            writers.setdefault(ref, set()).add(doc.stem)
    if any(len(docs) > 1 for docs in writers.values()):
        names.add('Регистратор')
    if list(src.glob('AccountingRegisters/*.xml')):
        names |= {'Субконто1', 'Субконто2', 'Субконто3', 'СубконтоДт1', 'СубконтоДт2', 'СубконтоДт3', 'СубконтоКт1', 'СубконтоКт2', 'СубконтоКт3'}
    return names


def standards(src):
    """Practices of the 1C development standards (rules/<book>/standards.json): {id: (status, reason)}, never scored."""
    from .codescan import posting_modules
    src = Path(src)
    written = {r for f in src.glob('Documents/*.xml') for r in re.findall(r'MDObjectRef">\w+Register\.(\w+)<', read(f))}
    texts = [read(f) for f in sorted(src.rglob('*.bsl')) if 'BenchmarkObserver' not in f.parts]
    helpers = set()
    for text in texts:
        for m in re.finditer(r'(?:Процедура|Функция)\s+(\w+)\s*\(([^)]*)\)(.*?)(?:КонецПроцедуры|КонецФункции)', lex(text)[0], re.S):
            params = [p.strip().split('=')[0].replace('Знач ', '').strip() for p in m.group(2).split(',')]
            if any(re.search(r'\.Добавить\(\s*' + re.escape(p) + r'\s*\)', m.group(3)) for p in params if p):
                helpers.add(m.group(1))
    call = r'(?:\.Добавить' + ''.join('|' + re.escape(h) for h in sorted(helpers)) + r')\(\s*"(РегистрСведений|РегистрНакопления|РегистрБухгалтерии)\.(\w+)"'
    locked = {m.groups() for text in texts for m in re.finditer(call, text)}
    reads = set()
    for f in posting_modules(src):
        code, strings = lex(read(f))
        for text, _ in strings:
            reads |= set(re.findall(r'(РегистрСведений|РегистрНакопления|РегистрБухгалтерии)\.(\w+)(?![\wЁё])', text))
        reads |= {('РегистрСведений', n) for n in re.findall(r'РегистрыСведений\.(\w+)\.(?:СрезПоследних|СрезПервых|Получить|Выбрать)\s*\(', code)}
    open_reads = sorted('%s.%s' % x for x in reads if x[1] not in written and x not in locked)
    if not reads:
        return {'STD01': ('not_assessed', 'проведение не читает регистры')}
    return {'STD01': ('violation', 'читаются при проведении без разделяемой блокировки: ' + ', '.join(open_reads)) if open_reads
            else ('no_violation_found', 'читаемые при проведении регистры защищены управляемой блокировкой или записываются решением')}

