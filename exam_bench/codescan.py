"""Concrete signs of official penalties in the solution's BSL code (posting code: documents and common modules).

Only unambiguous signs are reported; a rule whose violation depends on judgement («без необходимости») is not
scanned here. Each sign carries the file and line so a person can check it.
"""
import re
from pathlib import Path

VIRTUAL = r'(Остатки|Обороты|ОстаткиИОбороты|СрезПоследних|СрезПервых)'
TABLES = {'РегистрНакопления': 'AccumulationRegisters', 'РегистрБухгалтерии': 'AccountingRegisters', 'РегистрСведений': 'InformationRegisters'}
MANAGERS = r'(Справочники|Документы|РегистрыСведений|РегистрыНакопления|РегистрыБухгалтерии|РегистрыРасчета|ПланыСчетов|ПланыВидовХарактеристик|ПланыВидовРасчета)'
READS = r'(НайтиПоКоду|НайтиПоНаименованию|НайтиПоРеквизиту|Выбрать|Получить|ПолучитьПоследнее|ПолучитьПервое|СрезПоследних|СрезПервых|Остатки|Обороты|ПолучитьБазу|ПолучитьДанныеГрафика)'
CLAUSE_END = r'\b(СГРУППИРОВАТЬ|УПОРЯДОЧИТЬ|ИМЕЮЩИЕ|ОБЪЕДИНИТЬ|ИТОГИ|ДЛЯ\s+ИЗМЕНЕНИЯ|ИНДЕКСИРОВАТЬ|ВЫБРАТЬ|ПОМЕСТИТЬ)\b|;'


def lex(text):
    """(code with strings and comments blanked, [(string text, line)]): line numbers stay valid."""
    code, spans = lex_spans(text)
    return code, [(s, line) for s, line, _, _ in spans]


def lex_spans(text):
    """As lex, with each string's [start, end) offsets in text: the blanked code around a literal shows how it is used."""
    code, strings, i, n = [], [], 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith('//', i):
            j = text.find('\n', i)
            j = n if j < 0 else j
            code.append(' ' * (j - i)); i = j
        elif c == '"':
            line = text.count('\n', 0, i) + 1
            j, buf = i + 1, []
            while j < n:
                if text[j] == '"':
                    if text.startswith('""', j):
                        buf.append('"'); j += 2; continue
                    break
                if text[j] == '\n':
                    # A multi-line literal continues on lines starting with «|».
                    k = j + 1
                    while k < n and text[k] in ' \t':
                        k += 1
                    if k < n and text[k] == '|':
                        buf.append('\n'); j = k + 1; continue
                    break
                buf.append(text[j]); j += 1
            strings.append((''.join(buf), line, i, j + 1))
            code.append(''.join('\n' if ch == '\n' else ' ' for ch in text[i:j + 1])); i = j + 1
        else:
            code.append(c); i += 1
    return ''.join(code), strings


def posting_modules(src, exclude=()):
    src = Path(src)
    paths = list(src.glob('Documents/*/Ext/ObjectModule.bsl')) + list(src.glob('Documents/*/Ext/ManagerModule.bsl'))
    paths += [p for p in src.glob('CommonModules/*/Ext/Module.bsl') if p.parent.parent.name not in exclude and p.parent.parent.name != 'BenchmarkObserver']
    return sorted(paths)


IDENT = r'[A-Za-zА-Яа-яЁё_][\wЁё]*'


def loop_depth(code):
    """Loops opened and not closed in a code fragment."""
    return len(re.findall(r'(?<![\wЁё])Цикл(?![\wЁё])', code)) - len(re.findall(r'(?<![\wЁё])КонецЦикла(?![\wЁё])', code))


