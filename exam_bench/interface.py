"""General requirements (ticket section Б1): sections of the command interface, read from the exported sources.

The solver names the subsystem of each ticket section in binding["interface"]. The objects of a section are the ones
the solver already declared for it (binding.ou, the accounting bindings, binding.pr and their reports), so the stand
does not guess which object belongs where. Static: the rendered interface is not opened.
"""
import re
from pathlib import Path

from .ou import IDENT

SECTIONS = {'ou': 'оперативный учёт', 'bu': 'бухгалтерский учёт', 'pr': 'периодические расчёты'}
CASES = {}
RULES = {'G01': 'a top-level section of the command interface for each section of the ticket; section objects in it',
         'G02': 'every declared object of a section, registers included, is reachable from its section',
         'G03': 'commands grouped by kind: catalogs, documents, other objects are not mixed in one group'}
KIND = {'Catalog': 'catalogs', 'Document': 'documents'}
# Kinds examiners place differently: a chart of characteristic types may stand with catalogs or with other
# objects (Q10). They are not judged, so they never make a group mixed.
NEUTRAL = {'ChartOfCharacteristicTypes'}


def check(src, interface):
    if not isinstance(interface, dict) or not isinstance(interface.get('sections'), dict):
        raise ValueError('binding.interface.sections maps ou, bu, pr to Subsystem.<name>')
    for key, ref in interface['sections'].items():
        if key not in SECTIONS or not re.fullmatch(r'Subsystem\.\w+(\.Subsystem\.\w+)*', str(ref)):
            raise ValueError('binding.interface.sections.%s must be Subsystem.<name>' % key)
        if not subsystem_path(src, ref).is_file():
            raise ValueError('Metadata object absent: ' + ref)
    return True


def subsystem_path(src, ref):
    names = ref.split('.')[1::2]
    path = Path(src) / 'Subsystems'
    for n in names[:-1]:
        path = path / n / 'Subsystems'
    return path / (names[-1] + '.xml')


def section_objects(binding):
    """Objects the solver declared for each section of the ticket."""
    reports = binding.get('reports') or {}
    out = {}
    objects = binding.get('objects') or {}
    bu = [v for k, v in objects.items() if k in ('items', 'warehouses', 'receipt', 'sale', 'manual', 'ledger', 'accounts')]
    analogs = (binding.get('analogs') or {}).get('object')
    out['bu'] = bu + ([analogs] if analogs else []) + [r['object'] for k, r in reports.items() if k.startswith('bu_')]
    if binding.get('ou'):
        out['ou'] = list((binding['ou'].get('objects') or {}).values()) + [r['object'] for k, r in reports.items() if k.startswith('ou_')]
    if binding.get('pr'):
        pr = binding['pr']
        charts = sorted({'.'.join(v.split('.')[:2]) for v in (pr.get('calc_types') or {}).values()})
        out['pr'] = (list((pr.get('objects') or {}).values()) + [r['register'] for r in pr.get('results') or []] + charts
                     + [r['object'] for k, r in reports.items() if k.startswith('pr_')])
    return {k: sorted({o for o in v if isinstance(o, str) and re.fullmatch(r'\w+\.\w+', o)}) for k, v in out.items()}


def read_subsystem(src, ref):
    """Content (with nested subsystems), command-interface flag, hidden and grouped commands of a subsystem."""
    path = subsystem_path(src, ref)
    text = path.read_text(encoding='utf-8-sig')
    include = re.search(r'<IncludeInCommandInterface>(\w+)<', text)
    content = set(re.findall(r'<xr:Item xsi:type="xr:MDObjectRef">([^<]+)</xr:Item>', text))
    for child in re.findall(r'<Subsystem>(\w+)</Subsystem>', text):
        nested = read_subsystem(src, ref + '.Subsystem.' + child)
        content |= nested['content']
    ci = path.parent / path.stem / 'Ext' / 'CommandInterface.xml'
    hidden, groups = set(), {}
    if ci.is_file():
        ci_text = ci.read_text(encoding='utf-8-sig')
        visibility = re.search(r'<CommandsVisibility>(.*?)</CommandsVisibility>', ci_text, re.S)
        for name, body in re.findall(r'<Command name="([^"]+)">(.*?)</Command>', visibility.group(1) if visibility else '', re.S):
            if re.search(r'<xr:Common>false</xr:Common>', body):
                hidden.add('.'.join(name.split('.')[:2]))
        placement = re.search(r'<CommandsPlacement>(.*?)</CommandsPlacement>', ci_text, re.S)
        for name, body in re.findall(r'<Command name="([^"]+)">(.*?)</Command>', placement.group(1) if placement else '', re.S):
            # Standard groups (NavigationPanelOrdinary, ...) and the empty id are laid out by the platform, which
            # shows commands under headings by object type; only the solver's own command groups can mix kinds.
            g = re.search(r'<CommandGroup>(CommandGroup\.\w+)</CommandGroup>', body)
            if g:
                groups.setdefault(g.group(1), set()).add('.'.join(name.split('.')[:2]))
    return {'include': include is not None and include.group(1) == 'true', 'content': content, 'hidden': hidden, 'groups': groups}


