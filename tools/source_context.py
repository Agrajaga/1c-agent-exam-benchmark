"""Build presentation-only source excerpts from a validated frozen submission."""
import hashlib
import re
from pathlib import Path, PurePosixPath
from xml.parsers import expat

LOCATION = re.compile(r'(?<![\w/])((?:CommonModules|Documents|Catalogs|Reports|DataProcessors|CalculationRegisters|AccumulationRegisters|AccountingRegisters|InformationRegisters|ChartsOfAccounts)/[^\s;:]+\.bsl):(\d+)', re.I)
START = re.compile(r'^\s*(?:Асинх\s+|Async\s+)?(?:Процедура|Функция|Procedure|Function)\s+([\wА-Яа-яЁё]+)\s*\(', re.I)
END = re.compile(r'\b(?:КонецПроцедуры|КонецФункции|EndProcedure|EndFunction)\b', re.I)
MAX_BYTES = 2_000_000


def safe_file(src, name):
    """Only real, bounded files inside the submitted source can be exposed."""
    if not isinstance(name, str) or '\\' in name:
        return None
    rel = PurePosixPath(name)
    if rel.is_absolute() or not rel.parts or any(p in ('', '.', '..') for p in rel.parts):
        return None
    base = Path(src).resolve()
    path = base.joinpath(*rel.parts)
    try:
        if not path.resolve().is_relative_to(base) or not path.is_file() or path.stat().st_size > MAX_BYTES:
            return None
        return path
    except OSError:
        return None


def masked_lines(lines):
    """Mask BSL strings and comments before finding method boundaries."""
    quoted = False
    for line in lines:
        masked = []
        i = 0
        while i < len(line):
            ch = line[i]
            if quoted:
                if ch == '"' and i + 1 < len(line) and line[i + 1] == '"':
                    masked.extend('  '); i += 2; continue
                if ch == '"': quoted = False
                masked.append(' ')
            elif line[i:i + 2] == '//':
                masked.extend(' ' * (len(line) - i)); break
            elif ch == '"':
                quoted = True; masked.append(' ')
            else:
                masked.append(ch)
            i += 1
        yield ''.join(masked)


def code_context(src, name, line):
    path = safe_file(src, name)
    if not path or path.suffix.lower() != '.bsl' or not isinstance(line, int):
        return None
    try:
        raw = path.read_bytes()
        lines = raw.decode('utf-8-sig').splitlines()
    except (OSError, UnicodeError):
        return None
    if not 1 <= line <= len(lines):
        return None
    method, start = None, None
    for n, text in enumerate(masked_lines(lines), 1):
        m = START.match(text)
        if m:
            start, method = n, m.group(1)
        if start and END.search(text):
            if start <= line <= n:
                break
            start, method = None, None
    else:
        start, method = None, None
    if start and method:
        end = n
        truncated = end - start > 240
        if truncated:
            start, end = max(start, line - 20), min(end, line + 20)
    else:
        start, end, truncated = max(1, line - 12), min(len(lines), line + 12), False
    return {'kind': 'bsl', 'file': name, 'sha256': hashlib.sha256(raw).hexdigest(),
            'method': method, 'start_line': start, 'marked_line': line,
            'lines': lines[start - 1:end], 'truncated': truncated}


def xml_tree(raw):
    """Read XML without external entities; retain the original line of every element."""
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        return None
    parser = expat.ParserCreate(namespace_separator='}')
    stack, roots = [], []
    def start(name, attrs):
        item = {'tag': name.split('}')[-1], 'line': parser.CurrentLineNumber, 'children': [], 'text': ''}
        (stack[-1]['children'] if stack else roots).append(item)
        stack.append(item)
        if len(stack) > 80: raise ValueError('XML too deep')
    def end(_): stack.pop()
    def text(value):
        if stack: stack[-1]['text'] += value
    parser.StartElementHandler, parser.EndElementHandler, parser.CharacterDataHandler = start, end, text
    try:
        parser.Parse(raw, True)
    except (expat.ExpatError, ValueError):
        return None
    return roots[0] if roots else None


def descendants(node):
    yield node
    for child in node['children']:
        yield from descendants(child)


def child(node, tag):
    return next((n for n in node['children'] if n['tag'] == tag), None)


def metadata_context(src, name, prop, resource=None, dimension=None):
    path = safe_file(src, name)
    if not path or path.suffix.lower() != '.xml': return None
    try:
        raw = path.read_bytes()
        lines = raw.decode('utf-8-sig').splitlines()
    except (OSError, UnicodeError):
        return None
    root = xml_tree(raw)
    if root is None: return None
    obj = next((n for n in root['children'] if child(n, 'Properties')), None)
    if not obj: return None
    obj_name = child(child(obj, 'Properties'), 'Name')
    obj_name = obj_name['text'].strip() if obj_name else path.stem
    target_owner = obj
    chain = [{'label': {'Document': 'Документ', 'AccountingRegister': 'Регистр бухгалтерии'}.get(obj['tag'], obj['tag']) + ' · ' + obj_name}]
    if resource:
        target_owner = next((n for n in descendants(obj) if n['tag'] == 'Resource'
                             and child(n, 'Properties') and child(child(n, 'Properties'), 'Name')
                             and child(child(n, 'Properties'), 'Name')['text'].strip() == resource), None)
        if not target_owner: return None
        chain.extend([{'label': 'Ресурсы'}, {'label': 'Ресурс · ' + resource}])
    if dimension:
        target_owner = next((n for n in descendants(obj) if n['tag'] == 'Dimension'
                             and child(n, 'Properties') and child(child(n, 'Properties'), 'Name')
                             and child(child(n, 'Properties'), 'Name')['text'].strip() == dimension), None)
        if not target_owner: return None
        chain.extend([{'label': 'Измерения'}, {'label': 'Измерение · ' + dimension}])
    props = child(target_owner, 'Properties')
    target = child(props, prop) if props else None
    if not props: return None
    names = {'RealTimePosting': 'Оперативное проведение', 'RegisterRecordsWritingOnPost': 'Запись движений при проведении',
             'Balance': 'Балансовый', 'AccountingFlag': 'Признак учёта', 'ExtDimensionAccountingFlag': 'Признак учёта субконто',
             'ExtDimensionAccountingFlags': 'Признаки учёта субконто',
             'Name': 'Наименование'}
    value = target['text'].strip() if target else ''
    if target and target['children']:
        value = ', '.join(x['text'].strip() for x in descendants(target) if not x['children'] and x['text'].strip())
    chain.append({'label': names.get(prop, prop), 'value': value or 'не задано', 'marked': True})
    line = target['line'] if target else props['line']
    start = max(1, line - 5)
    return {'kind': 'metadata', 'file': name, 'sha256': hashlib.sha256(raw).hexdigest(),
            'tree': chain, 'property_missing': target is None, 'start_line': start,
            'marked_line': line, 'lines': lines[start - 1:min(len(lines), line + 5)]}


