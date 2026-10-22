"""Rewrites of calculation register record sets after calculation (М7.14, owner decision A15).

The examiner's reading (П. С. Белоусов, webinar «Расчеты», 2:06:31–2:09:44 and 2:31:52–2:33:19): the first write of the
movements fills both the main table and the actual action period table, as it must. After the results are
calculated, the set is written again; only resources and attributes of the main table changed, so the second write
must not rebuild the actual action period: Записать(, Истина) (ТолькоЗапись) or Записать(, , Ложь)
(ЗаписьФактическогоПериодаДействия). A plain Записать() of a register with an action period after calculation
rebuilds the table for nothing.

rewrites(src) -> [(file, line, target, statement)]: plain writes of a set of a register with an action period (or of
all movements) that follow a calculation (an assignment of «.Результат», directly or in a called method) and a
previous write (earlier in the method, or before the call in a caller).
"""
import re
from pathlib import Path

from .codescan import IDENT, lex

WORD = r'(?<![\wЁё])'
END = r'(?![\wЁё])'


def action_period_registers(src):
    src = Path(src)
    return sorted(p.stem for p in src.glob('CalculationRegisters/*.xml')
                  if re.search(r'<ActionPeriod>true</ActionPeriod>', p.read_text(encoding='utf-8-sig', errors='replace')))


def methods(src):
    """{name: [(file, offset of the body in the file's code, body)]}: every procedure and function of the solution."""
    src, out = Path(src), {}
    for path in sorted(src.rglob('*.bsl')):
        if 'BenchmarkObserver' in path.parts:
            continue
        code = lex(path.read_text(encoding='utf-8-sig', errors='replace'))[0]
        for m in re.finditer(r'(?:Процедура|Функция)\s+(' + IDENT + r')\s*\(.*?(?:КонецПроцедуры|КонецФункции)', code, re.S | re.I):
            out.setdefault(m.group(1), []).append((path, code, m.start(), m.group(0)))
    return out


def arguments(text):
    parts, depth, cur = [], 0, ''
    for ch in text:
        if ch == ',' and depth == 0:
            parts.append(cur.strip()); cur = ''
            continue
        depth += ch == '('
        depth -= ch == ')'
        cur += ch
    return parts + [cur.strip()]


def calls(body, names):
    return [(m.start(), m.group(1)) for m in re.finditer(WORD + r'(?<!Процедура )(?<!Функция )(' + IDENT + r')\s*\(', body, re.I) if m.group(1) in names]


WRITE = re.compile(r'(' + IDENT + r'(?:\.' + IDENT + r')*)\.Записать\(([^()]*(?:\([^()]*\)[^()]*)*)\)')
CALC = re.compile(r'\.\s*Результат\s*=[^=]')


def writes(body):
    """Writes of record sets in a method body: of movements, a set variable or a set kept in a collection."""
    return [m for m in WRITE.finditer(body) if m.group(1).split('.')[-1] == 'Движения' or 'Движения.' in m.group(1)
            or re.match(IDENT + r'(\.Значение)?$', m.group(1))]


def entered_after_write(table):
    """Methods entered after a write: a caller wrote before calling them, or was itself entered after a write."""
    names = set(table)
    after = set()
    changed = True
    while changed:
        changed = False
        for n, defs in table.items():
            for *_, body in defs:
                first = min([m.start() for m in writes(body)] or [len(body)])
                for pos, callee in calls(body, names):
                    if callee not in after and (n in after or first < pos) and callee != n:
                        after.add(callee); changed = True
    return after


BASE = re.compile(r'РегистрРасчета\.' + IDENT + r'\.База' + IDENT + r'\s*\((?:[^()]|\([^()]*\))*Регистратор|\.ПолучитьБазу\s*\(')


def base_before_write(src):
    """М7.13: the base of the records being calculated, read before they are written (the base virtual table filtered
    by the registrar, or ПолучитьБазу): the platform builds it from written records, so the base comes out empty.
    [(file, line, text)] in posting code (documents and common modules)."""
    src = Path(src)
    if not list(src.glob('CalculationRegisters/*.xml')):
        return []
    table = {n: [d for d in defs if d[0].parts[-4] in ('Documents', 'CommonModules')] for n, defs in methods(src).items()}
    table = {n: defs for n, defs in table.items() if defs}
    after = entered_after_write(table)
    out = []
    for name, defs in table.items():
        if name in after:
            continue
        for path, code, start, body in defs:
            raw = path.read_text(encoding='utf-8-sig', errors='replace')[start:start + len(body)]
            first = min([m.start() for m in writes(body)] or [len(body)])
            for m in BASE.finditer(raw):
                if m.start() < first:
                    line = code.count('\n', 0, start + m.start()) + 1
                    out.append((path.relative_to(src).as_posix(), line, raw[m.start():m.start() + 80].split('\n')[0]))
    return out


