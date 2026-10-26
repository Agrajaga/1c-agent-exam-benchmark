"""Optional callable candidates; they do not attest an actual user entry path."""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from exam_bench.codescan import lex
from exam_bench.submission import IDENT, MD


def validate_frequency_entries(src, ou):
    """Validate callable candidates separately, leaving missing paths unassessed."""
    src = Path(src)
    entries = ou.get('frequency_entry') if isinstance(ou, dict) else None
    if entries is None:
        return {}, {}
    if not isinstance(entries, dict):
        return {}, {'frequency_entry': 'frequency_entry must be an object'}
    valid, errors = {}, {}
    for role in ('policy', 'specification'):
        if role not in entries:
            continue
        parts = entries[role].split('.') if isinstance(entries[role], str) else []
        if len(parts) != 3 or parts[0] != 'CommonModule' or not all(IDENT.fullmatch(x) for x in parts[1:]):
            errors[role] = 'Expected CommonModule.<module>.<procedure>'
            continue
        module = src / 'CommonModules' / (parts[1] + '.xml')
        code = src / 'CommonModules' / parts[1] / 'Ext' / 'Module.bsl'
        try:
            props = ET.parse(module).getroot().find(MD + 'CommonModule/' + MD + 'Properties')
            if props is None or props.findtext(MD + 'Name') != parts[1] or props.findtext(MD + 'Server') != 'true':
                raise ValueError('Common module must exist, match its name and run on the server')
            text = lex(code.read_text(encoding='utf-8-sig'))[0]
            declaration = re.search(r'(?im)^\s*(?:Процедура|Procedure)\s+' + re.escape(parts[2]) + r'\s*\(([^()]*)\)\s*(?:Экспорт|Export)\b', text)
            if not declaration:
                raise ValueError('Exported procedure not found')
            params = [p.strip() for p in declaration.group(1).split(',')]
            param = re.compile(r'^(?:(?:Знач|Val)\s+)?' + IDENT.pattern[1:-1] + r'$', re.I)
            if len(params) != 3 or not all(param.fullmatch(p) for p in params):
                raise ValueError('Exported procedure must accept exactly three parameters')
        except (OSError, ET.ParseError, ValueError) as e:
            errors[role] = str(e)
            continue
        valid[role] = entries[role]
    return valid, errors
