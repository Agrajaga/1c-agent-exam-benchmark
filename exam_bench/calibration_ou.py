"""Operational-accounting part of the calibration solution: departments, policies, batches, properties.

A small reference that the grader must accept, plus mutants that must fail the targeted operational rule.
It is not an exam reference solution.
"""
import copy
import re
import uuid
import xml.etree.ElementTree as E
from pathlib import Path

M = '{http://v8.1c.ru/8.3/MDClasses}'
V = '{http://v8.1c.ru/8.1/data/core}'
X = '{http://v8.1c.ru/8.3/xcf/readable}'
I = '{http://www.w3.org/2001/XMLSchema-instance}'


def _child(template, name, typ):
    """Copy a register child element (same object kind) with a new name, uuid and value type."""
    el = copy.deepcopy(template)
    el.set('uuid', str(uuid.uuid4()))
    props = el.find(M + 'Properties')
    props.find(M + 'Name').text = name
    syn = props.find(M + 'Synonym')
    for c in list(syn):
        syn.remove(c)
    t = props.find(M + 'Type')
    for c in list(t):
        t.remove(c)
    E.SubElement(t, V + 'Type').text = typ
    if typ == 'xs:decimal':
        nq = E.SubElement(t, V + 'NumberQualifiers')
        for k, v in (('Digits', '15'), ('FractionDigits', '2'), ('AllowedSign', 'Any')):
            E.SubElement(nq, V + k).text = v
    if typ == 'xs:string':
        sq = E.SubElement(t, V + 'StringQualifiers')
        E.SubElement(sq, V + 'Length').text = '10'; E.SubElement(sq, V + 'AllowedLength').text = 'Variable'
    if typ == 'xs:dateTime':
        dq = E.SubElement(t, V + 'DateQualifiers')
        E.SubElement(dq, V + 'DateFractions').text = 'DateTime'
    for tag in ('MinValue', 'MaxValue'):
        node = props.find(M + tag)
        if node is not None:
            for k in list(node.attrib):
                del node.attrib[k]
            node.text = None
            node.set(I + 'nil', 'true')
    return el