def metadata_locations(charge, binding):
    """Map only explicit, unambiguous diagnostics to the exact property tested."""
    reason, pid = charge.get('reason', ''), charge.get('id', '')
    if pid == 'F1C-GEN28':
        for prefix, prop in [('оперативное проведение разрешено у документов с движениями по регистрам расчёта: ', 'RealTimePosting'),
                             ('проводимые документы в режиме «Записывать модифицированные»: ', 'RegisterRecordsWritingOnPost')]:
            if reason.startswith(prefix):
                for name in reason[len(prefix):].split(', '):
                    if re.fullmatch(r'[\wА-Яа-яЁё]+', name):
                        yield 'Documents/' + name + '.xml', prop, None, None
    if pid == 'F1C-BU05' and reason.startswith('аналитика счетов вынесена в измерения регистра бухгалтерии и есть у всех счетов: '):
        ref = (binding.get('objects') or {}).get('ledger', '')
        if ref.startswith('AccountingRegister.'):
            description = reason.split(': ', 1)[1]
            for name in re.findall(r'(?:^|,\s*)([\wА-Яа-яЁё]+)\s*\([^)]*\)', description):
                yield 'AccountingRegisters/' + ref.split('.', 1)[1] + '.xml', 'Name', None, name
    if pid == 'F1C-BU06':
        ref = (binding.get('objects') or {}).get('ledger', '')
        match = re.search(r'ресурс\s+([\wА-Яа-яЁё]+)\s+(балансовый|без признака учёта)', reason)
        if ref.startswith('AccountingRegister.') and match:
            yield 'AccountingRegisters/' + ref.split('.', 1)[1] + '.xml', 'Balance' if match[2] == 'балансовый' else 'AccountingFlag', match[1], None
    if pid == 'F1C-BU07' and reason.startswith('признаки учёта субконто не заведены:'):
        ref = (binding.get('objects') or {}).get('ledger', '')
        amount = ((binding.get('fields') or {}).get('ledger') or {}).get('amount') or 'Сумма'
        if ref.startswith('AccountingRegister.') and re.fullmatch(r'[\wА-Яа-яЁё]+', amount):
            yield 'AccountingRegisters/' + ref.split('.', 1)[1] + '.xml', 'ExtDimensionAccountingFlag', amount, None


def contexts(src, charges, assessment=None, binding=None):
    findings = (assessment or {}).get('findings', [])
    result = []
    for charge in charges:
        matches = [f for f in findings if f.get('penalty_id') == charge.get('id') and f.get('reason') == charge.get('reason')]
        locations = []
        metadata_evidence = []
        for finding in matches:
            locations.extend((e.get('file'), e.get('line')) for e in finding.get('evidence', []) if isinstance(e, dict))
            metadata_evidence.extend((e.get('file'), e.get('property'), e.get('resource'), e.get('dimension'))
                                     for e in finding.get('evidence', []) if isinstance(e, dict)
                                     and isinstance(e.get('property'), str) and re.fullmatch(r'[\wА-Яа-яЁё]+', e['property']))
        locations.extend((m.group(1), int(m.group(2))) for m in LOCATION.finditer(charge.get('reason', '')))
        seen, views = set(), []
        for name, line in locations:
            key = (name, line)
            if key in seen: continue
            seen.add(key)
            view = code_context(src, name, line)
            if view: views.append(view)
        for name, prop, resource, dimension in metadata_evidence:
            view = metadata_context(src, name, prop, resource, dimension)
            if view: views.append(view)
        for name, prop, resource, dimension in metadata_locations(charge, binding or {}):
            view = metadata_context(src, name, prop, resource, dimension)
            if not view: continue
            # A saved diagnostic must agree with the frozen XML before the property is highlighted.
            value = view['tree'][-1]['value']
            expected = {'RealTimePosting': 'Allow', 'RegisterRecordsWritingOnPost': 'WriteModified',
                        'Balance': 'true', 'AccountingFlag': 'не задано',
                        'ExtDimensionAccountingFlag': 'не задано', 'Name': dimension}.get(prop)
            if expected is not None and value.casefold() == expected.casefold():
                views.append(view)
        result.append({'id': charge.get('id'), 'reason': charge.get('reason'), 'contexts': views[:20]})
    return {'schema_version': 1, 'charges': result}
