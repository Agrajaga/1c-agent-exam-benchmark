"""Small control configurations for calibrating the partial grader, not exam references."""
import copy
import json
import re
import shutil
import uuid
import xml.etree.ElementTree as E
from pathlib import Path
from .common import write_json
M='{http://v8.1c.ru/8.3/MDClasses}';V='{http://v8.1c.ru/8.1/data/core}';X='{http://v8.1c.ru/8.3/xcf/readable}';I='{http://www.w3.org/2001/XMLSchema-instance}'


def generate(starter,target,variant='one',mutant=None):
    target=Path(target);shutil.copytree(starter,target)
    head=(target/'Configuration.xml').read_text(encoding='utf-8-sig')
    opening=re.search(r'<MetaDataObject\b[^>]*>',head).group()
    for prefix,uri in E.iterparse(target/'Configuration.xml',events=['start-ns']):E.register_namespace(uri[0],uri[1])
    def save(path,root):
        text=E.tostring(root,encoding='unicode')
        text=re.sub(r'<MetaDataObject\b[^>]*>',lambda _:opening,text,count=1)
        Path(path).parent.mkdir(parents=True,exist_ok=True);Path(path).write_text('<?xml version="1.0" encoding="UTF-8"?>\n'+text, encoding='utf-8')
    def clone(group,old,new):
        txt=(target/group/(old+'.xml')).read_text(encoding='utf-8-sig').replace(old,new)
        txt=re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',lambda _:str(uuid.uuid4()),txt)
        root=E.fromstring(txt);obj=root[0]
        for name in ('DefaultObjectForm','DefaultListForm','DefaultChoiceForm','AuxiliaryObjectForm','AuxiliaryListForm','AuxiliaryChoiceForm'):
            el=obj.find(M+'Properties/'+M+name)
            if el is not None:el.text=None
        children=obj.find(M+'ChildObjects')
        for c in list(children):
            if c.tag in (M+'Form',M+'Template',M+'Command'):children.remove(c)
        return root
    def internal(parent,kind,name):
        node=E.SubElement(parent,M+'InternalInfo')
        categories=('Record','RecordSet','RecordKey','Selection','List','Manager')
        if kind=='AccountingRegister':categories+=('ExtDimensions',)
        if kind=='InformationRegister':categories+=('RecordManager',)
        for category in categories:
            g=E.SubElement(node,X+'GeneratedType',name=kind+category+'.'+name,category=category)
            E.SubElement(g,X+'TypeId').text=str(uuid.uuid4());E.SubElement(g,X+'ValueId').text=str(uuid.uuid4())
    def props(parent,values):
        p=E.SubElement(parent,M+'Properties')
        for k,v in values.items():E.SubElement(p,M+k).text=v
        return p
    def attribute(kind,name,typ,balance=None):
        a=E.Element(M+kind,uuid=str(uuid.uuid4()));p=props(a,{'Name':name,'Synonym':None,'Comment':None})
        t=E.SubElement(p,M+'Type');E.SubElement(t,V+'Type').text=typ
        if typ=='xs:string':
            q=E.SubElement(t,V+'StringQualifiers');E.SubElement(q,V+'Length').text='20';E.SubElement(q,V+'AllowedLength').text='Variable'
        if typ=='xs:decimal':
            q=E.SubElement(t,V+'NumberQualifiers')
            for k,v in [('Digits','15'),('FractionDigits','2'),('AllowedSign','Any')]:E.SubElement(q,V+k).text=v
        if balance is not None:E.SubElement(p,M+'Balance').text=balance
        if kind in ('Dimension','Resource') and balance is not None:
            E.SubElement(p,M+'AccountingFlag')
            if kind=='Resource':E.SubElement(p,M+'ExtDimensionAccountingFlag')
        return a
    n={'one':'Bench','two':'Control','sub':'Sub','tab':'Tab'}[variant]
    # Variant tab keeps analogs in a tabular section of the items catalog instead of an information register.
    tab=variant=='tab'
    # Variant sub keeps item and warehouse in subconto kinds of the starter's ВидыСубконто instead of register dimensions.
    sub=variant=='sub'
    names={'warehouse':n+'Warehouse','receipt':n+'Receipt','sale':n+'Sale','manual':n+'Manual','ledger':n+'Ledger','analogs':n+'Analogs','accounts':n+'Accounts'}
    config=head
    for kind,k in [('Catalog','warehouse'),('Document','receipt'),('Document','sale'),('Document','manual'),('AccountingRegister','ledger'),('InformationRegister','analogs'),('ChartOfAccounts','accounts')]:
        config=config.replace('</ChildObjects>',f'<{kind}>{names[k]}</{kind}></ChildObjects>',1)
    (target/'Configuration.xml').write_text(config, encoding='utf-8')
    warehouse=clone('Catalogs','Валюты',names['warehouse']);warehouse[0].find(M+'ChildObjects').clear();save(target/'Catalogs'/(names['warehouse']+'.xml'),warehouse)
    accounts=clone('ChartsOfAccounts','Управленческий',names['accounts']);save(target/'ChartsOfAccounts'/(names['accounts']+'.xml'),accounts)
    # A string article entered by the user (the starter's catalog code is numeric).
    items_xml=target/'Catalogs'/'Номенклатура.xml'
    for prefix,uri in E.iterparse(items_xml,events=['start-ns']):E.register_namespace(uri[0],uri[1])
    items=E.parse(items_xml).getroot();items[0].find(M+'ChildObjects').append(attribute('Attribute','Артикул','xs:string'))
    if tab:items[0].find(M+'ChildObjects').append(analog_section(target))
    save(items_xml,items)
    predefined=target/'ChartsOfAccounts'/names['accounts']/'Ext'/'Predefined.xml'
    predefined.parent.mkdir(parents=True)
    # The kind is the name attribute, as the designer exports it; a nested <Type> element is silently ignored by 1C.
    kinds={'Goods':('Номенклатура','Склад'),'Profit':('Номенклатура',)} if sub else {}
    ext=lambda role:'<ExtDimensionTypes>'+''.join(f'<ExtDimensionType name="ChartOfCharacteristicTypes.ВидыСубконто.{k}"><Turnover>false</Turnover><AccountingFlags/></ExtDimensionType>' for k in kinds[role])+'</ExtDimensionTypes>' if role in kinds else ''
    predefined.write_text('<?xml version="1.0" encoding="UTF-8"?><PredefinedData xmlns="http://v8.1c.ru/8.3/xcf/predef" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="ChartOfAccountsPredefinedItems" version="2.20">'+''.join(f'<Item id="{uuid.uuid4()}"><Name>{role}</Name><Code>{code}</Code><Description>{role}</Description><AccountType>ActivePassive</AccountType><OffBalance>false</OffBalance><Order>{code}</Order><AccountingFlags/>{ext(role)}</Item>' for role,code in [('Goods','41'),('Suppliers','60'),('Customers','62'),('Profit','90')])+'</PredefinedData>', encoding='utf-8')
    if sub:
        accounts[0].find(M+'Properties/'+M+'ExtDimensionTypes').text='ChartOfCharacteristicTypes.ВидыСубконто'
        accounts[0].find(M+'Properties/'+M+'MaxExtDimensionCount').text='2'
        save(target/'ChartsOfAccounts'/(names['accounts']+'.xml'),accounts)
        kinds_xml=target/'ChartsOfCharacteristicTypes'/'ВидыСубконто.xml'
        text=kinds_xml.read_text(encoding='utf-8-sig')
        kinds_xml.write_text(text.replace('<v8:Type>cfg:CatalogRef.Номенклатура</v8:Type>','<v8:Type>cfg:CatalogRef.Номенклатура</v8:Type><v8:Type>cfg:CatalogRef.'+names['warehouse']+'</v8:Type>',1),encoding='utf-8')
        kinds_predefined=target/'ChartsOfCharacteristicTypes'/'ВидыСубконто'/'Ext'/'Predefined.xml'
        text=kinds_predefined.read_text(encoding='utf-8-sig')
        kinds_predefined.write_text(text.replace('</PredefinedData>',f'<Item id="{uuid.uuid4()}"><Name>Склад</Name><Code>000000002</Code><Description>Склад</Description><Type><v8:Type xmlns:d4p1="http://v8.1c.ru/8.1/data/enterprise/current-config">d4p1:CatalogRef.{names["warehouse"]}</v8:Type></Type><IsFolder>false</IsFolder></Item></PredefinedData>'),encoding='utf-8')
    # Single global item dimension, warehouse dimension; quantity debit/credit are independent.
    reg=E.Element(M+'MetaDataObject');o=E.SubElement(reg,M+'AccountingRegister',uuid=str(uuid.uuid4()))
    internal(o,'AccountingRegister',names['ledger'])
    props(o,{'Name':names['ledger'],'Synonym':None,'Comment':None,'ChartOfAccounts':'ChartOfAccounts.'+names['accounts'],'Correspondence':'true','UseStandardCommands':'true','DataLockControlMode':'Managed','FullTextSearch':'DontUse'})
    c=E.SubElement(o,M+'ChildObjects')
    if not sub:c.append(attribute('Dimension','Item','cfg:CatalogRef.Номенклатура','true'));c.append(attribute('Dimension','Warehouse','cfg:CatalogRef.'+names['warehouse'],'true'))
    c.append(attribute('Resource','Amount','xs:decimal','true'));c.append(attribute('Resource','Qty','xs:decimal','false'))
    c.append(attribute('Attribute','Requested','cfg:CatalogRef.Номенклатура'))
    save(target/'AccountingRegisters'/(names['ledger']+'.xml'),reg)
    analog=E.Element(M+'MetaDataObject');o=E.SubElement(analog,M+'InformationRegister',uuid=str(uuid.uuid4()))
    internal(o,'InformationRegister',names['analogs'])
    props(o,{'Name':names['analogs'],'Synonym':None,'Comment':None,'InformationRegisterPeriodicity':'Nonperiodical','WriteMode':'Independent','UseStandardCommands':'true','DataLockControlMode':'Managed'})
    c=E.SubElement(o,M+'ChildObjects')
    for k in ('LinkA','LinkB'):c.append(attribute('Dimension',k,'cfg:CatalogRef.Номенклатура'))
    save(target/'InformationRegisters'/(names['analogs']+'.xml'),analog)
    for kind,original in [('receipt','ПриходнаяНакладная'),('sale','РасходнаяНакладная'),('manual','ПриходнаяНакладная')]:
        doc=clone('Documents',original,names[kind]);o=doc[0]
        o.find(M+'ChildObjects').append(attribute('Attribute','Warehouse','cfg:CatalogRef.'+names['warehouse']))
        records=o.find(M+'Properties/'+M+'RegisterRecords');records.clear()
        E.SubElement(records,X+'Item',{I+'type':'xr:MDObjectRef'}).text='AccountingRegister.'+names['ledger']
        if kind=='manual':o.find(M+'Properties/'+M+'Posting').text='Deny'
        if kind=='sale' and mutant=='warehouse_in_rows':
            o.find(M+'ChildObjects/'+M+'TabularSection/'+M+'ChildObjects').append(attribute('Attribute','RowWarehouse','cfg:CatalogRef.'+names['warehouse']))
        save(target/'Documents'/(names[kind]+'.xml'),doc)
    binding={'schema_version':1,'objects':{'items':'Catalog.Номенклатура','warehouses':'Catalog.'+names['warehouse'],'receipt':'Document.'+names['receipt'],'sale':'Document.'+names['sale'],'manual':'Document.'+names['manual'],'ledger':'AccountingRegister.'+names['ledger'],'accounts':'ChartOfAccounts.'+names['accounts']},'fields':{'items':{'article':'Артикул'},'ledger':{'item_debit':'Item','item_credit':'Item','warehouse_debit':'Warehouse','warehouse_credit':'Warehouse','quantity_debit':'QtyДт','quantity_credit':'QtyКт','amount':'Amount'}},'account_codes':{'goods':'41','suppliers':'60','customers':'62','profit':'90'},'analogs':{'mode':'information_register','object':'InformationRegister.'+names['analogs'],'left':'LinkA','right':'LinkB'}}
    if tab:binding['analogs']={'mode':'tabular_section','object':'Catalog.Номенклатура','left':'Ссылка','right':'Аналоги.Номенклатура'}
    if sub:binding['fields']['ledger'].update({k:'ВидыСубконто.'+('Номенклатура' if k.startswith('item_') else 'Склад') for k in ('item_debit','item_credit','warehouse_debit','warehouse_credit')})
    for kind in ('receipt','sale'):binding['fields'][kind]={'warehouse':'Warehouse','item':'СписокНоменклатуры.Номенклатура','quantity':'СписокНоменклатуры.Количество','price':'СписокНоменклатуры.Цена','amount':'СписокНоменклатуры.Сумма'}
    write_json(target.parent/'binding.json',binding)
    receipt=f'''Процедура ОбработкаПроведения(Отказ, РежимПроведения)
 Движения.{names['ledger']}.Записывать = Истина;
 Для Каждого Стр Из СписокНоменклатуры Цикл
  Дв = Движения.{names['ledger']}.Добавить(); Дв.Период = Дата;
  Дв.СчетДт = ПланыСчетов.{names['accounts']}.НайтиПоКоду("41"); Дв.СчетКт = ПланыСчетов.{names['accounts']}.НайтиПоКоду("60");
  Дв.Item = Стр.Номенклатура; Дв.Warehouse = Warehouse; Дв.QtyДт = Стр.Количество; Дв.Amount = Стр.Сумма;
 КонецЦикла;
КонецПроцедуры
'''
    if sub:receipt=receipt.replace('Дв.Item = Стр.Номенклатура; Дв.Warehouse = Warehouse;','Дв.СубконтоДт[ПланыВидовХарактеристик.ВидыСубконто.Номенклатура] = Стр.Номенклатура; Дв.СубконтоДт[ПланыВидовХарактеристик.ВидыСубконто.Склад] = Warehouse;')
    if tab:sale_template=SALE.replace(ANALOG_QUERY_LINE,TAB_ANALOG_QUERY_LINE)
    sale=(sale_template if tab else SALE) if not sub else SALE.replace(SALE_QUERY_LINE,SUB_QUERY_LINE).replace('Дв.Item = Кандидат; Дв.Warehouse = Warehouse;',SUB_COST).replace('Дв.Item = Кандидат; Дв.Requested',SUB_REVENUE)
    sale=sale.replace('@LEDGER@',names['ledger']).replace('@ACCOUNTS@',names['accounts']).replace('@ANALOGS@',names['analogs'])
    if mutant=='warehouse_average':sale=sale.replace('ОбщаяСумма = ОбщаяСумма + С.Amount;','Если С.Warehouse = Warehouse Тогда ОбщаяСумма = ОбщаяСумма + С.Amount; КонецЕсли;').replace('ОбщееКоличество = ОбщееКоличество + С.QtyДт;','Если С.Warehouse = Warehouse Тогда ОбщееКоличество = ОбщееКоличество + С.QtyДт; КонецЕсли;')
    if mutant=='ignore_manual':sale=sale.replace('Для Каждого С Из Таблица Цикл','Для Каждого С Из Таблица Цикл\n Если ТипЗнч(С.Регистратор) = Тип("ДокументСсылка.'+names['manual']+'") Тогда Продолжить; КонецЕсли;')
    if mutant=='double_analog':sale=sale.replace('Занято.Вставить(Кандидат, Уже + Берем);','Занято.Вставить(Кандидат, Уже);')
    if mutant=='partial_refusal':sale=sale.replace('Отказ = Истина; Возврат;','Движения.@LEDGER@.Записать(); Возврат;'.replace('@LEDGER@',names['ledger']))
    MUT={'no_transitive':('Найдено.Вставить(Сосед, Истина); Очередь.Добавить(Сосед);','Найдено.Вставить(Сосед, Истина);'),
         'analog_first':('Для Каждого Н Из Аналоги Цикл Кандидаты.Добавить(Н.Товар); КонецЦикла;','Кандидаты.Удалить(0); Для Каждого Н Из Аналоги Цикл Кандидаты.Добавить(Н.Товар); КонецЦикла; Кандидаты.Добавить(Стр.Номенклатура);'),
         'article_desc':('Аналоги.Сортировать("Артикул Возр");','Аналоги.Сортировать("Артикул Убыв");'),
         'no_substitution':('Для Каждого Н Из Аналоги Цикл Кандидаты.Добавить(Н.Товар); КонецЦикла;',''),
         'company_stock':('Если С.Warehouse = Warehouse Тогда Доступно = Доступно + С.QtyДт; КонецЕсли;','Доступно = Доступно + С.QtyДт;'),
         'no_revenue':('Дв.Requested = Стр.Номенклатура; Дв.Amount = Берем * Стр.Цена;','Дв.Requested = Стр.Номенклатура; Дв.Amount = 0;'),
         'cost_wrong_debit':('НайтиПоКоду("90"); Дв.СчетКт = СчетТовары;','НайтиПоКоду("60"); Дв.СчетКт = СчетТовары;')}
    if mutant in MUT:
        old_text,new_text=MUT[mutant]
        if old_text not in sale:raise ValueError('Mutation anchor missing: '+mutant)
        sale=sale.replace(old_text,new_text,1)
        if mutant=='company_stock':sale=sale.replace('Если С.Warehouse = Warehouse Тогда Доступно = Доступно - С.QtyКт; КонецЕсли;','Доступно = Доступно - С.QtyКт;',1)
    if mutant=='receipt_wrong_credit':receipt=receipt.replace('НайтиПоКоду("60")','НайтиПоКоду("62")',1)
    if mutant=='posting_crash':sale=sale.replace(' Движения.'+names['ledger']+'.Записывать = Истина;',' ВызватьИсключение "calibration crash";\n Движения.'+names['ledger']+'.Записывать = Истина;',1)
    from .calibration_ou import build as build_ou
    receipt,sale,binding['ou']=build_ou(target,n,mutant,clone,save,attribute,receipt,sale,names)
    for kind,code in [('receipt',receipt),('sale',sale)]:
        f=target/'Documents'/names[kind]/'Ext'/'ObjectModule.bsl';f.parent.mkdir(parents=True);f.write_text(code, encoding='utf-8')
    if mutant=='manual_restricted':
        module=target/'AccountingRegisters'/names['ledger']/'Ext'/'RecordSetModule.bsl';module.parent.mkdir(parents=True,exist_ok=True)
        module.write_text(f'''Процедура ПередЗаписью(Отказ, Замещение)
 Если ТипЗнч(Отбор.Регистратор.Значение) = Тип("ДокументСсылка.{names['manual']}") Тогда
  Для Каждого З Из ЭтотОбъект Цикл Если З.СчетДт.Код <> "41" Тогда Отказ = Истина; КонецЕсли; КонецЦикла;
 КонецЕсли;
КонецПроцедуры
''', encoding='utf-8')
    if mutant=='article_overwrite':
        module=target/'Catalogs'/'Номенклатура'/'Ext'/'ObjectModule.bsl';module.parent.mkdir(parents=True,exist_ok=True)
        module.write_text('Процедура ПередЗаписью(Отказ)\n Если ЭтоНовый() Тогда Артикул = "AUTO-" + Наименование; КонецЕсли;\nКонецПроцедуры\n', encoding='utf-8')
    binding['reports']={'bu_sales':add_report(target,names,variant,mutant)}
    from .calibration_ou import reports as ou_reports
    binding['reports'].update(ou_reports(target,n,variant,mutant,names))
    from .calibration_pr import build as build_pr
    binding['pr'],binding['reports']['pr_bonus']=build_pr(target,n,variant,mutant,clone,save,attribute)
    from .calibration_forms import build as build_forms
    binding['forms']=build_forms(target,n,variant,mutant,clone,save,attribute)
    from .calibration_interface import build as build_interface
    binding['interface']=build_interface(target,n,variant,mutant,binding)
    write_json(target.parent/'binding.json',binding)
    return binding