def build(target, n, mutant, clone, save, attribute, receipt, sale, names):
    """Add operational objects and code to the generated calibration configuration; returns (receipt, sale, ou binding)."""
    target = Path(target)
    cfg = target / 'Configuration.xml'
    props_name, policies, batches = n + 'Properties', n + 'Policies', n + 'Batches'
    text = cfg.read_text(encoding='utf-8-sig')
    for kind, name in (('Catalog', props_name), ('InformationRegister', policies), ('AccumulationRegister', batches)):
        text = text.replace('</ChildObjects>', f'<{kind}>{name}</{kind}></ChildObjects>', 1)
    cfg.write_text(text, encoding='utf-8')

    # Average-cost policy value next to the starter's FIFO / LIFO.
    enum_path = target / 'Enums' / 'УчетнаяПолитика.xml'
    enum = E.parse(enum_path).getroot()
    values = enum[0].find(M + 'ChildObjects')
    avg = copy.deepcopy(values[0]); avg.set('uuid', str(uuid.uuid4())); avg.find(M + 'Properties/' + M + 'Name').text = 'ПоСредней'
    values.append(avg); save(enum_path, enum)

    properties = clone('Catalogs', 'Валюты', props_name)
    children = properties[0].find(M + 'ChildObjects'); children.clear()
    children.append(attribute('Attribute', 'Item', 'cfg:CatalogRef.Номенклатура'))
    save(target / 'Catalogs' / (props_name + '.xml'), properties)

    reg = clone('InformationRegisters', 'КурсыВалют', policies)
    reg[0].find(M + 'Properties/' + M + 'InformationRegisterPeriodicity').text = 'Year'
    kids = reg[0].find(M + 'ChildObjects'); res, dim = kids.find(M + 'Resource'), kids.find(M + 'Dimension'); kids.clear()
    kids.append(_child(res, 'Method', 'cfg:EnumRef.УчетнаяПолитика')); kids.append(_child(dim, 'Department', 'cfg:CatalogRef.Подразделения'))
    save(target / 'InformationRegisters' / (policies + '.xml'), reg)

    acc = clone('AccumulationRegisters', 'ОстаткиНоменклатуры', batches)
    kids = acc[0].find(M + 'ChildObjects'); res, dim = kids.find(M + 'Resource'), kids.find(M + 'Dimension'); kids.clear()
    for name, typ in (('Qty', 'xs:decimal'), ('Cost', 'xs:decimal')):
        kids.append(_child(res, name, typ))
    for name, typ in (('Department', 'cfg:CatalogRef.Подразделения'), ('Item', 'cfg:CatalogRef.Номенклатура'),
                      ('Property', 'cfg:CatalogRef.' + props_name), ('Batch', 'xs:dateTime')):
        kids.append(_child(dim, name, typ))
    save(target / 'AccumulationRegisters' / (batches + '.xml'), acc)

    # Department in the receipt header and in sale rows; property in receipt rows; both post to the batches register.
    for kind, header, rows in (('receipt', ['Department'], ['Property']), ('sale', ['SaleDepartment'] if mutant == 'department_in_header' else [], [] if mutant == 'department_in_header' else ['Department'])):
        path = target / 'Documents' / (names[kind] + '.xml')
        doc = E.parse(path).getroot(); o = doc[0]
        for attr in header:
            o.find(M + 'ChildObjects').append(attribute('Attribute', attr, 'cfg:CatalogRef.' + ('Подразделения' if 'Department' in attr else props_name)))
        table = o.find(M + 'ChildObjects/' + M + 'TabularSection/' + M + 'ChildObjects')
        for attr in rows:
            table.append(attribute('Attribute', attr, 'cfg:CatalogRef.' + ('Подразделения' if attr == 'Department' else props_name)))
        E.SubElement(o.find(M + 'Properties/' + M + 'RegisterRecords'), X + 'Item', {I + 'type': 'xr:MDObjectRef'}).text = 'AccumulationRegister.' + batches
        save(path, doc)

    receipt = receipt.replace(' Для Каждого Стр Из СписокНоменклатуры Цикл', ' Если ЗначениеЗаполнено(Department) Тогда ПриходОУ(); Возврат; КонецЕсли;\n Для Каждого Стр Из СписокНоменклатуры Цикл', 1)
    receipt += f'''
Процедура ПриходОУ()
 Движения.{batches}.Записывать = Истина;
 Для Каждого Стр Из СписокНоменклатуры Цикл
  Д = Движения.{batches}.ДобавитьПриход(); Д.Период = Дата; Д.Department = Department; Д.Item = Стр.Номенклатура; Д.Property = Стр.Property;
  Д.Batch = Дата; Д.Qty = Стр.Количество; Д.Cost = Стр.Сумма;
 КонецЦикла;
КонецПроцедуры
'''
    row_department = 'SaleDepartment' if mutant == 'department_in_header' else 'Стр.Department'
    first_department = 'СписокНоменклатуры[0].Department' if mutant == 'department_first_row' else row_department
    sale = sale.replace(' Для Каждого Стр Из СписокНоменклатуры Цикл\n  Кандидаты', f' РасходОУ(Отказ); Если Отказ Тогда Возврат; КонецЕсли;\n Для Каждого Стр Из СписокНоменклатуры Цикл\n  Если ЗначениеЗаполнено({row_department}) Тогда Продолжить; КонецЕсли;\n  Кандидаты', 1)
    order = {'fifo_as_lifo': ('Убыв', 'Убыв'), 'lifo_as_fifo': ('Возр', 'Возр')}.get(mutant, ('Возр', 'Убыв'))
    average_branch = 'Ложь' if mutant == 'average_as_fifo' else 'Метод = Перечисления.УчетнаяПолитика.ПоСредней'
    policy_department = 'Неопределено' if mutant == 'policy_global' else 'Отдел'
    sale += f'''
Процедура РасходОУ(Отказ)
 Движения.{batches}.Записывать = Истина;
 Для Каждого Стр Из СписокНоменклатуры Цикл
  Отдел = {first_department};
  Если НЕ ЗначениеЗаполнено({row_department}) Тогда Продолжить; КонецЕсли;
  Отбор = Новый Структура; Если {policy_department} <> Неопределено Тогда Отбор.Вставить("Department", {policy_department}); КонецЕсли;
  Метод = РегистрыСведений.{policies}.ПолучитьПоследнее(Дата, Отбор).Method;
  Запрос = Новый Запрос("ВЫБРАТЬ Т.Batch, Т.Property, Т.QtyОстаток КАК Qty, Т.CostОстаток КАК Cost ИЗ РегистрНакопления.{batches}.Остатки(&Момент, Department = &Отдел И Item = &Товар) КАК Т ГДЕ Т.QtyОстаток > 0 УПОРЯДОЧИТЬ ПО Т.Batch " + ?(Метод = Перечисления.УчетнаяПолитика.ЛИФО, "{order[1]}", "{order[0]}"));
  Запрос.УстановитьПараметр("Момент", Новый Граница(МоментВремени(), ВидГраницы.Исключая)); Запрос.УстановитьПараметр("Отдел", Отдел); Запрос.УстановитьПараметр("Товар", Стр.Номенклатура);
  Партии = Запрос.Выполнить().Выгрузить();
  ВсегоКол = Партии.Итог("Qty"); ВсегоСт = Партии.Итог("Cost");
  Если ВсегоКол < Стр.Количество Тогда Отказ = Истина; Возврат; КонецЕсли;
  Нужно = Стр.Количество;
  Для Каждого П Из Партии Цикл
   Берем = Мин(Нужно, П.Qty); Если Берем <= 0 Тогда Прервать; КонецЕсли;
   Д = Движения.{batches}.ДобавитьРасход(); Д.Период = Дата; Д.Department = Отдел; Д.Item = Стр.Номенклатура; Д.Property = П.Property; Д.Batch = П.Batch;
   Д.Qty = Берем; Д.Cost = ?({average_branch}, Окр(ВсегоСт / ВсегоКол * Берем, 2), Окр(П.Cost / П.Qty * Берем, 2));
   Нужно = Нужно - Берем;
  КонецЦикла;
 КонецЦикла;
КонецПроцедуры
'''
    # Characteristics of properties: the starter's chart of characteristic types (string values) and a value register.
    values_name = n + 'PropertyValues'
    cfg.write_text(cfg.read_text(encoding='utf-8-sig').replace('</ChildObjects>', f'<InformationRegister>{values_name}</InformationRegister></ChildObjects>', 1), encoding='utf-8')
    reg = clone('InformationRegisters', 'КурсыВалют', values_name)
    reg[0].find(M + 'Properties/' + M + 'InformationRegisterPeriodicity').text = 'Nonperiodical'
    kids = reg[0].find(M + 'ChildObjects'); res, dim = kids.find(M + 'Resource'), kids.find(M + 'Dimension'); kids.clear()
    kids.append(_child(res, 'Value', 'xs:string'))
    kids.append(_child(dim, 'Property', 'cfg:CatalogRef.' + props_name)); kids.append(_child(dim, 'Characteristic', 'cfg:ChartOfCharacteristicTypesRef.СвойстваОбъектов'))
    save(target / 'InformationRegisters' / (values_name + '.xml'), reg)

    assembly_binding = _assembly(target, n, mutant, clone, save, attribute, batches, policies, props_name)
    if mutant == 'policy_latest':
        sale = sale.replace('ПолучитьПоследнее(Дата, Отбор)', 'ПолучитьПоследнее(Дата(3999,12,31), Отбор)')
    sale_department = 'SaleDepartment' if mutant == 'department_in_header' else 'СписокНоменклатуры.Department'
    ou = {'objects': {'departments': 'Catalog.Подразделения', 'properties': 'Catalog.' + props_name, 'policies': 'InformationRegister.' + policies,
                      'stock': 'AccumulationRegister.' + batches, 'receipt': 'Document.' + names['receipt'], 'sale': 'Document.' + names['sale']},
          'fields': {'properties': {'owner': 'Item'}, 'policies': {'department': 'Department', 'method': 'Method'},
                     'policy_values': {'fifo': 'Enum.УчетнаяПолитика.ФИФО', 'lifo': 'Enum.УчетнаяПолитика.ЛИФО', 'average': 'Enum.УчетнаяПолитика.ПоСредней'},
                     'stock': {'department': 'Department', 'item': 'Item', 'property': 'Property', 'quantity': 'Qty', 'cost': 'Cost'},
                     'receipt': {'department': 'Department', 'item': 'СписокНоменклатуры.Номенклатура', 'property': 'СписокНоменклатуры.Property',
                                 'quantity': 'СписокНоменклатуры.Количество', 'price': 'СписокНоменклатуры.Цена', 'amount': 'СписокНоменклатуры.Сумма'},
                     'sale': {'department': sale_department, 'item': 'СписокНоменклатуры.Номенклатура', 'quantity': 'СписокНоменклатуры.Количество',
                              'price': 'СписокНоменклатуры.Цена', 'amount': 'СписокНоменклатуры.Сумма'}}}
    ou['objects'].update(assembly_binding['objects']); ou['fields'].update(assembly_binding['fields'])
    ou['objects'].update(characteristics='ChartOfCharacteristicTypes.СвойстваОбъектов', property_values='InformationRegister.' + values_name)
    ou['fields']['property_values'] = {'property': 'Property', 'characteristic': 'Characteristic', 'value': 'Value'}
    return receipt, sale, ou


