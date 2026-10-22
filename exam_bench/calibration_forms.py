"""Managed-forms part of the calibration solution: manager of a counterparty and its additional information.

Variant one keeps values in a tabular section of the counterparty, variant two in an information register.
The counterparty main form builds input fields for the kinds listed at the selected manager.
"""
import copy
import uuid
import xml.etree.ElementTree as E
from pathlib import Path

from .calibration_ou import M, X, _child

FORM_META = '''<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:app="http://v8.1c.ru/8.2/managed-application/core" version="2.17">
 <Form uuid="{uuid}"><Properties><Name>Форма</Name><Synonym/><Comment/><FormType>Managed</FormType><IncludeHelpInContents>false</IncludeHelpInContents>
 <UsePurposes><v8:Value xsi:type="app:ApplicationUsePurpose">PlatformApplication</v8:Value></UsePurposes></Properties></Form>
</MetaDataObject>
'''
FORM = '''<?xml version="1.0" encoding="UTF-8"?>
<Form xmlns="http://v8.1c.ru/8.3/xcf/logform" xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.17">
 <UseForFoldersAndItems>Items</UseForFoldersAndItems>
 <AutoCommandBar name="КоманднаяПанель" id="-1"/>
 <Events><Event name="OnCreateAtServer">ПриСозданииНаСервере</Event><Event name="BeforeWriteAtServer">ПередЗаписьюНаСервере</Event>{after_write}</Events>
 <ChildItems>
  <InputField name="Наименование" id="2"><DataPath>Объект.Description</DataPath><ContextMenu name="НаименованиеКонтекстноеМеню" id="6"/><ExtendedTooltip name="НаименованиеРасширеннаяПодсказка" id="7"/></InputField>
  {manager_field}
 </ChildItems>
 <Attributes>
  <Attribute name="Объект" id="1"><Type><v8:Type>cfg:CatalogObject.Контрагенты</v8:Type></Type><MainAttribute>true</MainAttribute></Attribute>
  <Attribute name="ПоляМенеджера" id="100"><Type><v8:Type>cfg:CatalogRef.ФизическиеЛица</v8:Type></Type></Attribute>
 </Attributes>
</Form>
'''
MANAGER_FIELD = ('<InputField name="Менеджер" id="3"><DataPath>Объект.Менеджер</DataPath><ContextMenu name="МенеджерКонтекстноеМеню" id="8"/>'
                 '<ExtendedTooltip name="МенеджерРасширеннаяПодсказка" id="9"/><Events><Event name="OnChange">МенеджерПриИзменении</Event></Events></InputField>')


def _table(template, catalog, name, attributes):
    """A catalog tabular section built from a document tabular section of the starter."""
    t = copy.deepcopy(template)
    t.set('uuid', str(uuid.uuid4()))
    info = t.find(M + 'InternalInfo')
    for g, kind in zip(info, ('TabularSection', 'TabularSectionRow')):
        g.set('name', f'Catalog{kind}.{catalog}.{name}')
        for tag in ('TypeId', 'ValueId'):
            g.find(X + tag).text = str(uuid.uuid4())
    props = t.find(M + 'Properties')
    props.find(M + 'Name').text = name
    use = E.Element(M + 'Use'); use.text = 'ForItem'
    props.insert(list(props).index(props.find(M + 'StandardAttributes')) + 1, use)
    children = t.find(M + 'ChildObjects'); children.clear()
    for a in attributes:
        children.append(a)
    return t