SALES_QUERY='''ВЫБРАТЬ Т.Requested КАК Номенклатура, Т.Item КАК Продано,
 СУММА(ВЫБОР КОГДА Т.СчетКт.Код = "41" ТОГДА Т.QtyКт ИНАЧЕ 0 КОНЕЦ) КАК Количество,
 СУММА(ВЫБОР КОГДА Т.СчетКт.Код = "41" ТОГДА Т.Amount ИНАЧЕ 0 КОНЕЦ) КАК Себестоимость,
 СУММА(ВЫБОР КОГДА Т.СчетДт.Код = "62" ТОГДА Т.Amount ИНАЧЕ 0 КОНЕЦ) КАК Продажа,
 СУММА(ВЫБОР КОГДА Т.СчетДт.Код = "62" ТОГДА Т.Amount ИНАЧЕ 0 КОНЕЦ) - СУММА(ВЫБОР КОГДА Т.СчетКт.Код = "41" ТОГДА Т.Amount ИНАЧЕ 0 КОНЕЦ) КАК Прибыль
ИЗ РегистрБухгалтерии.@LEDGER@ КАК Т
ГДЕ Т.Период МЕЖДУ &НачалоПериода И &КонецПериода И Т.Requested <> ЗНАЧЕНИЕ(Справочник.Номенклатура.ПустаяСсылка)
СГРУППИРОВАТЬ ПО Т.Requested, Т.Item'''
# Variant sub: the account 41 subconto are (1) item, (2) warehouse; the credit subconto 1 of both 41 and 90 is the sold item.
SUB_SOLD='ВЫРАЗИТЬ(Т.СубконтоКт1 КАК Справочник.Номенклатура)'
ANALOG_QUERY_LINE='Связи = Новый Запрос("ВЫБРАТЬ LinkA, LinkB ИЗ РегистрСведений.@ANALOGS@");'
TAB_ANALOG_QUERY_LINE='Связи = Новый Запрос("ВЫБРАТЬ Т.Ссылка КАК LinkA, Т.Номенклатура КАК LinkB ИЗ Справочник.Номенклатура.Аналоги КАК Т");'


