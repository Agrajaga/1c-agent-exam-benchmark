"""Native calibration for query fields supplied by a table-valued parameter."""
import json
from pathlib import Path

from . import queries
from .common import tree_manifest, write_json
from .observer import inject
from .platform import OneC
from .workspaces import case_workspace

VALID = ('ВЫБРАТЬ Сотрудник, Месяц ПОМЕСТИТЬ ВТ ИЗ &Периоды КАК Т; '
         'ВЫБРАТЬ ВТ.Сотрудник, ВТ.Месяц ИЗ ВТ КАК ВТ')
INVALID = VALID.replace('Сотрудник, Месяц', 'ОтсутствующееПоле, Месяц', 1)


def run(starter_source, starter_dt, binary, root):
    """On 1C, check the parser and actual execution on good and deliberately bad input."""
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    scratch = root / 'query-source'
    module = scratch / 'CommonModules/QueryCalibration/Ext/Module.bsl'
    module.parent.mkdir(parents=True)
    module.write_text('Процедура Контроль()\n А = Новый Запрос(%s);\n Б = Новый Запрос(%s);\nКонецПроцедуры\n'
                      % (queries.literal(VALID), queries.literal(INVALID)), encoding='utf-8')
    before = tree_manifest(scratch)
    # The same observer that the grader runs, plus independent execution on a freshly constructed table.
    probe = '''
    Таблица = Новый ТаблицаЗначений;
    Таблица.Колонки.Добавить("Сотрудник", Новый ОписаниеТипов("Строка"));
    Таблица.Колонки.Добавить("Месяц", Новый ОписаниеТипов("Дата"));
    Запрос = Новый Запрос(@VALID@); Запрос.УстановитьПараметр("Периоды", Таблица);
    Попытка
        Запрос.Выполнить(); Ответ.Вставить("valid_execution", "ok");
    Исключение
        Ответ.Вставить("valid_execution", КраткоеПредставлениеОшибки(ИнформацияОбОшибке()));
    КонецПопытки;
    Запрос = Новый Запрос(@INVALID@); Запрос.УстановитьПараметр("Периоды", Таблица);
    Попытка
        Запрос.Выполнить(); Ответ.Вставить("invalid_execution", "ok");
    Исключение
        Ответ.Вставить("invalid_execution", КраткоеПредставлениеОшибки(ИнформацияОбОшибке()));
    КонецПопытки;
'''.replace('@VALID@', queries.literal(VALID)).replace('@INVALID@', queries.literal(INVALID))
    observer = queries.code(scratch).replace('\tВозврат Ответ;\nКонецФункции', probe + '\tВозврат Ответ;\nКонецФункции')
    (root / 'platform-evidence').mkdir()
    with case_workspace(root / 'platform-evidence') as work:
        adapter = OneC(binary, work / 'platform', 180)
        observed = inject(starter_source, work / 'observed-src', observer)
        adapter.restore(work / 'ib', starter_dt)
        adapter.load(work / 'ib', observed)
        result_path = work / 'observations.json'
        adapter.command(['ENTERPRISE', '/F', work / 'ib', '/C', result_path], 'observe', confined=work)
        result = json.loads(result_path.read_text(encoding='utf-8-sig'))
    if 'error' in result:
        raise ValueError('Query parameter calibration failed: ' + result['error'])
    judged, skipped = queries.verdicts(scratch, result)
    invalid_error = result.get('invalid_execution', '')
    # Check the actual penalty decision, not only the parser classifier.
    from .penalties import assess
    task = Path(__file__).resolve().parents[1] / 'tasks/1c-platform-official-sample'
    catalogue = json.loads((task / 'private/official-assessment-mapping.json').read_text(encoding='utf-8'))
    policy = json.loads((task / 'private/owner-scoring-policy.json').read_text(encoding='utf-8'))
    good = assess([], scratch, {}, [], None, catalogue, policy, {}, {'query_texts': result})
    reqs = [{'id': 'BU03', 'section': 'BU', 'stand': {'grader_cases': ['chain']}},
            {'id': 'BU01', 'section': 'BU', 'stand': {'grader_cases': []}}]
    rules = [{'id': 'BU03', 'verdict': 'fail', 'reason': 'Ошибка выполнения'}, {'id': 'BU01', 'verdict': 'pass'}]
    error = '{ОбщийМодуль.Test.Модуль(1)}: Ошибка при вызове метода контекста (Выполнить): ' + invalid_error
    bad = assess(rules, scratch, {}, reqs, None, catalogue, policy, {},
                 {'query_texts': result, 'chain': {'posting_error': error}})
    good_status = good['statuses']['F1C-GEN12']['status']
    invalid_runtime_caught = any(f['penalty_id'] == 'F1C-GEN12' and f['proof_kind'] == 'runtime_error'
                                 for f in bad['findings'])
    passed = (len(judged) == 2 and not skipped
              and [q['status'] for q in judged] == ['unresolved_parameter_schema'] * 2
              and result.get('valid_execution') == 'ok'
              and bool(queries.MISSING_FIELD.search(invalid_error))
              and 'ОтсутствующееПоле' in invalid_error and tree_manifest(scratch) == before
              and good_status == 'not_assessed' and invalid_runtime_caught)
    summary = {'passed': bool(passed), 'parser_statuses': [q['status'] for q in judged],
               'valid_execution': result.get('valid_execution'), 'invalid_execution': invalid_error,
               'unproved_query_status': good_status, 'invalid_runtime_penalty_caught': invalid_runtime_caught,
               'readonly_sources_verified': tree_manifest(scratch) == before}
    write_json(root / 'summary.json', summary)
    return summary
