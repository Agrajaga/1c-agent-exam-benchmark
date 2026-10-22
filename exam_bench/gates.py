"""Mandatory conditions checked before acceptance scenarios.

- starter_origin: the submission is built on the issued starter configuration (methodology М1.4).
- load_gate: the submission loads into a clean infobase restored from the starter (owner decision A11, М1.3).
- demo_data: the solver's declared demo-data procedure fills the infobase (owner decision A10, М4.32).
"""
import json
import re
from pathlib import Path

from .observer import inject
from .platform import OneC, PlatformError

_UUID = re.compile(r'<(\w+) uuid="([^"]+)"')


def configuration_identity(src):
    """Configuration UUID and {group/name: uuid} of top-level metadata objects of an exported source tree."""
    src = Path(src)
    root = _UUID.search((src / 'Configuration.xml').read_text(encoding='utf-8-sig'))
    objects = {}
    for path in src.glob('*/*.xml'):
        match = _UUID.search(path.read_text(encoding='utf-8-sig')[:4000])
        if match:
            objects[f'{path.parent.name}/{path.stem}'] = match.group(2)
    return root.group(2) if root else None, objects


def starter_origin(src, starter):
    """Same configuration identity as the starter. Removing starter objects is allowed (М1.5), so it is only reported."""
    uuid, objects = configuration_identity(src)
    kept = sorted(k for k, v in starter['objects_uuid'].items() if objects.get(k) == v)
    return {'passed': uuid == starter['configuration_uuid'], 'configuration_uuid': uuid,
            'starter_configuration_uuid': starter['configuration_uuid'],
            'starter_objects_kept': len(kept), 'starter_objects_total': len(starter['objects_uuid']),
            'starter_objects_missing': sorted(set(starter['objects_uuid']) - set(kept))}


def load_gate(src, starter_dt, binary, evidence):
    """Loadable submission, or which side failed. A restore failure is the stand's, a load failure the submission's."""
    evidence = Path(evidence)
    adapter = OneC(binary, evidence / 'platform', 180)
    try:
        adapter.restore(evidence / 'ib', starter_dt)
    except PlatformError as exc:
        return {'status': 'infrastructure_error', 'reason': 'Clean infobase from the starter could not be restored: ' + str(exc)}
    try:
        adapter.load(evidence / 'ib', src)
    except PlatformError as exc:
        return {'status': 'not_loadable', 'reason': 'Submitted configuration does not load into a clean infobase: ' + str(exc)}
    return {'status': 'loaded'}


def clients_gate(infobase, binary, evidence):
    """М2.3.1 barrier, owner decision A17: every module of the loaded submission compiles in the thin and web client.

    The platform's own syntax check (DESIGNER /CheckModules -ThinClient -WebClient) runs on the clean infobase of the
    load gate, without an observer. The issued starter passes it, so any error belongs to the submission. Running the
    interface itself is not reproduced: the stand has no web server, and the observer replaces the startup module.
    """
    evidence = Path(evidence)
    adapter = OneC(binary, evidence / 'platform', 300)
    try:
        adapter.command(['DESIGNER', '/F', Path(infobase).resolve(), '/CheckModules', '-ThinClient', '-WebClient'], 'check-clients')
        return {'status': 'compiles', 'scope': 'module compilation in thin and web client contexts; interface not run'}
    except PlatformError as exc:
        logs = sorted((evidence / 'platform').glob('*-check-clients.platform.log'))
        text = logs[-1].read_text(encoding='utf-8-sig', errors='replace') if logs else ''
        errors = [line.strip() for line in text.splitlines() if line.startswith('{')]
        if errors:
            return {'status': 'not_compiled', 'errors': errors[:50], 'reason': '%d ошибок компиляции в тонком или веб-клиенте' % len(errors)}
        return {'status': 'inconclusive', 'reason': str(exc)}