def analog_section(target):
    """Tabular section Аналоги of the items catalog: one column Номенклатура, cloned from the starter receipt's lines."""
    receipt=E.parse(target/'Documents'/'ПриходнаяНакладная.xml').getroot()
    section=copy.deepcopy(receipt[0].find(M+'ChildObjects/'+M+'TabularSection'))
    section.set('uuid',str(uuid.uuid4()))
    for g in section.iter(X+'GeneratedType'):
        g.set('name',g.get('name').replace('DocumentTabularSection','CatalogTabularSection').replace('ПриходнаяНакладная.СписокНоменклатуры','Номенклатура.Аналоги'))
        for child in g:child.text=str(uuid.uuid4())
    section.find(M+'Properties/'+M+'Name').text='Аналоги'
    children=section.find(M+'ChildObjects')
    for a in list(children):
        if a.findtext(M+'Properties/'+M+'Name')!='Номенклатура':children.remove(a)
        else:a.set('uuid',str(uuid.uuid4()))
    return section


SALE_QUERY_LINE='Запрос = Новый Запрос("ВЫБРАТЬ * ИЗ РегистрБухгалтерии.@LEDGER@");'
SUB_QUERY_LINE=('Запрос = Новый Запрос("ВЫБРАТЬ Т.СчетДт КАК СчетДт, Т.СчетКт КАК СчетКт, Т.Amount КАК Amount, Т.QtyДт КАК QtyДт, Т.QtyКт КАК QtyКт, Т.Регистратор КАК Регистратор,'
                ' ВЫБОР КОГДА Т.СчетДт.Код = ""41"" ТОГДА Т.СубконтоДт1 ИНАЧЕ Т.СубконтоКт1 КОНЕЦ КАК Item,'
                ' ВЫБОР КОГДА Т.СчетДт.Код = ""41"" ТОГДА Т.СубконтоДт2 ИНАЧЕ Т.СубконтоКт2 КОНЕЦ КАК Warehouse ИЗ РегистрБухгалтерии.@LEDGER@.ДвиженияССубконто КАК Т");')
