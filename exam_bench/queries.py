"""Query texts of the solution, checked by the platform's own query parser (М4.12, F1C-GEN12).

A query text is a string literal of the solution's BSL code that starts with ВЫБРАТЬ/SELECT or УНИЧТОЖИТЬ/DROP
(in upper case, or in any case with a FROM clause). The
platform parses each one in the solution's infobase with Запрос.НайтиПараметры(): the query language parser with the
solution's metadata, nothing is executed against data. A text it rejects (syntax, missing table or field) fails
whenever that code runs, whether or not a scenario reaches it.

Not checked, and reported as such:
- a literal joined with other strings by «+»: the full text exists only at run time;
- a reference to a temporary table without a dot in its name: such a table may come from a temporary tables manager
  filled by another query, which a single text does not see.
"""
import re
from pathlib import Path

from .codescan import lex_spans

CASE = 'query_texts'
# Upper case is how queries are written; any other case counts only with a FROM clause («Выбрать склад» is a message).
START = re.compile(r'\s*(ВЫБРАТЬ|SELECT|УНИЧТОЖИТЬ|DROP)\b')
START_ANY_CASE = re.compile(r'\s*(ВЫБРАТЬ|SELECT)\b', re.I)
FROM = re.compile(r'\b(ИЗ|FROM)\b', re.I)
# The parser names the missing table; a name without a dot is a temporary table.
TEMP_TABLE = re.compile(r'Таблица не найдена "[^".]+"|Table not found "[^".]+"')


def modules(src):
    src = Path(src)
    return sorted(p for p in src.rglob('*.bsl') if 'BenchmarkObserver' not in p.parts)


def extract(src):
    """([query], [skipped]): each {'file', 'line', 'text'} or {'file', 'line', 'reason'}."""
    src = Path(src)
    found, skipped = [], []
    for path in modules(src):
        text = path.read_text(encoding='utf-8-sig')
        code, spans = lex_spans(text)
        for literal, line, start, end in spans:
            if not (START.match(literal) or START_ANY_CASE.match(literal) and FROM.search(literal)):
                continue
            where = {'file': path.relative_to(src).as_posix(), 'line': line}
            before, after = code[:start].rstrip(), code[end:].lstrip()
            if before.endswith('+') or after.startswith('+'):
                skipped.append(dict(where, reason='текст запроса собирается из частей, целиком известен только при выполнении'))
            else:
                found.append(dict(where, text=literal))
    return found, skipped


def literal(text):
    """A BSL expression with the given text."""
    return ' + Символы.ПС + '.join('"' + line.replace('"', '""') + '"' for line in text.split('\n'))