def build(target, n, variant, mutant, clone, save, attribute):
    """Add the manager, lists and the counterparty form; returns the forms binding."""
    target = Path(target)
    template = E.parse(target / 'Documents' / 'РасходнаяНакладная.xml').getroot()[0].find(M + 'ChildObjects/' + M + 'TabularSection')
    kind = 'xs:string' if mutant == 'list_not_chart' else 'cfg:ChartOfCharacteristicTypesRef.СвойстваОбъектов'

    def string_attribute(name):
        a = attribute('Attribute', name, 'xs:string')
        return a

    people = target / 'Catalogs' / 'ФизическиеЛица.xml'
    doc = E.parse(people).getroot(); children = doc[0].find(M + 'ChildObjects')
    children.append(_table(template, 'ФизическиеЛица', 'Сведения', [attribute('Attribute', 'Свойство', kind)]))
    save(people, doc)
    if mutant == 'list_truncated':
        module = target / 'Catalogs' / 'ФизическиеЛица' / 'Ext' / 'ObjectModule.bsl'
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text('Процедура ПередЗаписью(Отказ)\n Пока Сведения.Количество() > 1 Цикл Сведения.Удалить(1); КонецЦикла;\nКонецПроцедуры\n', encoding='utf-8')

    path = target / 'Catalogs' / 'Контрагенты.xml'
    doc = E.parse(path).getroot(); o = doc[0]; children = o.find(M + 'ChildObjects')
    children.append(attribute('Attribute', 'Менеджер', 'cfg:CatalogRef.ФизическиеЛица'))
    if variant == 'one':
        children.append(_table(template, 'Контрагенты', 'Сведения', [attribute('Attribute', 'Свойство', 'cfg:ChartOfCharacteristicTypesRef.СвойстваОбъектов'),
                                                                     string_attribute('Значение')]))
    E.SubElement(children, M + 'Form').text = 'Форма'
    o.find(M + 'Properties/' + M + 'DefaultObjectForm').text = 'Catalog.Контрагенты.Form.Форма'
    save(path, doc)

    values = None
    if variant != 'one':
        values = n + 'CounterpartyInfo'
        cfg = target / 'Configuration.xml'
        cfg.write_text(cfg.read_text(encoding='utf-8-sig').replace('</ChildObjects>', f'<InformationRegister>{values}</InformationRegister></ChildObjects>', 1), encoding='utf-8')
        reg = clone('InformationRegisters', 'КурсыВалют', values)
        reg[0].find(M + 'Properties/' + M + 'InformationRegisterPeriodicity').text = 'Nonperiodical'
        kids = reg[0].find(M + 'ChildObjects'); res, dim = kids.find(M + 'Resource'), kids.find(M + 'Dimension'); kids.clear()
        kids.append(_child(res, 'Значение', 'xs:string'))
        kids.append(_child(dim, 'Контрагент', 'cfg:CatalogRef.Контрагенты')); kids.append(_child(dim, 'Свойство', 'cfg:ChartOfCharacteristicTypesRef.СвойстваОбъектов'))
        save(target / 'InformationRegisters' / (values + '.xml'), reg)

    forms = target / 'Catalogs' / 'Контрагенты' / 'Forms'
    (forms / 'Форма' / 'Ext' / 'Form').mkdir(parents=True)
    (forms / 'Форма.xml').write_text(FORM_META.replace('{uuid}', str(uuid.uuid4())), encoding='utf-8')
    (forms / 'Форма' / 'Ext' / 'Form.xml').write_text(FORM.replace('{manager_field}', '' if mutant == 'form_no_manager' else MANAGER_FIELD)
                                                       .replace('{after_write}', '' if variant == 'one' else '<Event name="OnWriteAtServer">ПриЗаписиНаСервере</Event>'), encoding='utf-8')
    (forms / 'Форма' / 'Ext' / 'Form' / 'Module.bsl').write_text(form_module(variant, mutant, values), encoding='utf-8')

    binding = {'objects': {'counterparties': 'Catalog.Контрагенты', 'managers': 'Catalog.ФизическиеЛица', 'characteristics': 'ChartOfCharacteristicTypes.СвойстваОбъектов'},
               'form': 'Catalog.Контрагенты.Form.Форма',
               'fields': {'counterparties': {'manager': 'Менеджер'}, 'managers': {'list': 'Сведения.Свойство'}}}
    binding['values'] = ({'kind': 'table', 'characteristic': 'Сведения.Свойство', 'value': 'Сведения.Значение'} if variant == 'one' else
                         {'kind': 'register', 'register': 'InformationRegister.' + values, 'counterparty': 'Контрагент', 'characteristic': 'Свойство', 'value': 'Значение'})
    return binding