SUB_COST=('Дв.СубконтоДт[ПланыВидовХарактеристик.ВидыСубконто.Номенклатура] = Кандидат; Дв.СубконтоКт[ПланыВидовХарактеристик.ВидыСубконто.Номенклатура] = Кандидат;'
          ' Дв.СубконтоКт[ПланыВидовХарактеристик.ВидыСубконто.Склад] = Warehouse;')
SUB_REVENUE='Дв.СубконтоКт[ПланыВидовХарактеристик.ВидыСубконто.Номенклатура] = Кандидат; Дв.Requested'
FIELDS={'item':'Номенклатура','sold':'Продано','quantity':'Количество','cost':'Себестоимость','revenue':'Продажа','profit':'Прибыль'}
MDX='xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.17"'


def add_report(target,names,variant,mutant):
    """Sales report of requested items and analogs: variant one as an exported function, variant two as a DCS main schema."""
    name=names['ledger'].replace('Ledger','Sales')
    query=SALES_QUERY.replace('@LEDGER@',names['ledger'])
    if variant=='sub':query=query.replace('Т.Item',SUB_SOLD).replace('РегистрБухгалтерии.'+names['ledger']+' КАК Т','РегистрБухгалтерии.'+names['ledger']+'.ДвиженияССубконто КАК Т')
    if mutant=='report_ignores_period':query=query.replace('Т.Период МЕЖДУ &НачалоПериода И &КонецПериода И ','')
    if mutant=='report_profit_wrong':query=query.replace(' - СУММА(ВЫБОР КОГДА Т.СчетКт.Код = "41" ТОГДА Т.Amount ИНАЧЕ 0 КОНЕЦ) КАК Прибыль',' КАК Прибыль')
    return make_report(target,name,variant,query,FIELDS,['Номенклатура','Продано'],['Количество','Себестоимость','Продажа','Прибыль'])