def _rename_table(table, doc, old, new):
    """Give a tabular section a new name with fresh generated-type ids."""
    table.set('uuid', str(uuid.uuid4()))
    for g in table.find(M + 'InternalInfo'):
        g.set('name', g.get('name').replace(f'{doc}.{old}', f'{doc}.{new}'))
        for tag in ('TypeId', 'ValueId'):
            g.find(X + tag).text = str(uuid.uuid4())
    table.find(M + 'Properties/' + M + 'Name').text = new
    for a in table.find(M + 'ChildObjects'):
        a.set('uuid', str(uuid.uuid4()))
    return table


def _assembly(target, n, mutant, clone, save, attribute, batches, policies, props_name):
    """Specification register (periodic by calendar week) and the assembly document with blocks and extra details."""
    specs, assembly = n + 'Specs', n + 'Assembly'
    cfg = target / 'Configuration.xml'
    cfg.write_text(cfg.read_text(encoding='utf-8-sig').replace('</ChildObjects>', f'<InformationRegister>{specs}</InformationRegister><Document>{assembly}</Document></ChildObjects>', 1), encoding='utf-8')
    reg = clone('InformationRegisters', 'КурсыВалют', specs)
    reg[0].find(M + 'Properties/' + M + 'InformationRegisterPeriodicity').text = 'Nonperiodical' if mutant == 'spec_nonperiodic' else 'Day'
    kids = reg[0].find(M + 'ChildObjects'); res, dim = kids.find(M + 'Resource'), kids.find(M + 'Dimension'); kids.clear()
    kids.append(_child(res, 'Qty', 'xs:decimal'))
    for name, typ in (('Block', 'cfg:CatalogRef.Номенклатура'), ('Item', 'cfg:CatalogRef.Номенклатура'), ('Property', 'cfg:CatalogRef.' + props_name)):
        kids.append(_child(dim, name, typ))
    save(target / 'InformationRegisters' / (specs + '.xml'), reg)

    doc = clone('Documents', 'РасходнаяНакладная', assembly); o = doc[0]
    children = o.find(M + 'ChildObjects')
    for attr in ('Source', 'Target'):
        children.append(attribute('Attribute', attr, 'cfg:CatalogRef.Подразделения'))
    blocks = children.find(M + 'TabularSection')
    for a in list(blocks.find(M + 'ChildObjects')):
        if a.find(M + 'Properties/' + M + 'Name').text in ('Цена', 'Сумма'):
            blocks.find(M + 'ChildObjects').remove(a)
    extras = _rename_table(copy.deepcopy(blocks), assembly, 'СписокНоменклатуры', 'Extras')
    extras.find(M + 'ChildObjects').append(attribute('Attribute', 'Property', 'cfg:CatalogRef.' + props_name))
    _rename_table(blocks, assembly, 'СписокНоменклатуры', 'Blocks')
    children.append(extras)
    records = o.find(M + 'Properties/' + M + 'RegisterRecords'); records.clear()
    E.SubElement(records, X + 'Item', {I + 'type': 'xr:MDObjectRef'}).text = 'AccumulationRegister.' + batches
    save(target / 'Documents' / (assembly + '.xml'), doc)

    need = '' if mutant == 'spec_ignored' else f'''
 Для Каждого Б Из Blocks Цикл
  Запрос = Новый Запрос("ВЫБРАТЬ С.Item, С.Property, С.Qty ИЗ РегистрСведений.{specs}.{'СрезПервых' if mutant == 'spec_first_version' else 'СрезПоследних'}(&Дата, Block = &Блок) КАК С");
  Запрос.УстановитьПараметр("Дата", Дата); Запрос.УстановитьПараметр("Блок", Б.Номенклатура);
  Для Каждого С Из Запрос.Выполнить().Выгрузить() Цикл Н = Потребность.Добавить(); Н.Item = С.Item; Н.Property = С.Property; Н.Qty = С.Qty * Б.Количество; КонецЦикла;
 КонецЦикла;'''
    extra = '' if mutant == 'extras_ignored' else '''
 Для Каждого Д Из Extras Цикл Н = Потребность.Добавить(); Н.Item = Д.Номенклатура; Н.Property = Д.Property; Н.Qty = Д.Количество; КонецЦикла;'''
    prop_filter = '' if mutant == 'property_ignored' else ' И Property = &Свойство'
    receiver = 'Source' if mutant == 'target_ignored' else 'Target'
    when = 'Дата(3999,12,31)' if mutant == 'policy_latest' else 'Дата'
    module = f'''Процедура ОбработкаПроведения(Отказ, РежимПроведения)
 {'Возврат;' if mutant == 'assembly_no_movements' else ''}
 Движения.{batches}.Записывать = Истина;
 Потребность = Новый ТаблицаЗначений; Потребность.Колонки.Добавить("Item"); Потребность.Колонки.Добавить("Property"); Потребность.Колонки.Добавить("Qty", Новый ОписаниеТипов("Число"));{need}{extra}
 Потребность.Свернуть("Item, Property", "Qty");
 Метод = РегистрыСведений.{policies}.ПолучитьПоследнее({when}, Новый Структура("Department", Source)).Method;
 Стоимость = 0;
 Для Каждого Н Из Потребность Цикл
  Запрос = Новый Запрос("ВЫБРАТЬ Т.Batch, Т.Property, Т.QtyОстаток КАК Qty, Т.CostОстаток КАК Cost ИЗ РегистрНакопления.{batches}.Остатки(&Момент, Department = &Отдел И Item = &Товар{prop_filter}) КАК Т ГДЕ Т.QtyОстаток > 0 УПОРЯДОЧИТЬ ПО Т.Batch " + ?(Метод = Перечисления.УчетнаяПолитика.ЛИФО, "Убыв", "Возр"));
  Запрос.УстановитьПараметр("Момент", Новый Граница(МоментВремени(), ВидГраницы.Исключая)); Запрос.УстановитьПараметр("Отдел", Source);
  Запрос.УстановитьПараметр("Товар", Н.Item); Запрос.УстановитьПараметр("Свойство", Н.Property);
  Партии = Запрос.Выполнить().Выгрузить(); ВсегоКол = Партии.Итог("Qty"); ВсегоСт = Партии.Итог("Cost");
  Если ВсегоКол < Н.Qty Тогда Отказ = Истина; Возврат; КонецЕсли;
  Нужно = Н.Qty;
  Для Каждого П Из Партии Цикл
   Берем = Мин(Нужно, П.Qty); Если Берем <= 0 Тогда Прервать; КонецЕсли;
   Цена = ?(Метод = Перечисления.УчетнаяПолитика.ПоСредней{' Или Истина' if mutant == 'property_ignored' else ''}, ВсегоСт / ВсегоКол, П.Cost / П.Qty);
   Д = Движения.{batches}.ДобавитьРасход(); Д.Период = Дата; Д.Department = Source; Д.Item = Н.Item; Д.Property = П.Property; Д.Batch = П.Batch;
   Д.Qty = Берем; Д.Cost = Окр(Цена * Берем, 2); Стоимость = Стоимость + Д.Cost; Нужно = Нужно - Берем;
  КонецЦикла;
 КонецЦикла;
 Блоков = Blocks.Итог("Количество");
 Для Каждого Б Из Blocks Цикл
  Д = Движения.{batches}.ДобавитьПриход(); Д.Период = Дата; Д.Department = {receiver}; Д.Item = Б.Номенклатура; Д.Batch = Дата;
  Д.Qty = Б.Количество; Д.Cost = ?(Блоков = 0, 0, Окр(Стоимость * Б.Количество / Блоков, 2));
 КонецЦикла;
КонецПроцедуры
'''
    path = target / 'Documents' / assembly / 'Ext' / 'ObjectModule.bsl'; path.parent.mkdir(parents=True); path.write_text(module, encoding='utf-8')
    if mutant == 'disassembly_doc':
        name = n + 'Разборка'
        cfg.write_text(cfg.read_text(encoding='utf-8-sig').replace('</ChildObjects>', f'<Document>{name}</Document></ChildObjects>', 1), encoding='utf-8')
        other = clone('Documents', 'ПриходнаяНакладная', name); other[0].find(M + 'Properties/' + M + 'RegisterRecords').clear()
        save(target / 'Documents' / (name + '.xml'), other)
    return {'objects': {'specification': 'InformationRegister.' + specs, 'assembly': 'Document.' + assembly},
            'fields': {'specification': {'block': 'Block', 'item': 'Item', 'property': 'Property', 'quantity': 'Qty'},
                       'assembly': {'source': 'Source', 'target': 'Target', 'block': 'Blocks.Номенклатура', 'block_quantity': 'Blocks.Количество',
                                    'extra_item': 'Extras.Номенклатура', 'extra_property': 'Extras.Property', 'extra_quantity': 'Extras.Количество'}}}


