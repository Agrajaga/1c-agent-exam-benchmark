"""Penalty signs read from the platform's own reading of the solution's queries (СхемаЗапроса) and storage indexes.

The observer of exam_bench.queries returns, for every query text the platform parsed, its schema: per operator the
sources (table name, alias, virtual table parameters, joins with type and condition), ГДЕ conditions, selected
fields and grouping, as the platform normalises them. It also returns the infobase storage structure with indexes
(ПолучитьСтруктуруХраненияБазыДанных). Signs found here:

- М4.15 (F1C-GEN15) — a filter with no usable index: the conditions on a source (=, В, or a range by МЕЖДУ, <, >)
  name no field that leads an index of the table the platform reads (std652). Totals of accumulation registers and slices of information registers are
  read by period implicitly, so the period never counts as a leading field there.
- М4.14 (F1C-GEN14) — totals computed over the main table of an accumulation or accounting register (aggregation or
  grouping) instead of its virtual table, unless the query reads the records of one registrar.
- М4.24 (F1C-GEN24) — a virtual table joined by a field that is not passed into its parameters: the join filters
  what the parameters should have filtered.
- М4.22 (F1C-GEN22) — a field of an outer-joined table used in arithmetic without ЕСТЬNULL, or in ГДЕ without a NULL
  check (the outer join silently becomes an inner one).
- М7.9 (F1C-PR09) — a base virtual table of a calculation register whose condition does not restrict the registrar.
- М4.28 (F1C-GEN28, decision A18) — balances read before writing only to control quantities (the old posting method).

Not read: accounting and calculation register virtual tables (several totals tables) and temporary tables (std777).
"""
import re

AGGREGATE = re.compile(r'\b(СУММА|SUM|КОЛИЧЕСТВО|COUNT|МАКСИМУМ|MAX|МИНИМУМ|MIN|СРЕДНЕЕ|AVG)\s*\(', re.I)
VIRTUAL = ('Остатки', 'Обороты', 'ОстаткиИОбороты', 'СрезПоследних', 'СрезПервых')
REGISTERS = ('РегистрНакопления', 'РегистрБухгалтерии')
STORAGE_NAMES = {'Period': 'Период', 'Recorder': 'Регистратор', 'LineNo': 'НомерСтроки', 'ID': 'Ссылка', 'Splitter': None}
NAME = r'[A-Za-zА-Яа-яЁё_][\wЁё]*'


def conjuncts(expr):
    """Top-level И/AND parts of a condition; parentheses around the whole part are dropped."""
    parts, depth, start, i = [], 0, 0, 0
    text = expr or ''
    while i < len(text):
        c = text[i]
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        elif depth == 0:
            m = re.match(r'\s(И|AND)\s', text[i:], re.I)
            if m:
                parts.append(text[start:i]); i += m.end(); start = i; continue
        i += 1
    parts.append(text[start:])
    out = []
    for p in (p.strip() for p in parts):
        while p.startswith('(') and p.endswith(')') and balanced(p[1:-1]):
            p = p[1:-1].strip()
        if p:
            out.append(p)
    return out


def balanced(text):
    depth = 0
    for c in text:
        depth += {'(': 1, ')': -1}.get(c, 0)
        if depth < 0:
            return False
    return depth == 0


def refs(expr, alias):
    """Fields of alias referenced in expr (the first name after «alias.»)."""
    return {m.group(1) for m in re.finditer(r'(?<![\wЁё.])' + re.escape(alias) + r'\.(' + NAME + ')', expr or '')}


def outside_isnull(expr):
    """expr without the arguments of ЕСТЬNULL/ISNULL calls."""
    out, i = [], 0
    while i < len(expr):
        m = re.match(r'(ЕСТЬNULL|ISNULL)\s*\(', expr[i:], re.I)
        if m:
            depth, j = 1, i + m.end()
            while j < len(expr) and depth:
                depth += {'(': 1, ')': -1}.get(expr[j], 0); j += 1
            out.append(' '); i = j; continue
        out.append(expr[i]); i += 1
    return ''.join(out)