DATE_TYPE='<v8:Type>xs:dateTime</v8:Type><v8:DateQualifiers><v8:DateFractions>DateTime</v8:DateFractions></v8:DateQualifiers>'


def make_report(target,name,variant,query,fields,groups,totals,extra=()):
    """A report over one query: variant one as an exported object-module function, otherwise a DCS main schema.

    extra: (binding parameter role, query parameter, DCS value type xml) passed after the period, e.g. a department."""
    from xml.sax.saxutils import escape
    dcs=variant!='one'
    config=target/'Configuration.xml'
    config.write_text(config.read_text(encoding='utf-8-sig').replace('</ChildObjects>',f'<Report>{name}</Report></ChildObjects>',1), encoding='utf-8')
    schema=f'<MainDataCompositionSchema>Report.{name}.Template.ОсновнаяСхема</MainDataCompositionSchema>' if dcs else '<MainDataCompositionSchema/>'
    (target/'Reports').mkdir(exist_ok=True)
    (target/'Reports'/(name+'.xml')).write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject {MDX}>
 <Report uuid="{uuid.uuid4()}">
  <InternalInfo>
   <xr:GeneratedType name="ReportObject.{name}" category="Object"><xr:TypeId>{uuid.uuid4()}</xr:TypeId><xr:ValueId>{uuid.uuid4()}</xr:ValueId></xr:GeneratedType>
   <xr:GeneratedType name="ReportManager.{name}" category="Manager"><xr:TypeId>{uuid.uuid4()}</xr:TypeId><xr:ValueId>{uuid.uuid4()}</xr:ValueId></xr:GeneratedType>
  </InternalInfo>
  <Properties><Name>{name}</Name><Synonym/><Comment/><UseStandardCommands>true</UseStandardCommands><DefaultForm/><AuxiliaryForm/>{schema}<DefaultSettingsForm/><AuxiliarySettingsForm/><DefaultVariantForm/><VariantsStorage/><SettingsStorage/><IncludeHelpInContents>false</IncludeHelpInContents><ExtendedPresentation/><Explanation/></Properties>
  <ChildObjects>{'<Template>ОсновнаяСхема</Template>' if dcs else ''}</ChildObjects>
 </Report>
