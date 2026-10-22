"""Command-interface part of the calibration solution: one subsystem per ticket section.

Variant one leaves command placement to the platform; variant two puts commands into its own groups
«Справочники», «Документы», «Прочие» (Б1.1.3). Built last, from the bindings of the other sections.
"""
import uuid
from pathlib import Path

from .interface import section_objects

NS = ('xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" '
      'xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.17"')
CI = ('xmlns="http://v8.1c.ru/8.3/xcf/extrnprops" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xs="http://www.w3.org/2001/XMLSchema" '
      'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.17"')
NAMES = {'ou': 'ОперативныйУчет', 'bu': 'БухгалтерскийУчет', 'pr': 'ПериодическиеРасчеты'}
GROUPS = {'catalogs': 'Справочники', 'documents': 'Документы', 'other': 'Прочие'}


def command(ref):
    kind = ref.split('.')[0]
    return ref + ('.StandardCommand.Open' if kind in ('Report', 'DataProcessor') else '.StandardCommand.OpenList')


def build(target, n, variant, mutant, binding):
    target = Path(target)
    objects = section_objects(binding)
    sections = {'Учет': sorted({o for v in objects.values() for o in v})} if mutant == 'interface_one_section' else {NAMES[k]: v for k, v in objects.items()}
    groups = variant != 'one' or mutant == 'mixed_group'
    cfg = target / 'Configuration.xml'
    text = cfg.read_text(encoding='utf-8-sig')
    added = ''.join(f'<Subsystem>{name}</Subsystem>' for name in sections)
    if groups:
        added += ''.join(f'<CommandGroup>{g}</CommandGroup>' for g in list(GROUPS.values()) + (['Разное'] if mutant == 'mixed_group' else []))
    cfg.write_text(text.replace('</ChildObjects>', added + '</ChildObjects>', 1), encoding='utf-8')
    (target / 'Subsystems').mkdir(exist_ok=True)
    if groups:
        (target / 'CommandGroups').mkdir(exist_ok=True)
        for g in list(GROUPS.values()) + (['Разное'] if mutant == 'mixed_group' else []):
            (target / 'CommandGroups' / (g + '.xml')).write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject {NS}><CommandGroup uuid="{uuid.uuid4()}"><Properties><Name>{g}</Name><Synonym/><Comment/><Representation>Auto</Representation><ToolTip/><Picture/><Category>NavigationPanel</Category></Properties></CommandGroup></MetaDataObject>
''', encoding='utf-8')
    for name, content in sections.items():
        items = ''.join(f'<xr:Item xsi:type="xr:MDObjectRef">{o}</xr:Item>' for o in content)
        (target / 'Subsystems' / (name + '.xml')).write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject {NS}><Subsystem uuid="{uuid.uuid4()}"><Properties><Name>{name}</Name><Synonym/><Comment/><IncludeHelpInContents>true</IncludeHelpInContents>
<IncludeInCommandInterface>true</IncludeInCommandInterface><UseOneCommand>false</UseOneCommand><Explanation/><Picture/><Content>{items}</Content></Properties><ChildObjects/></Subsystem></MetaDataObject>
''', encoding='utf-8')
        hidden = [o for o in content if mutant == 'register_hidden' and name == NAMES['ou'] and o == binding['ou']['objects']['stock']]
        placement = []
        if groups:
            for o in content:
                if o.split('.')[0] in ('Report', 'DataProcessor'):
                    continue  # a report without a schema or form has no standard open command to place
                kind = {'Catalog': 'catalogs', 'Document': 'documents'}.get(o.split('.')[0], 'other')
                group = 'Разное' if mutant == 'mixed_group' and name == NAMES['bu'] and kind in ('catalogs', 'documents') else GROUPS[kind]
                placement.append((command(o), group))
        if hidden or placement:
            visibility = ''.join(f'<Command name="{command(o)}"><Visibility><xr:Common>false</xr:Common></Visibility></Command>' for o in hidden)
            places = ''.join(f'<Command name="{c}"><CommandGroup>CommandGroup.{g}</CommandGroup><Placement>Auto</Placement></Command>' for c, g in placement)
            ci = target / 'Subsystems' / name / 'Ext' / 'CommandInterface.xml'
            ci.parent.mkdir(parents=True, exist_ok=True)
            ci.write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<CommandInterface {CI}>{'<CommandsVisibility>' + visibility + '</CommandsVisibility>' if visibility else ''}{'<CommandsPlacement>' + places + '</CommandsPlacement>' if places else ''}</CommandInterface>
''', encoding='utf-8')
    if mutant == 'interface_one_section':
        return {'sections': {k: 'Subsystem.Учет' for k in objects}}
    return {'sections': {k: 'Subsystem.' + NAMES[k] for k in objects}}