def form_module(variant, mutant, values):
    kinds = ('ВЫБРАТЬ Р.Ссылка КАК Свойство ИЗ ПланВидовХарактеристик.СвойстваОбъектов КАК Р' if mutant == 'fields_all' else
             'ВЫБРАТЬ Т.Свойство КАК Свойство ИЗ Справочник.ФизическиеЛица.Сведения КАК Т ГДЕ Т.Ссылка = &Менеджер УПОРЯДОЧИТЬ ПО Т.НомерСтроки')
    if variant == 'one':
        read = ' С = Объект.Сведения.НайтиСтроки(Новый Структура("Свойство", Свойство)); Возврат ?(С.Количество() = 0, "", С[0].Значение);'
        save_value = (' С = ТекущийОбъект.Сведения.НайтиСтроки(Новый Структура("Свойство", Свойство));\n'
                      ' Строка_ = ?(С.Количество() = 0, ТекущийОбъект.Сведения.Добавить(), С[0]); Строка_.Свойство = Свойство; Строка_.Значение = Значение;')
    else:
        read = (f' Если Объект.Ссылка.Пустая() Тогда Возврат ""; КонецЕсли;\n'
                f' Возврат РегистрыСведений.{values}.Получить(Новый Структура("Контрагент, Свойство", Объект.Ссылка, Свойство)).Значение;')
        save_value = ' Значения.Вставить(Свойство, Значение);'
    after = '' if variant == 'one' else f'''
&НаСервере
Процедура ПриЗаписиНаСервере(Отказ, ТекущийОбъект, ПараметрыЗаписи)
 Для Каждого КЗ Из Значения Цикл
  МЗ = РегистрыСведений.{values}.СоздатьМенеджерЗаписи(); МЗ.Контрагент = ТекущийОбъект.Ссылка; МЗ.Свойство = КЗ.Ключ; МЗ.Значение = КЗ.Значение; МЗ.Записать();
 КонецЦикла;
КонецПроцедуры
'''
    return f'''&НаСервере
Перем Значения;

&НаСервере
Процедура ПриСозданииНаСервере(Отказ, СтандартнаяОбработка)
 ПостроитьПоля();
КонецПроцедуры

&НаКлиенте
Процедура МенеджерПриИзменении(Элемент)
 ПерестроитьПоля();
КонецПроцедуры

&НаСервере
Процедура ПерестроитьПоля()
 ПостроитьПоля();
КонецПроцедуры

&НаСервере
Функция Виды(Менеджер)
 Запрос = Новый Запрос("{kinds}"); Запрос.УстановитьПараметр("Менеджер", Менеджер);
 Возврат Запрос.Выполнить().Выгрузить();
КонецФункции

&НаСервере
Функция ИмяПоля(Свойство)
 Возврат "Доп_" + СтрЗаменить(Строка(Свойство.УникальныйИдентификатор()), "-", "");
КонецФункции

&НаСервере
Функция ЗначениеСведения(Свойство)
{read}
КонецФункции

// Input fields for the kinds listed at the selected manager; fields of the previous manager are removed.
&НаСервере
Процедура ПостроитьПоля()
 Старые = Новый Массив;
 Для Каждого Э Из Элементы Цикл Если Лев(Э.Имя, 4) = "Доп_" Тогда Старые.Добавить(Э.Имя); КонецЕсли; КонецЦикла;
 Для Каждого Имя Из Старые Цикл Элементы.Удалить(Элементы[Имя]); КонецЦикла;
 Если Старые.Количество() > 0 Тогда ИзменитьРеквизиты(, Старые); КонецЕсли;
 ПоляМенеджера = Объект.Менеджер;
 Т = Виды(Объект.Менеджер); Новые = Новый Массив;
 Для Каждого С Из Т Цикл Новые.Добавить(Новый РеквизитФормы(ИмяПоля(С.Свойство), Новый ОписаниеТипов("Строка", , Новый КвалификаторыСтроки(50)), , Строка(С.Свойство))); КонецЦикла;
 Если Новые.Количество() > 0 Тогда ИзменитьРеквизиты(Новые); КонецЕсли;
 Для Каждого С Из Т Цикл
  Имя = ИмяПоля(С.Свойство); Э = Элементы.Добавить(Имя, Тип("ПолеФормы")); Э.Вид = ВидПоляФормы.ПолеВвода; Э.ПутьКДанным = Имя; Э.Заголовок = Строка(С.Свойство);
  ЭтотОбъект[Имя] = ЗначениеСведения(С.Свойство);
 КонецЦикла;
КонецПроцедуры

&НаСервере
Процедура ПередЗаписьюНаСервере(Отказ, ТекущийОбъект, ПараметрыЗаписи)
 Значения = Новый Соответствие;
 {'' if mutant == 'values_not_saved' else 'Для Каждого С Из Виды(ПоляМенеджера) Цикл Свойство = С.Свойство; Значение = ЭтотОбъект[ИмяПоля(Свойство)];' + save_value + ' КонецЦикла;'}
КонецПроцедуры
{after}'''