STATEMENT_QUERY = '''ВЫБРАТЬ Т.Item КАК Товар, ЗС.Value КАК Характеристика,
 СУММА(Т.CostНачальныйОстаток) КАК НачОст, СУММА(Т.CostПриход) КАК Приход, СУММА(Т.CostРасход) КАК Расход, СУММА(Т.CostКонечныйОстаток) КАК КонОст,
 СУММА(Т.QtyНачальныйОстаток) КАК НачОстКол, СУММА(Т.QtyПриход) КАК ПриходКол, СУММА(Т.QtyРасход) КАК РасходКол, СУММА(Т.QtyКонечныйОстаток) КАК КонОстКол
ИЗ РегистрНакопления.@BATCHES@.ОстаткиИОбороты(&НачалоПериода, &КонецПериода, , , Department = &Подразделение) КАК Т
 ЛЕВОЕ СОЕДИНЕНИЕ РегистрСведений.@VALUES@ КАК ЗС ПО ЗС.Property = Т.Property
СГРУППИРОВАТЬ ПО Т.Item, ЗС.Value'''
STATEMENT_FIELDS = {'item': 'Товар', 'characteristic': 'Характеристика', 'opening': 'НачОст', 'receipt': 'Приход', 'expense': 'Расход', 'closing': 'КонОст',
                    'opening_qty': 'НачОстКол', 'receipt_qty': 'ПриходКол', 'expense_qty': 'РасходКол', 'closing_qty': 'КонОстКол'}