def operators(batch):
    """Every operator of a batch, nested queries included."""
    for item in batch or []:
        for op in item.get('operators') or []:
            yield op
            for source in op.get('sources') or []:
                if source.get('nested'):
                    yield from operators([source['nested']])


def table_parts(name):
    """('РегистрНакопления', 'Товары', 'Остатки') for РегистрНакопления.Товары.Остатки; a temp table has one part."""
    return tuple((name or '').split('.'))


def index_lookup(storage):
    """{(metadata, purpose): [[leading-first field names]]} from the storage structure."""
    out = {}
    for table in storage or []:
        indexes = []
        for fields in table.get('indexes') or []:
            names = []
            for f in fields:
                name = f.get('name') or (f.get('metadata') or '').rsplit('.', 1)[-1] or STORAGE_NAMES.get(f.get('storage'), f.get('storage'))
                name = STORAGE_NAMES.get(name, name) if name in STORAGE_NAMES else name
                if name:
                    names.append(name)
            if names:
                indexes.append(names)
        out.setdefault((table.get('metadata'), table.get('purpose')), []).extend(indexes)
    return out


def storage_of(parts):
    """(metadata, purpose, implicit fields) of the table the platform reads for a source, or None if not read here."""
    if len(parts) == 2 and parts[0] in ('Справочник', 'Документ', 'РегистрСведений', 'РегистрНакопления', 'РегистрБухгалтерии', 'ПланСчетов',
                                         'ПланВидовХарактеристик', 'ПланВидовРасчета', 'РегистрРасчета'):
        return '.'.join(parts), 'Основная', set()
    if len(parts) == 3 and parts[0] == 'РегистрНакопления' and parts[2] in ('Остатки', 'Обороты', 'ОстаткиИОбороты'):
        return '.'.join(parts[:2]), 'Итоги', {'Период'}
    if len(parts) == 3 and parts[0] == 'РегистрСведений' and parts[2] in ('СрезПоследних', 'СрезПервых'):
        return '.'.join(parts[:2]), 'Основная', {'Период'}
    return None


def condition_params(source):
    """Virtual table parameters that are conditions (they compare fields), not periods or lists of dimensions."""
    return [p for p in source.get('params') or [] if re.search(r'=|<|>|\s(В|IN)\s*\(|\s(В|IN)\s', p, re.I) and not p.startswith('&')]


def equality_fields(expr, alias, bare=False):
    """Fields of the source compared by = or В in one conjunct; bare: unqualified names count (virtual table params)."""
    if re.search(r'\s(ИЛИ|OR)\s', expr, re.I) or not re.search(r'=|\s(В|IN)\s*\(', expr, re.I):
        return set()
    found = refs(expr, alias)
    if bare:
        m = re.match(r'(' + NAME + r')(\.' + NAME + r')*\s*(=|\s(В|IN)\s*\()', expr, re.I)
        if m:
            found.add(m.group(1))
    return found


def direct_refs(expr, alias):
    """Fields of alias referenced without dereferencing («alias.Поле», not «alias.Поле.Реквизит»)."""
    return {m.group(1) for m in re.finditer(r'(?<![\wЁё.])' + re.escape(alias) + r'\.(' + NAME + r')(?![\wЁё]|\.' + NAME + ')', expr or '')}


def dimensions(parts, indexes):
    """Fields a virtual table can filter by in its condition parameter: register dimensions (and account, subconto)."""
    if parts[0] == 'РегистрБухгалтерии':
        return {'Счет', 'Субконто1', 'Субконто2', 'Субконто3', 'Организация'}
    target = storage_of(parts)
    if not target:
        return set()
    metadata, purpose, implicit = target
    return {f for idx in indexes.get((metadata, purpose), []) for f in idx} - implicit - {'Регистратор', 'НомерСтроки'}