def rewrites(src):
    registers = action_period_registers(src)
    if not registers:
        return []
    table = methods(src)
    names = set(table)

    # Methods that calculate results: assign «.Результат» or call such a method.
    calculating = {n for n, defs in table.items() if any(CALC.search(b) for *_, b in defs)}
    changed = True
    while changed:
        changed = False
        for n, defs in table.items():
            if n not in calculating and any(c in calculating for *_, b in defs for _, c in calls(b, names)):
                calculating.add(n); changed = True
    after_write = entered_after_write(table)

    out = []
    for name, defs in table.items():
        for path, code, start, body in defs:
            for m in writes(body):
                prefix = body[:m.start()]
                calc = [x.start() for x in CALC.finditer(prefix)] + [p for p, c in calls(prefix, names) if c in calculating]
                if not calc:
                    continue
                earlier = [w.start() for w in writes(prefix) if w.start() < min(calc)]
                if not (earlier or name in after_write):
                    continue
                target = resolve(m.group(1), prefix, registers) or passed(m.group(1), body, name, table, registers) \
                    or created(m.group(1), code, registers)
                if not target:
                    continue
                args = arguments(m.group(2))
                only_write = len(args) > 1 and args[1] != '' and args[1].upper() != 'ЛОЖЬ'
                no_actual = len(args) > 2 and args[2].upper() == 'ЛОЖЬ'
                if only_write or no_actual:
                    continue
                line = code.count('\n', 0, start + m.start()) + 1
                out.append((path.relative_to(src).as_posix(), line, target, m.group(0)))
    return out


def resolve(expr, prefix, registers):
    """The register a written expression stands for: a register name, «все движения», or None when unknown."""
    tail = expr.split('.')
    if tail[-1] == 'Движения':
        return 'все движения'
    if len(tail) >= 2 and tail[-2] == 'Движения':
        return tail[-1] if tail[-1] in registers else None
    assigned = list(re.finditer(WORD + re.escape(expr) + r'\s*=\s*([^;]+);', prefix))
    if assigned:
        rhs = assigned[-1].group(1)
        m = re.search(r'Движения\.(' + IDENT + ')' + END, rhs) or re.search(r'РегистрыРасчета\.(' + IDENT + r')\.СоздатьНаборЗаписей', rhs)
        return m.group(1) if m and m.group(1) in registers else None
    named = [r for r in registers if r in expr]
    return named[0] if len(named) == 1 else None


def parameters(body):
    m = re.match(r'(?:Процедура|Функция)\s+' + IDENT + r'\s*\(([^)]*)\)', body, re.I)
    return [re.sub(r'^Знач\s+', '', p.split('=')[0].strip(), flags=re.I) for p in m.group(1).split(',')] if m else []


def passed(expr, body, name, table, registers):
    """A parameter of the method: the register of the movements every caller passes in its place."""
    if expr not in parameters(body):
        return None
    index = parameters(body).index(expr)
    found = set()
    for defs in table.values():
        for *_, caller in defs:
            for m in re.finditer(r'(?<![\wЁё])(?<!Процедура )(?<!Функция )' + re.escape(name) + r'\s*\(([^;]*?)\)\s*;', caller):
                args = arguments(m.group(1))
                if index < len(args):
                    r = re.search(r'Движения\.(' + IDENT + ')$', args[index])
                    found.add(r.group(1) if r else None)
    return found.pop() if len(found) == 1 and None not in found and next(iter(found)) in registers else None


def created(expr, code, registers):
    """A set kept in a collection: the one register with an action period whose sets the module creates."""
    if not re.match(IDENT + r'\.Значение$', expr):
        return None
    made = {r for r in re.findall(r'РегистрыРасчета\.(' + IDENT + r')\.СоздатьНаборЗаписей', code) if r in registers}
    return made.pop() if len(made) == 1 else None