SALES_QUERY = '''ВЫБРАТЬ Об.Номенклатура КАК Номенклатура, СУММА(Об.Количество) КАК Количество, СУММА(Об.Себестоимость) КАК Себестоимость,
 СУММА(Об.Продажа) КАК Продажа, СУММА(Об.Продажа) - СУММА(Об.Себестоимость) КАК Прибыль
ИЗ (ВЫБРАТЬ Т.Item КАК Номенклатура, Т.Qty КАК Количество, Т.Cost КАК Себестоимость, 0 КАК Продажа
 ИЗ РегистрНакопления.@BATCHES@ КАК Т
 ГДЕ Т.ВидДвижения = ЗНАЧЕНИЕ(ВидДвиженияНакопления.Расход) И Т.Регистратор ССЫЛКА Документ.@SALE@ И Т.Период МЕЖДУ &НачалоПериода И &КонецПериода
 ОБЪЕДИНИТЬ ВСЕ
 ВЫБРАТЬ С.Номенклатура, 0, 0, С.Сумма
 ИЗ Документ.@SALE@.СписокНоменклатуры КАК С
 ГДЕ С.Ссылка.Проведен И С.Ссылка.Дата МЕЖДУ &НачалоПериода И &КонецПериода И С.@DEPARTMENT@ <> ЗНАЧЕНИЕ(Справочник.Подразделения.ПустаяСсылка)) КАК Об
СГРУППИРОВАТЬ ПО Об.Номенклатура'''
SALES_FIELDS = {'item': 'Номенклатура', 'quantity': 'Количество', 'cost': 'Себестоимость', 'revenue': 'Продажа', 'profit': 'Прибыль'}
DEPARTMENT_TYPE = '<v8:Type>cfg:CatalogRef.Подразделения</v8:Type>'