def unloaded_once(src):
    """[(file, line, variable)]: a query result unloaded to a value table that is then only walked once.

    The variable takes «….Выполнить().Выгрузить()» and its only later use is «Для Каждого … Из <variable> Цикл» not
    nested in a loop opened after the unloading: Выбрать() would walk the result without the intermediate table. A
    search, sort, total, a pass to another method or repeated walking (a loop inside a loop) is a reason to unload.
    """
    src, out = Path(src), []
    for path in sorted(src.rglob('*.bsl')):
        if 'BenchmarkObserver' in path.parts:
            continue
        code = lex(path.read_text(encoding='utf-8-sig', errors='replace'))[0]
        for method in re.finditer(r'(?:Процедура|Функция)\s+' + IDENT + r'\s*\(.*?(?:КонецПроцедуры|КонецФункции)', code, re.S | re.I):
            body = method.group(0)
            for m in re.finditer(r'(' + IDENT + r')\s*=\s*[^;]*?\.Выполнить\(\s*\)\s*\.Выгрузить\(\s*\)\s*;', body):
                rest = body[m.end():]
                uses = list(re.finditer(r'(?<![\wЁё.])' + re.escape(m.group(1)) + r'(?![\wЁё])', rest))
                walks = [u for u in uses if re.search(r'Для\s+Каждого\s+' + IDENT + r'\s+Из\s*$', rest[:u.start()], re.I)
                         and re.match(r'\s*Цикл(?![\wЁё])', rest[u.end():]) and loop_depth(rest[:u.start()]) == 0]
                if len(uses) == len(walks) == 1:
                    out.append((path.relative_to(src).as_posix(), code.count('\n', 0, method.start() + m.start()) + 1, m.group(1)))
    return out


def dimensions(src, table, name):
    folder = TABLES.get(table)
    path = Path(src) / folder / (name + '.xml') if folder else None
    if not path or not path.is_file():
        return set()
    text = path.read_text(encoding='utf-8-sig')
    dims = {m.group(1) for m in re.finditer(r'<Dimension uuid="[^"]*">\s*<Properties>\s*<Name>(\w+)</Name>', text)}
    return dims | ({'Счет', 'Account'} if table == 'РегистрБухгалтерии' else set())


def reference_fields(src):
    """Names of fields of a reference type in the metadata (dimensions, resources, attributes) plus standard ones."""
    names = {'Ссылка', 'Регистратор', 'Владелец', 'Родитель'}
    for path in Path(src).rglob('*.xml'):
        if path.parent.name == 'Ext' or 'BenchmarkObserver' in path.parts:
            continue
        text = path.read_text(encoding='utf-8-sig', errors='replace')
        for m in re.finditer(r'<(?:Dimension|Resource|Attribute) uuid="[^"]*">\s*<Properties>\s*<Name>(\w+)</Name>(.*?)</Properties>', text, re.S):
            if re.search(r'<v8:Type>cfg:\w+Ref\.', m.group(2)):
                names.add(m.group(1))
    return names


def string_aliases(strings):
    """Aliases a query gives to an expression that is not the field of the same name («ПРЕДСТАВЛЕНИЕ(Т.Товар) КАК Товар»)."""
    out = set()
    for text, _ in strings:
        for expr, alias in re.findall(r'([^,\n]+?)\s+КАК\s+([\wЁё]+)', text, re.I):
            if not re.fullmatch(r'\s*[\wЁё]+\.' + re.escape(alias) + r'\s*', expr):
                out.add(alias)
    return out