</MetaDataObject>
''',encoding='utf-8')
    if not dcs:
        module=target/'Reports'/name/'Ext'/'ObjectModule.bsl';module.parent.mkdir(parents=True)
        text=query.replace('"','""').replace('\n','\n|')
        args=''.join(', '+p for _,p,_ in extra)
        sets=''.join(f' Запрос.УстановитьПараметр("{p}", {p});' for _,p,_ in extra)
        module.write_text(f'Функция Данные(Начало, Конец{args}) Экспорт\n Запрос = Новый Запрос("{text}");\n Запрос.УстановитьПараметр("НачалоПериода", Начало); Запрос.УстановитьПараметр("КонецПериода", Конец);{sets}\n Возврат Запрос.Выполнить().Выгрузить();\nКонецФункции\n',encoding='utf-8')
        return {'object':'Report.'+name,'kind':'function','module':'object','function':'Данные','fields':fields}
    templates=target/'Reports'/name/'Templates';(templates/'ОсновнаяСхема'/'Ext').mkdir(parents=True)
    (templates/'ОсновнаяСхема.xml').write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject {MDX}>
 <Template uuid="{uuid.uuid4()}"><Properties><Name>ОсновнаяСхема</Name><Synonym/><Comment/><TemplateType>DataCompositionSchema</TemplateType></Properties></Template>
</MetaDataObject>
''',encoding='utf-8')
    columns=''.join(f'<field xsi:type="DataSetFieldField"><dataPath>{c}</dataPath><field>{c}</field></field>' for c in fields.values())
    param=lambda n,typ,value:f'<parameter><name>{n}</name><valueType>{typ}</valueType>{value}<useRestriction>false</useRestriction></parameter>'
    params=''.join(param(n,DATE_TYPE,'<value xsi:type="xs:dateTime">0001-01-01T00:00:00</value>') for n in ('НачалоПериода','КонецПериода'))
    params+=''.join(param(p,typ,'') for _,p,typ in extra)
    selection=''.join(f'<dcsset:item xsi:type="dcsset:SelectedItemField"><dcsset:field>{c}</dcsset:field></dcsset:item>' for c in fields.values())
    group=lambda f,inner='':f'<dcsset:item xsi:type="dcsset:StructureItemGroup"><dcsset:groupItems><dcsset:item xsi:type="dcsset:GroupItemField"><dcsset:field>{f}</dcsset:field><dcsset:groupType>Items</dcsset:groupType><dcsset:periodAdditionType>None</dcsset:periodAdditionType><dcsset:periodAdditionBegin xsi:type="xs:dateTime">0001-01-01T00:00:00</dcsset:periodAdditionBegin><dcsset:periodAdditionEnd xsi:type="xs:dateTime">0001-01-01T00:00:00</dcsset:periodAdditionEnd></dcsset:item></dcsset:groupItems><dcsset:order><dcsset:item xsi:type="dcsset:OrderItemAuto"/></dcsset:order><dcsset:selection><dcsset:item xsi:type="dcsset:SelectedItemAuto"/></dcsset:selection>{inner}</dcsset:item>'
    structure=''
    for g in reversed(groups):structure=group(g,structure)
    total=''.join(f'<totalField><dataPath>{c}</dataPath><expression>Сумма({c})</expression></totalField>' for c in totals)
    (templates/'ОсновнаяСхема'/'Ext'/'Template.xml').write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<DataCompositionSchema xmlns="http://v8.1c.ru/8.1/data-composition-system/schema" xmlns:dcscom="http://v8.1c.ru/8.1/data-composition-system/common" xmlns:dcscor="http://v8.1c.ru/8.1/data-composition-system/core" xmlns:dcsset="http://v8.1c.ru/8.1/data-composition-system/settings" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:v8ui="http://v8.1c.ru/8.1/data/ui" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config">