def reports(target, n, variant, mutant, names):
    """Statement by department grouped by characteristic value and item; sales with profit. Same variant split as the BU report."""
    from .calibration import make_report
    statement = STATEMENT_QUERY.replace('@BATCHES@', n + 'Batches').replace('@VALUES@', n + 'PropertyValues')
    if mutant == 'statement_ignores_department':
        statement = statement.replace('Department = &Подразделение', '(Department = &Подразделение ИЛИ ИСТИНА)')
    if mutant == 'statement_without_characteristics':
        statement = statement.replace('ЗС.Value КАК Характеристика', 'ВЫРАЗИТЬ("" КАК СТРОКА(10)) КАК Характеристика').replace(', ЗС.Value', '')
    sales = SALES_QUERY.replace('@BATCHES@', n + 'Batches').replace('@SALE@', names['sale'])
    sales = sales.replace('С.@DEPARTMENT@', 'С.Ссылка.SaleDepartment' if mutant == 'department_in_header' else 'С.Department')
    if mutant == 'ou_sales_profit_wrong':
        sales = sales.replace('СУММА(Об.Продажа) - СУММА(Об.Себестоимость) КАК Прибыль', 'СУММА(Об.Продажа) КАК Прибыль')
    return {'ou_statement': make_report(target, n + 'Statement', variant, statement, STATEMENT_FIELDS, ['Характеристика', 'Товар'],
                                        [c for k, c in STATEMENT_FIELDS.items() if k not in ('item', 'characteristic')],
                                        [('department', 'Подразделение', DEPARTMENT_TYPE)]),
            'ou_sales': make_report(target, n + 'OUSales', variant, sales, SALES_FIELDS, ['Номенклатура'], ['Количество', 'Себестоимость', 'Продажа', 'Прибыль'])}