def scan(src, binding):
    """{sign: [(file, line, text)]} for the scanned signs."""
    src = Path(src)
    demo = ((binding.get('demo_data') or {}).get('procedure') or '').split('.')
    exclude = {demo[1]} if len(demo) > 2 else set()
    signs = {'loop_reads': [], 'unknown_loop_reads': [], 'empty_virtual_parameters': [], 'where_on_dimension': [], 'schedule_table': [], 'calculation_main_table': []}
    schedule = ((binding.get('pr') or {}).get('objects') or {}).get('schedules', '').split('.', 1)[-1]
    results = [r['register'].split('.', 1)[1] for r in ((binding.get('pr') or {}).get('results') or [])]
    base_api = False
    refs = reference_fields(src)
    for path in posting_modules(src, exclude):
        rel = path.relative_to(src).as_posix()
        text = path.read_text(encoding='utf-8-sig', errors='replace')
        code, strings = lex(text)
        # The base table of a calculation register is named after the base register: РегистрРасчета.Р.БазаОсновныеНачисления.
        if re.search(r'РегистрРасчета\.\w+\.База\w+|\bПолучитьБазу\s*\(', text):
            base_api = True
        # Reads inside loops: depth of Цикл ... КонецЦикла in the code without strings and comments.
        reads = re.compile(r'\.\s*Выполнить\s*\(|' + MANAGERS + r'\.\w+\.' + READS + r'\s*\(')  # data reads (М4.20), not object edits
        source_lines = text.splitlines()
        # A stack of open loops: True for a loop over data (Для Каждого, Пока, Для ... По <expression>); a loop with
        # literal numeric bounds (Для Этап = 1 По 2) runs a fixed number of stages and is not a per-record loop.
        # Each open loop: (over data?, the variable it walks — «Для Каждого X Из», «Пока X.Следующий()»).
        named = refs - string_aliases(strings)
        stack, flat, header_start = [], code, 0
        tokens = list(re.finditer(r'(?<![\wа-яё])(конеццикла|цикл|конецпроцедуры|конецфункции)(?![\wа-яё])', flat.lower()))
        cursor = 0
        for token in tokens:
            segment = flat[cursor:token.start()]
            if any(data for data, _ in stack):
                found = [m.start() for m in reads.finditer(segment)]
                # A hidden read (М4.20): an attribute of a reference taken through the loop variable, «Выборка.Товар.Код».
                # Methods («Набор.Отбор.Регистратор.Установить(…)») and key-value pairs are not reads of the base.
                for _, var in stack:
                    if var:
                        from .querytypes import loop_fields
                        fields = loop_fields(src, text, cursor, var)
                        for m in re.finditer(r'(?<![\wЁё.])' + re.escape(var) + r'\.(?!Отбор\.|Значение\.|Ключ\.)(' + IDENT + r')\.' + IDENT + r'(?![\wЁё])(?!\s*\()', segment):
                            types = fields.get(m[1].lower())
                            if types and any('Ref.' in t for t in types):
                                found.append(m.start())
                            elif types is None:
                                signs['unknown_loop_reads'].append((rel, flat.count('\n', 0, cursor + m.start()) + 1, m.group(0)))
                        # A reference turned into a string (concatenation, a message, a template parameter) reads its
                        # presentation from the base on every pass; the query should select ПРЕДСТАВЛЕНИЕ.
                        field = re.escape(var) + r'\.(' + IDENT + r')(?![\wЁё.(])'
                        for pattern in (r'\+\s*' + field, r'(?<![\wЁё.])' + field + r'\s*\+', r'(?:Сообщить|СообщитьПользователю|Строка|СтрШаблон)\s*\([^;]*?(?<![\wЁё.])' + field,
                                        r'\.Параметры\.' + IDENT + r'\s*=\s*' + field):
                            # A message on a branch that leaves the loop («…; Возврат;») runs once, not on every pass.
                            found += [m.start() for m in re.finditer(pattern, segment) if m.group(1) in named
                                      and not re.match(r'(?:(?!КонецЕсли|КонецЦикла|ИначеЕсли|Иначе(?![\wЁё])).)*?(?<![\wЁё])(?:Возврат|Прервать|ВызватьИсключение)(?![\wЁё])', segment[m.end():], re.S)
                                      and not re.search(r'(?<![\wЁё])ВызватьИсключение(?![\wЁё])[^;]*$', segment[:m.start()], re.I)]
                for start in sorted(set(found)):
                    no = flat.count('\n', 0, cursor + start) + 1
                    signs['loop_reads'].append((rel, no, source_lines[no - 1].strip()[:160]))
            word = token.group(1)
            if word == 'цикл':
                head = flat[max(flat.rfind(';', 0, token.start()), flat.rfind('\n', 0, token.start()) - 400, 0):token.start()]
                fixed = re.search(r'Для\s+\w+\s*=\s*\d+\s+По\s+\d+\s*$', head, re.I)
                var = re.search(r'Для\s+Каждого\s+(' + IDENT + r')\s+Из\b', head, re.I) or re.search(r'Пока\s+(' + IDENT + r')\.Следующий\s*\(\s*\)\s*$', head, re.I)
                stack.append((not fixed, var.group(1) if var else None))
            elif word == 'конеццикла':
                if stack:
                    stack.pop()
            else:
                stack = []
            cursor = token.end()
        for literal, line in strings:
            for m in re.finditer(r'(РегистрНакопления|РегистрБухгалтерии|РегистрСведений)\.(\w+)\.' + VIRTUAL + r'\s*\(', literal):
                depth, end = 1, m.end()
                while end < len(literal) and depth:
                    depth += {'(': 1, ')': -1}.get(literal[end], 0)
                    end += 1
                arguments = literal[m.end():end-1]
                if depth == 0 and not arguments.replace(',', '').strip():
                    signs['empty_virtual_parameters'].append((rel, line + literal.count('\n', 0, m.start()), literal[m.start():end][:120]))
            for m in re.finditer(r'(РегистрНакопления|РегистрБухгалтерии|РегистрСведений)\.(\w+)\.' + VIRTUAL + r'\s*\(', literal):
                depth_, j = 1, m.end()
                while j < len(literal) and depth_:
                    depth_ += {'(': 1, ')': -1}.get(literal[j], 0); j += 1
                alias = re.match(r'\s*КАК\s+(\w+)', literal[j:], re.I)
                if not alias:
                    continue
                rest = literal[j + alias.end():]
                where = re.search(r'\bГДЕ\b', rest)
                if not where or re.search(r'\bВЫБРАТЬ\b', rest[:where.start()]):
                    continue
                clause = re.split(CLAUSE_END, rest[where.end():])[0]
                dims = dimensions(src, m.group(1), m.group(2))
                used = {f for f in re.findall(r'\b' + alias.group(1) + r'\.(\w+)', clause) if f in dims}
                if used:
                    signs['where_on_dimension'].append((rel, line + literal.count('\n', 0, m.start()), '%s.%s.%s: ГДЕ по %s' % (m.group(1), m.group(2), m.group(3), ', '.join(sorted(used)))))
            if schedule and re.search(r'РегистрСведений\.' + re.escape(schedule) + r'\b', literal):
                signs['schedule_table'].append((rel, line, 'запрос к РегистрСведений.' + schedule))
            # Reading the records of the document being posted (… ГДЕ Т.Регистратор = &…) is how they are calculated, not a base.
            own_records = re.search(r'\.Регистратор\s*=\s*&', literal)
            for reg in ([] if own_records else results):
                for m in re.finditer(r'РегистрРасчета\.' + re.escape(reg) + r'(?!\.)\b', literal):
                    signs['calculation_main_table'].append((rel, line + literal.count('\n', 0, m.start()), 'запрос к основной таблице РегистрРасчета.' + reg))
        if schedule:
            for m in re.finditer(r'РегистрыСведений\.' + re.escape(schedule) + r'\.(Выбрать|Получить|СрезПоследних|СрезПервых)\s*\(', code):
                signs['schedule_table'].append((rel, code.count('\n', 0, m.start()) + 1, m.group(0)))
    if base_api:
        signs['calculation_main_table'] = []  # the base is obtained by the calculation mechanism somewhere: not a proved base-from-table
    recalc = [p.relative_to(src).as_posix() for p in src.glob('CalculationRegisters/*/Recalculations/*.xml')]
    signs['recalculations'] = [(p, 1, 'перерасчёт ' + Path(p).stem) for p in recalc]
    return signs