<dataSource><name>ИсточникДанных1</name><dataSourceType>Local</dataSourceType></dataSource>
<dataSet xsi:type="DataSetQuery"><name>Данные</name>{columns}<dataSource>ИсточникДанных1</dataSource><query>{escape(query)}</query></dataSet>
{total}{params}
<settingsVariant><dcsset:name>Основной</dcsset:name><dcsset:settings><dcsset:selection>{selection}</dcsset:selection>{structure}</dcsset:settings></settingsVariant>
</DataCompositionSchema>
''',encoding='utf-8')
    parameters={'period_start':'НачалоПериода','period_end':'КонецПериода'}
    parameters.update({role:p for role,p,_ in extra})
    return {'object':'Report.'+name,'kind':'dcs','parameters':parameters,'fields':fields}

SALE='''Процедура ОбработкаПроведения(Отказ, РежимПроведения)
 Движения.@LEDGER@.Записывать = Истина;
 СчетТовары = ПланыСчетов.@ACCOUNTS@.НайтиПоКоду("41");
 Запрос = Новый Запрос("ВЫБРАТЬ * ИЗ РегистрБухгалтерии.@LEDGER@"); Таблица = Запрос.Выполнить().Выгрузить();
 Связи = Новый Запрос("ВЫБРАТЬ LinkA, LinkB ИЗ РегистрСведений.@ANALOGS@"); СвязиТ = Связи.Выполнить().Выгрузить();
 Занято = Новый Соответствие;
 Для Каждого Стр Из СписокНоменклатуры Цикл
  Кандидаты = Новый Массив; Кандидаты.Добавить(Стр.Номенклатура);
  // Own item first, then the transitive closure of analogs ordered by article as a string (ascending).
  Найдено = Новый Соответствие; Найдено.Вставить(Стр.Номенклатура, Истина); Очередь = Новый Массив; Очередь.Добавить(Стр.Номенклатура);
  Аналоги = Новый ТаблицаЗначений; Аналоги.Колонки.Добавить("Товар"); Аналоги.Колонки.Добавить("Артикул");
  Пока Очередь.Количество() > 0 Цикл
   Текущий = Очередь[0]; Очередь.Удалить(0);
   Для Каждого Св Из СвязиТ Цикл
    Сосед = Неопределено;
    Если Св.LinkA = Текущий Тогда Сосед = Св.LinkB; ИначеЕсли Св.LinkB = Текущий Тогда Сосед = Св.LinkA; КонецЕсли;
    Если Сосед <> Неопределено И Найдено.Получить(Сосед) = Неопределено Тогда
     Найдено.Вставить(Сосед, Истина); Очередь.Добавить(Сосед);
     Н = Аналоги.Добавить(); Н.Товар = Сосед; Н.Артикул = Сосед.Артикул;
    КонецЕсли;
   КонецЦикла;
  КонецЦикла;
  Аналоги.Сортировать("Артикул Возр");
  Для Каждого Н Из Аналоги Цикл Кандидаты.Добавить(Н.Товар); КонецЦикла;
  Нужно = Стр.Количество;
  Для Каждого Кандидат Из Кандидаты Цикл
   Доступно = 0; ОбщаяСумма = 0; ОбщееКоличество = 0;
   Для Каждого С Из Таблица Цикл
    Если С.Item <> Кандидат Тогда Продолжить; КонецЕсли;
    Если С.СчетДт = СчетТовары Тогда
     ОбщаяСумма = ОбщаяСумма + С.Amount; ОбщееКоличество = ОбщееКоличество + С.QtyДт;
     Если С.Warehouse = Warehouse Тогда Доступно = Доступно + С.QtyДт; КонецЕсли;
    КонецЕсли;
    Если С.СчетКт = СчетТовары Тогда
     ОбщаяСумма = ОбщаяСумма - С.Amount; ОбщееКоличество = ОбщееКоличество - С.QtyКт;
     Если С.Warehouse = Warehouse Тогда Доступно = Доступно - С.QtyКт; КонецЕсли;
    КонецЕсли;
   КонецЦикла;
   Уже = Занято.Получить(Кандидат); Если Уже = Неопределено Тогда Уже = 0; КонецЕсли;
   Берем = Мин(Нужно, Макс(0, Доступно - Уже));
   Если Берем > 0 Тогда
    Дв = Движения.@LEDGER@.Добавить(); Дв.Период = Дата;
    Дв.СчетДт = ПланыСчетов.@ACCOUNTS@.НайтиПоКоду("90"); Дв.СчетКт = СчетТовары;
    Дв.Item = Кандидат; Дв.Warehouse = Warehouse; Дв.QtyКт = Берем; Дв.Amount = Окр(ОбщаяСумма / ОбщееКоличество * Берем, 2); Дв.Requested = Стр.Номенклатура;
    Дв = Движения.@LEDGER@.Добавить(); Дв.Период = Дата; Дв.СчетДт = ПланыСчетов.@ACCOUNTS@.НайтиПоКоду("62"); Дв.СчетКт = ПланыСчетов.@ACCOUNTS@.НайтиПоКоду("90"); Дв.Item = Кандидат; Дв.Requested = Стр.Номенклатура; Дв.Amount = Берем * Стр.Цена;
    Нужно = Нужно - Берем; Занято.Вставить(Кандидат, Уже + Берем);
   КонецЕсли;
   Если Нужно = 0 Тогда Прервать; КонецЕсли;
  КонецЦикла;
  Если Нужно > 0 Тогда Отказ = Истина; Возврат; КонецЕсли;
 КонецЦикла;
КонецПроцедуры
'''
