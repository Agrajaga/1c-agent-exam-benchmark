"""Inject a trusted observation module into a disposable grading/probe copy."""
import shutil
import stat
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

MD = 'http://v8.1c.ru/8.3/MDClasses'
ET.register_namespace('', MD)
MODULE = 'BenchmarkObserver'


def inject(source, target, server_code, client_code=None):
    source, target = Path(source), Path(target)
    if target.exists():
        raise ValueError('Observer target must be absent')
    shutil.copytree(source, target)
    # Frozen submissions are read-only; only the disposable copy may be edited.
    for copied in target.rglob('*'):
        if copied.is_file():
            copied.chmod(copied.stat().st_mode | stat.S_IWUSR)
    path = target/'Configuration.xml'
    original_xml = path.read_text(encoding='utf-8-sig')
    root = ET.fromstring(original_xml)
    configuration = root.find('{'+MD+'}Configuration')
    children = configuration.find('{'+MD+'}ChildObjects')
    if any((x.text or '') == MODULE for x in children):
        raise ValueError('Reserved observer name already exists')
    # QName values inside 1C XML depend on declared prefixes even where no tag
    # uses that namespace. ElementTree serialization drops those declarations.
    if '</ChildObjects>' not in original_xml:
        raise ValueError('Unsupported configuration XML namespace layout')
    path.write_text(original_xml.replace('</ChildObjects>', f'<CommonModule>{MODULE}</CommonModule>\n</ChildObjects>', 1), encoding='utf-8')
    descriptor = f'''<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="{MD}" xmlns:v8="http://v8.1c.ru/8.1/data/core" version="2.17">
 <CommonModule uuid="{uuid.uuid4()}">
  <Properties><Name>{MODULE}</Name><Synonym/><Comment/>
   <Global>false</Global><ClientManagedApplication>false</ClientManagedApplication>
   <Server>true</Server><ExternalConnection>false</ExternalConnection>
   <ClientOrdinaryApplication>false</ClientOrdinaryApplication><ServerCall>true</ServerCall>
   <Privileged>false</Privileged><ReturnValuesReuse>DontUse</ReturnValuesReuse>
  </Properties>
 </CommonModule>
</MetaDataObject>'''
    module_root = target/'CommonModules'
    module_root.mkdir(exist_ok=True)
    (module_root/(MODULE+'.xml')).write_text(descriptor, encoding='utf-8')
    code_path = module_root/MODULE/'Ext'/'Module.bsl'
    code_path.parent.mkdir(parents=True)
    code_path.write_text(server_code, encoding='utf-8')
    ext = target/'Ext'
    ext.mkdir(exist_ok=True)
    # Use only a disposable copy. This replaces startup hooks for trusted observation,
    # never the frozen submitted sources. Posting object modules are untouched.
    (ext/'ManagedApplicationModule.bsl').write_text('''Процедура ПриНачалеРаботыСистемы()
    Попытка
        Результат = BenchmarkObserver.Run();
        @CLIENT_CALL@
    Исключение
        Результат = Новый Структура("error", ОписаниеОшибки());
    КонецПопытки;
    // An unhandled client error opens a modal dialog and hangs until timeout; report it instead.
    Попытка
        Запись = Новый ЗаписьJSON;
        Запись.ОткрытьФайл(ПараметрЗапуска);
        ЗаписатьJSON(Запись, Результат);
        Запись.Закрыть();
    Исключение
        Запись = Новый ЗаписьJSON;
        Запись.ОткрытьФайл(ПараметрЗапуска);
        ЗаписатьJSON(Запись, Новый Структура("error", "Observation is not serializable: " + ОписаниеОшибки()));
        Запись.Закрыть();
    КонецПопытки;
    ЗавершитьРаботуСистемы(Ложь);
КонецПроцедуры
'''.replace('@CLIENT_CALL@', 'ClientRun(Результат);' if client_code else '') + (client_code or ''), encoding='utf-8')
    return target


# client_code: an optional client procedure ClientRun(Результат) of the startup module, run after the server part
# (forms can be obtained only on the client).
RUNTIME_PROBE = '''Функция Run() Экспорт
    Имя = "BenchmarkProbe_20261009";
    До = Справочники.Валюты.НайтиПоНаименованию(Имя, Истина);
    Если До.Пустая() Тогда
        Объект = Справочники.Валюты.СоздатьЭлемент();
        Объект.Наименование = Имя;
        Объект.Записать();
    КонецЕсли;
    После = Справочники.Валюты.НайтиПоНаименованию(Имя, Истина);
    Результат = Новый Структура;
    Результат.Вставить("absent_before", До.Пустая());
    Результат.Вставить("read_after_write", Не После.Пустая());
    Результат.Вставить("name", После.Наименование);
    Возврат Результат;
КонецФункции
'''