def standard_commands(src, ref):
    """False when the object has its standard commands switched off (no list command in the interface)."""
    from .submission import GROUPS
    kind, name = ref.split('.')
    folder = GROUPS.get(kind) or {'DataProcessor': 'DataProcessors', 'ChartOfCalculationTypes': 'ChartsOfCalculationTypes'}.get(kind)
    path = Path(src) / folder / (name + '.xml') if folder else None
    if not path or not path.is_file():
        return True
    m = re.search(r'<UseStandardCommands>(\w+)<', path.read_text(encoding='utf-8-sig'))
    return not m or m.group(1) == 'true'


def static_signs(src, binding):
    interface = binding.get('interface') or {}
    top = set(re.findall(r'<Subsystem>(\w+)</Subsystem>', (Path(src) / 'Configuration.xml').read_text(encoding='utf-8-sig')))
    sections = {}
    for key, ref in (interface.get('sections') or {}).items():
        s = read_subsystem(src, ref)
        s['top_level'] = ref.count('.') == 1 and ref.split('.')[1] in top
        s['ref'] = ref
        sections[key] = s
    objects = section_objects(binding)
    no_commands = sorted({o for v in objects.values() for o in v if not standard_commands(src, o)})
    return {'sections': sections, 'objects': objects, 'no_commands': no_commands}


def compare(observations, binding, static=None):
    static = static or {}
    why = []
    sections, objects = static.get('sections') or {}, static.get('objects') or {}

    def judged():
        missing = [k for k in objects if k not in sections]
        if missing:
            raise ValueError('interface.sections does not name a subsystem for ' + ', '.join(missing))
        return {k: sections[k] for k in objects}

    def g01():
        s = judged()
        ok = True
        if len({v['ref'] for v in s.values()}) < len(s):
            why.append('several ticket sections share one subsystem: %s' % {k: v['ref'] for k, v in s.items()})
            ok = False
        for k, v in s.items():
            if not v['top_level'] or not v['include']:
                why.append('%s: %s is not a top-level section of the command interface' % (k, v['ref']))
                ok = False
        own = {k: set(objects[k]) - {o for kk, oo in objects.items() if kk != k for o in oo} for k in s}
        for k, v in s.items():
            absent = sorted(own[k] - v['content'])
            if absent:
                why.append('%s: objects of the section outside %s: %s' % (k, v['ref'], ', '.join(absent)))
                ok = False
        return ok

    def g02():
        s = judged()
        ok = True
        for k, v in s.items():
            absent = sorted(set(objects[k]) - v['content'])
            hidden = sorted(set(objects[k]) & v['hidden'])
            off = sorted(set(objects[k]) & set(static.get('no_commands') or []))
            for label, items in (('not in the section', absent), ('hidden in the section', hidden), ('without standard commands', off)):
                if items:
                    why.append('%s %s: %s' % (k, label, ', '.join(items)))
                    ok = False
        return ok

    def g03():
        s = judged()
        ok = True
        for k, v in s.items():
            for group, items in v['groups'].items():
                kinds = {KIND.get(o.split('.')[0], 'other') for o in items if o.split('.')[0] not in NEUTRAL}
                if len(kinds) > 1:
                    why.append('%s: group %s mixes %s' % (k, group, ', '.join(sorted(items))))
                    ok = False
        return ok

    out = []
    for rule, check_ in (('G01', g01), ('G02', g02), ('G03', g03)):
        why.clear()
        try:
            verdict = 'pass' if check_() else 'fail'
            reason = '; '.join(why)[:600] if verdict == 'fail' and why else None
        except (KeyError, TypeError, ValueError) as exc:
            verdict, reason = 'inconclusive', 'Required observations unavailable: ' + str(exc)[:200]
        out.append({'id': rule, 'verdict': verdict, 'reason': reason, 'coverage': 'static_sources', 'assertion_id': rule + '.static_sources'})
    return out