def listlike(source):
    """A temporary table or a tabular section: a list of values the code put together."""
    if not source or source.get('kind') != 'table':
        return False
    parts = table_parts(source.get('table'))
    return len(parts) == 1 or len(parts) == 3 and parts[0] in ('Документ', 'Справочник')


def range_fields(expr, alias, bare=False):
    """Fields of the source bounded by МЕЖДУ or <, >: an index leading with such a field is used by a range seek."""
    if re.search(r'\s(ИЛИ|OR)\s', expr, re.I) or not re.search(r'\s(МЕЖДУ|BETWEEN)\s|<|>', expr, re.I):
        return set()
    found = refs(expr, alias)
    if bare:
        m = re.match(r'(' + NAME + r')\s*(<|>|\s(МЕЖДУ|BETWEEN)\s)', expr, re.I)
        if m:
            found.add(m.group(1))
    return found


def signs(schema, storage):
    """Penalty signs of one parsed query text: [{'penalty', 'target', 'detail'}]; target is the table or outer-joined alias."""
    indexes = index_lookup(storage)
    out = []
    for op in operators(schema):
        sources = op.get('sources') or []
        where = [c for e in op.get('where') or [] for c in conjuncts(e)]
        joins = [(s['alias'], j) for s in sources for j in s.get('joins') or []]
        nullable = set()
        for left, j in joins:
            kind = (j.get('type') or '').lower()
            if 'лев' in kind or 'left' in kind:
                nullable.add(j['to'])
            elif 'прав' in kind or 'right' in kind:
                nullable.add(left)
            elif 'полн' in kind or 'full' in kind:
                nullable.update((left, j['to']))
        for s in sources:
            if s.get('kind') != 'table':
                continue
            alias, parts = s['alias'], table_parts(s['table'])
            params = condition_params(s)
            filtered = {f for p in params for c in conjuncts(p) for f in equality_fields(c, alias, bare=True)}
            filtered |= {f for c in where for f in equality_fields(c, alias)}
            joined = set()
            for left, j in joins:
                if alias in (left, j['to']):
                    for c in conjuncts(j.get('condition')):
                        joined |= equality_fields(c, alias)
            # М4.15: no index of the table read leads with a field the conditions use.
            target = storage_of(parts)
            ranged = {f for p in params for c in conjuncts(p) for f in range_fields(c, alias, bare=True)} | {f for c in where for f in range_fields(c, alias)}
            used = filtered | joined | ranged
            if len(parts) == 3:
                # A virtual table is filtered in storage only by its dimensions; a condition on a computed resource
                # (КоличествоОстаток > 0) filters the result and needs no index.
                used &= dimensions(parts, indexes)
            if target and used and 'Ссылка' not in used:
                metadata, purpose, implicit = target
                leading = {next((f for f in idx if f not in implicit), None) for idx in indexes.get((metadata, purpose), [])}
                if indexes.get((metadata, purpose)) and not (leading & used):
                    out.append({'penalty': 'F1C-GEN15', 'target': s['table'], 'detail': '%s: отбор по %s, индексы таблицы начинаются с %s' % (
                        s['table'], ', '.join(sorted(used)), ', '.join(sorted(f for f in leading if f)) or '—')})
            # М7.9: a base virtual table of a calculation register computed for the whole register: its condition does
            # not restrict the registrar, so the base is collected for every record, not for the document's own.
            if len(parts) == 3 and parts[0] == 'РегистрРасчета' and parts[2].startswith('База'):
                condition = (s.get('params') or [''] * 4)[3] if len(s.get('params') or []) > 3 else ''
                if not re.search(r'\bРегистратор\b|\bRecorder\b', condition):
                    out.append({'penalty': 'F1C-PR09', 'target': s['table'], 'detail': '%s: база получается без отбора по регистратору — по всем записям регистра' % s['table']})
            # М4.28 (owner decision A18): the old posting method where the new one applies. A balance query that only
            # controls quantities — selects nothing but quantity balances and the dimensions it is joined by, and does not
            # look for negative balances — reads before writing to compare with the document. The new method writes the
            # records first and then looks for negative balances. Selecting another dimension (a batch to distribute by)
            # or any amount is a reason to read before writing.
            if len(parts) == 3 and parts[0] == 'РегистрНакопления' and parts[2] in ('Остатки', 'ОстаткиИОбороты'):
                selected = [f for f in op.get('fields') or [] if refs(f, alias)]
                balances = {r for f in selected for r in refs(f, alias) if r.endswith('Остаток')}
                plain = {r for f in selected for r in refs(f, alias) if not r.endswith('Остаток')}
                negative = any(re.search(r'<\s*0|>\s*0', c) and refs(c, alias) for c in where) or any(re.search(r'^-', f.strip()) for f in selected)
                keys = set(filtered)
                for left, j in joins:
                    partner = j['to'] if left == alias else left if j['to'] == alias else None
                    if partner and listlike(next((x for x in sources if x['alias'] == partner), None)):
                        keys |= {f for c in conjuncts(j.get('condition')) for f in direct_refs(c, alias)}
                if balances and all(re.search(r'Количеств', b) for b in balances) and plain <= keys and not negative:
                    out.append({'penalty': 'F1C-GEN28', 'target': s['table'], 'detail': '%s: остатки читаются до записи только для контроля количества (старая методика); новая — записать движения и искать отрицательные остатки' % s['table']})
            # М4.14: totals over the main table of a register.
            if len(parts) == 2 and parts[0] in REGISTERS:
                aggregated = any(AGGREGATE.search(f) for f in op.get('fields') or []) or bool(op.get('group'))
                own = 'Регистратор' in filtered
                if aggregated and not own:
                    out.append({'penalty': 'F1C-GEN14', 'target': s['table'], 'detail': '%s: итоги считаются по основной таблице регистра, а не по виртуальной' % s['table']})
            # М4.24: values of a temporary table or a tabular section joined to a virtual table by its dimensions,
            # with no condition passed into the virtual table at all: the join does the filtering.
            if len(parts) == 3 and parts[2] in VIRTUAL and not params:
                dims = dimensions(parts, indexes)
                by = set()
                for left, j in joins:
                    if alias not in (left, j['to']):
                        continue
                    partner = j['to'] if left == alias else left
                    if not listlike(next((x for x in sources if x['alias'] == partner), None)):
                        continue
                    for c in conjuncts(j.get('condition')):
                        by |= {f for f in direct_refs(c, alias) if f in dims} if refs(c, partner) else set()
                if by:
                    out.append({'penalty': 'F1C-GEN24', 'target': s['table'], 'detail': '%s соединена с таблицей значений по %s, а условий в её параметрах нет' % (s['table'], ', '.join(sorted(by)))})
        # М4.22: outer-joined fields in arithmetic without ЕСТЬNULL, or in ГДЕ without a NULL check.
        for alias in sorted(nullable):
            for f in op.get('fields') or []:
                rest = outside_isnull(f)
                if refs(rest, alias) and re.search(r'[-+*/]', re.sub(r'"[^"]*"', '', rest)):
                    out.append({'penalty': 'F1C-GEN22', 'target': alias, 'detail': 'поле присоединённой таблицы %s в выражении без ЕСТЬNULL: %s' % (alias, f.strip()[:120])})
            for c in where:
                if refs(c, alias) and not re.search(r'ЕСТЬ\s+(НЕ\s+)?NULL|IS\s+(NOT\s+)?NULL|ЕСТЬNULL|ISNULL', c, re.I):
                    out.append({'penalty': 'F1C-GEN22', 'target': alias, 'detail': 'условие ГДЕ по полю присоединённой таблицы %s без проверки на NULL: %s' % (alias, c[:120])})
    return out