# Observer helpers: the platform's own reading of a query (СхемаЗапроса) and the storage indexes of the infobase.
SCHEMA_BSL = """Функция ВыраженияСхемы(Коллекция)
	Результат = Новый Массив;
	Для Каждого Выражение Из Коллекция Цикл
		Результат.Добавить(Строка(Выражение));
	КонецЦикла;
	Возврат Результат;
КонецФункции

Функция ОператорСхемы(Оператор)
	Источники = Новый Массив;
	Для Каждого Источник Из Оператор.Источники Цикл
		Описание = Новый Структура("alias,kind,table,params,joins,nested", Источник.Источник.Псевдоним, "", "", Новый Массив, Новый Массив, Неопределено);
		ТипИсточника = ТипЗнч(Источник.Источник);
		Если ТипИсточника = Тип("ТаблицаСхемыЗапроса") Тогда
			Описание.kind = "table";
			Описание.table = Источник.Источник.ИмяТаблицы;
			Для Каждого Параметр Из Источник.Источник.Параметры Цикл
				Описание.params.Добавить(Строка(Параметр.Выражение));
			КонецЦикла;
		ИначеЕсли ТипИсточника = Тип("ВложенныйЗапросСхемыЗапроса") Тогда
			Описание.kind = "nested";
			Описание.nested = ЗапросСхемы(Источник.Источник.Запрос);
		Иначе
			Описание.kind = Строка(ТипИсточника);
		КонецЕсли;
		Для Каждого Соединение Из Источник.Соединения Цикл
			Описание.joins.Добавить(Новый Структура("to,type,condition", Соединение.Источник.Источник.Псевдоним, Строка(Соединение.ТипСоединения), Строка(Соединение.Условие)));
		КонецЦикла;
		Источники.Добавить(Описание);
	КонецЦикла;
	Возврат Новый Структура("sources,where,fields,group", Источники, ВыраженияСхемы(Оператор.Отбор), ВыраженияСхемы(Оператор.ВыбираемыеПоля), ВыраженияСхемы(Оператор.Группировка));
КонецФункции

Функция ЗапросСхемы(ЗапросВыбора)
	Операторы = Новый Массив;
	Для Каждого Оператор Из ЗапросВыбора.Операторы Цикл
		Операторы.Добавить(ОператорСхемы(Оператор));
	КонецЦикла;
	Возврат Новый Структура("into,operators", ЗапросВыбора.ТаблицаДляПомещения, Операторы);
КонецФункции

Функция ПакетСхемы(Текст)
	Схема = Новый СхемаЗапроса;
	Схема.УстановитьТекстЗапроса(Текст);
	Пакет = Новый Массив;
	Для Каждого Элемент Из Схема.ПакетЗапросов Цикл
		Если ТипЗнч(Элемент) = Тип("ЗапросВыбораСхемыЗапроса") Тогда
			Пакет.Добавить(ЗапросСхемы(Элемент));
		Иначе
			Пакет.Добавить(Новый Структура("drop", Элемент.ИмяТаблицы));
		КонецЕсли;
	КонецЦикла;
	Возврат Пакет;
КонецФункции

Функция ПолеХранения(Поле)
	Возврат Новый Структура("storage,name,metadata", Поле.ИмяПоляХранения, Поле.ИмяПоля, Строка(Поле.Метаданные));
КонецФункции

Функция СтруктураХранения()
	Таблицы = Новый Массив;
	Для Каждого ТаблицаХранения Из ПолучитьСтруктуруХраненияБазыДанных(, Ложь) Цикл
		Индексы = Новый Массив;
		Для Каждого Индекс Из ТаблицаХранения.Индексы Цикл
			ПоляИндекса = Новый Массив;
			Для Каждого Поле Из Индекс.Поля Цикл
				ПоляИндекса.Добавить(ПолеХранения(Поле));
			КонецЦикла;
			Индексы.Добавить(ПоляИндекса);
		КонецЦикла;
		Таблицы.Добавить(Новый Структура("table,purpose,metadata,indexes", ТаблицаХранения.ИмяТаблицы, ТаблицаХранения.Назначение, Строка(ТаблицаХранения.Метаданные), Индексы));
	КонецЦикла;
	Возврат Таблицы;
КонецФункции
"""


def code(src):
    """Observer module: parses every complete query text; for a parsed one also the platform's query schema.

    Returns {checked: [{index, error, schema | schema_error}], storage: [...] | storage_error}.
    """
    found, skipped = extract(src)
    body = [SCHEMA_BSL, 'Функция Run() Экспорт', '\tРезультаты = Новый Массив;']
    for index, query in enumerate(found):
        body += ['\tТекст = %s;' % literal(query['text']),
                 '\tОтвет = Новый Структура("index,error,schema,schema_error", %d, "", Неопределено, "");' % index,
                 '\tПопытка',
                 '\t\tЗапрос = Новый Запрос(Текст);',
                 '\t\tЗапрос.НайтиПараметры();',
                 '\t\tПопытка',
                 '\t\t\tОтвет.schema = ПакетСхемы(Текст);',
                 '\t\tИсключение',
                 '\t\t\tОтвет.schema_error = КраткоеПредставлениеОшибки(ИнформацияОбОшибке());',
                 '\t\tКонецПопытки;',
                 '\tИсключение',
                 '\t\tОтвет.error = КраткоеПредставлениеОшибки(ИнформацияОбОшибке());',
                 '\tКонецПопытки;',
                 '\tРезультаты.Добавить(Ответ);']
    body += ['\tОтвет = Новый Структура("checked", Результаты);',
             '\tПопытка',
             '\t\tОтвет.Вставить("storage", СтруктураХранения());',
             '\tИсключение',
             '\t\tОтвет.Вставить("storage_error", КраткоеПредставлениеОшибки(ИнформацияОбОшибке()));',
             '\tКонецПопытки;',
             '\tВозврат Ответ;', 'КонецФункции', '']
    return '\n'.join(body)


def verdicts(src, observation):
    """Each extracted query with the platform's answer: status ok, error, unresolved_temp_table or not_observed."""
    found, skipped = extract(src)
    answers = {item['index']: item['error'] for item in (observation or {}).get('checked') or []}
    out = []
    for index, query in enumerate(found):
        error = answers.get(index)
        status = 'not_observed' if error is None else 'ok' if error == '' else 'unresolved_temp_table' if TEMP_TABLE.search(error) else 'error'
        out.append({'file': query['file'], 'line': query['line'], 'status': status, 'error': error or ''})
    return out, skipped


def message(error):
    """The parser's own words: without the position prefix and the echoed query fragment."""
    lines = [l for l in error.splitlines() if l.strip()]
    first = re.sub(r'^\{\(\d+, ?\d+\)\}:\s*', '', lines[0]) if lines else ''
    return first.strip()
