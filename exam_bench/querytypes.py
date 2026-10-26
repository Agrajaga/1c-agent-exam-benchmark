"""Conservative source-scoped types for simple static query projections.

Unknown aliases, derived tables and nested queries are not proof of a reference type.
"""
import re
from pathlib import Path

FOLDERS = {'Справочник': 'Catalogs', 'Документ': 'Documents', 'РегистрСведений': 'InformationRegisters',
           'РегистрНакопления': 'AccumulationRegisters', 'РегистрБухгалтерии': 'AccountingRegisters',
           'РегистрРасчета': 'CalculationRegisters', 'ПланСчетов': 'ChartsOfAccounts',
           'ПланВидовХарактеристик': 'ChartsOfCharacteristicTypes', 'ПланВидовРасчета': 'ChartsOfCalculationTypes'}


def field_types(src, kind, name):
    path = Path(src) / FOLDERS[kind] / (name + '.xml')
    if not path.is_file():
        path = next((p for p in (Path(src)/FOLDERS[kind]).glob('*.xml') if p.stem.casefold() == name.casefold()), None)
        if path is None:
            return {}
    name = path.stem
    text = path.read_text(encoding='utf-8-sig').split('<TabularSection', 1)[0]
    fields = {}
    for m in re.finditer(r'<(?:Dimension|Resource|Attribute)\b[^>]*>\s*<Properties>\s*<Name>(\w+)</Name>(.*?)</Properties>', text, re.S):
        fields[m[1].lower()] = re.findall(r'<v8:Type>([^<]+)</v8:Type>', m[2])
    if kind in ('Справочник', 'Документ'):
        fields['ссылка'] = ['cfg:' + ('CatalogRef.' if kind == 'Справочник' else 'DocumentRef.') + name]
    register = {'РегистрНакопления': 'AccumulationRegister', 'РегистрБухгалтерии': 'AccountingRegister',
                'РегистрРасчета': 'CalculationRegister', 'РегистрСведений': 'InformationRegister'}.get(kind)
    if register:
        writers = [p.stem for p in (Path(src)/'Documents').glob('*.xml')
                   if re.search(r'>\s*' + register + r'\.' + re.escape(name) + r'\s*<', p.read_text(encoding='utf-8-sig'), re.I)]
        if writers:
            fields['регистратор'] = ['cfg:DocumentRef.' + n for n in writers]
    return fields


def source_types(src, query):
    # Do not let an inner query's alias overwrite an outer alias with the same spelling.
    if len(re.findall(r'\bВЫБРАТЬ\b', query, re.I)) != 1:
        return {}
    aliases = {}
    pattern = r'\b(?:ИЗ|СОЕДИНЕНИЕ)\s+(' + '|'.join(FOLDERS) + r')\.(\w+)(?:\.(\w+))?'
    for m in re.finditer(pattern, query, re.I):
        end = m.end()
        if query[end:].lstrip().startswith('('):
            end += len(query[end:]) - len(query[end:].lstrip())
            depth = 1; end += 1
            while end < len(query) and depth:
                depth += {'(': 1, ')': -1}.get(query[end], 0); end += 1
            if depth:
                continue
        alias = re.match(r'\s+КАК\s+(\w+)', query[end:], re.I)
        name = alias[1] if alias else m[2]
        kind = next(k for k in FOLDERS if k.lower() == m[1].lower())
        fields = field_types(src, kind, m[2])
        # A tabular section needs its own scope, which this reader does not infer.
        if m[3] and m[3].lower() not in ('остатки','обороты','остаткииобороты','срезпоследних','срезпервых','данныеграфика'):
            fields = {}
        aliases[name.lower()] = fields if name.lower() not in aliases else {}
    return aliases


def query_dereferences(src, query):
    sources = source_types(src, query)
    for m in re.finditer(r'(?<![\w.])(\w+)\.(\w+)\.(\w+)', query):
        if m[1].lower() in {k.lower() for k in FOLDERS}:
            continue
        types = sources.get(m[1].lower(), {}).get(m[2].lower())
        yield m, types


def projection(src, query):
    sources = source_types(src, query)
    result = {}
    select = re.search(r'\bВЫБРАТЬ\b(.*?)\bИЗ\b', query, re.S | re.I)
    if not select:
        return result
    for item in select[1].split(','):
        m = re.fullmatch(r'\s*(\w+)\.(\w+)(?:\s+КАК\s+(\w+))?\s*', item, re.I)
        if m:
            result[(m[3] or m[2]).lower()] = sources.get(m[1].lower(), {}).get(m[2].lower())
    return result


def loop_fields(src, text, position, var):
    from .codescan import lex_spans
    code, strings = lex_spans(text[:position])
    starts = list(re.finditer(r'\b(?:Процедура|Функция)\s+\w+\s*\(', code, re.I))
    begin = starts[-1].start() if starts else 0
    events = []
    for m in re.finditer(r'(?<![\w.])(\w+)\s*=\s*([^;\n]*)', code[begin:]):
        copy = re.fullmatch(r'(\w+)\.(?:Выполнить\(\)\.)?(?:Выбрать|Выгрузить|Выполнить)\(\)\s*', m[2], re.I)
        row = re.fullmatch(r'(\w+)\.(Добавить|НайтиСтроки)\([^)]*\)\s*', m[2], re.I)
        value = copy[1].lower() if copy else None
        if re.match(r'Новый\s+ТаблицаЗначений\b', m[2], re.I) or row and row[2].lower() == 'найтистроки':
            value = {'__memory__': True}
        elif row:
            value = row[1].lower()
        events.append((begin+m.start(), 0, m[1].lower(), value))
    for m in re.finditer(r'(?<![\w.])(\w+)\.(\w+)\s*=\s*(\w+)\s*;', code[begin:]):
        events.append((begin+m.start(), 2, m[1].lower(), (m[2].lower(), m[3].lower())))
    for query, _, start, _ in strings:
        owner = re.search(r'(\w+)(?:\.Текст)?\s*=\s*(?:Новый\s+Запрос\s*\(\s*)?$', code[begin:start], re.I)
        if owner:
            events.append((start, 1, owner[1].lower(), projection(src, query)))
    for m in re.finditer(r'Для\s+Каждого\s+(\w+)\s+Из\s+(\w+)\s+Цикл', code[begin:], re.I):
        events.append((begin+m.start(), 0, m[1].lower(), m[2].lower()))
    values = {}
    for _, kind, name, value in sorted(events):
        if kind == 2:
            field, source = value
            if values.get(source, {}).get('__memory__') and name in values:
                values[name][field] = []  # the value is a row/collection in memory, not a reference
            elif name in values:
                values[name][field] = None
            continue
        values[name] = value if isinstance(value, dict) else values.get(value, {})
    return values.get(var.lower(), {})