DEMO_OBSERVER = '''Функция Run() Экспорт
 Ошибка = "";
 Попытка
  {call}();
 Исключение
  Ошибка = ОписаниеОшибки();
 КонецПопытки;
 Документы_ = Новый Структура;
 Для Каждого Док Из Метаданные.Документы Цикл
  Запрос = Новый Запрос("ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК Всего, СУММА(ВЫБОР КОГДА Т.Проведен ТОГДА 1 ИНАЧЕ 0 КОНЕЦ) КАК Проведено ИЗ Документ." + Док.Имя + " КАК Т");
  Выборка = Запрос.Выполнить().Выбрать(); Выборка.Следующий();
  Документы_.Вставить(Док.Имя, Новый Структура("total,posted", Выборка.Всего, ?(Выборка.Проведено = NULL, 0, Выборка.Проведено)));
 КонецЦикла;
 Возврат Новый Структура("error,documents", Ошибка, Документы_);
КонецФункции
'''


def demo_data(src, binding, starter_dt, binary, evidence):
    """Run the declared demo-data procedure in a confined clean infobase and count posted documents per type."""
    declared = (binding.get('demo_data') or {}).get('procedure')
    if not declared:
        return {'status': 'not_declared', 'penalty': 'F1C-GEN32'}
    module, procedure = declared.split('.')[1:3]
    evidence = Path(evidence)
    adapter = OneC(binary, evidence / 'platform', 300)
    try:
        trusted = inject(src, evidence / 'observed-src', DEMO_OBSERVER.replace('{call}', f'{module}.{procedure}'))
        adapter.restore(evidence / 'ib', starter_dt)
        adapter.load(evidence / 'ib', trusted)
        result = evidence / 'demo.json'
        adapter.command(['ENTERPRISE', '/F', evidence / 'ib', '/C', result], 'demo-data', confined=evidence)
        data = json.loads(result.read_text(encoding='utf-8-sig'))
    except (PlatformError, OSError, ValueError) as exc:
        return {'status': 'inconclusive', 'reason': str(exc)}
    documents = data.get('documents') or {}
    posted = {k: v['posted'] for k, v in documents.items() if v.get('posted')}
    if data.get('error'):
        return {'status': 'failed', 'penalty': 'F1C-GEN32', 'reason': data['error'], 'documents': documents}
    if not posted:
        return {'status': 'empty', 'penalty': 'F1C-GEN32', 'reason': 'No posted documents after the demo-data procedure', 'documents': documents}
    # Completeness per exam section is not verified yet: any posted document is accepted as demo data.
    return {'status': 'present', 'posted_documents': posted, 'documents': documents, 'coverage': 'any_posted_document'}


def starter_for(starter_dt):
    """The registered starter whose DT this run used (starters/<id>/starter.json)."""
    from .common import digest
    sha = digest(starter_dt)
    for path in sorted(Path(__file__).parents[1].glob('starters/*/starter.json')):
        starter = json.loads(path.read_text(encoding='utf-8'))
        if starter['sha256'] == sha:
            return starter
    raise ValueError('Starter DT is not a registered starter')


def check_all(src, binding, starter_dt, binary, evidence):
    """Mandatory conditions before scenarios. Returns (gates, whole_ticket verdict or None, may_grade)."""
    evidence = Path(evidence)
    gates = {'starter_origin': starter_origin(src, starter_for(starter_dt))}
    if not gates['starter_origin']['passed']:
        return gates, {'verdict': 'not_passed', 'reason': 'not_built_on_issued_starter', 'source': 'М1.4'}, False
    gates['load'] = load_gate(src, starter_dt, binary, evidence / 'load')
    if gates['load']['status'] == 'not_loadable':
        return gates, {'verdict': 'not_passed', 'reason': 'configuration_not_loadable', 'source': 'М1.3, решение A11'}, False
    if gates['load']['status'] != 'loaded':
        return gates, None, False
    gates['clients'] = clients_gate(evidence / 'load' / 'ib', binary, evidence / 'clients')
    if gates['clients']['status'] == 'not_compiled':
        return gates, {'verdict': 'not_passed', 'reason': 'not_working_in_thin_or_web_client', 'source': 'М2.3.1, решение A17'}, False
    gates['demo_data'] = demo_data(src, binding, starter_dt, binary, evidence / 'demo')
    return gates, None, True
