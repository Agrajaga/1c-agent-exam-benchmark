#!/usr/bin/env python3
"""Compare immutable attempts, keeping execution, adapters and grading separate."""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from exam_bench.common import digest,tree_manifest,utc,write_json

VARIANT_FIELDS={'run_id','harness','profile_sha256','model_probe_ref','runtime_probe_ref','client','client_version','reasoning_effort'}


def load_attempt(run):
    run=Path(run).resolve()
    result=json.loads((run/'result.json').read_text())
    plan=json.loads((run/'plan.json').read_text())
    if digest(run/'plan.json')!=json.loads((run/'plan-integrity.json').read_text())['sha256']:
        raise ValueError('Frozen run plan changed: '+str(run))
    if tree_manifest(run/'artifacts')!=json.loads((run/'artifact-manifest.json').read_text()):
        raise ValueError('Frozen submission changed: '+str(run))
    integrity=run/'harness-integrity.json'
    unchanged=json.loads(integrity.read_text())['package_unchanged'] if integrity.exists() else None
    supplemental=run/'compatible-binding-v1/result.json'
    load=run/'native-load-unchanged/load-gate.json'
    return {'directory':str(run),'plan':plan,'result':result,'harness_package_unchanged':unchanged,
            'supplemental':json.loads(supplemental.read_text()) if supplemental.exists() else None,
            'native_load':json.loads(load.read_text()) if load.exists() else None}


def compare(attempts):
    if len(attempts)<2:raise ValueError('At least two attempts required')
    condition_sets=[{k:v for k,v in a['plan'].items() if k not in VARIANT_FIELDS} for a in attempts]
    keys=set().union(*(c.keys() for c in condition_sets))
    differences=sorted(k for k in keys if any(c.get(k)!=condition_sets[0].get(k) for c in condition_sets[1:]))
    return {'schema_version':1,'created_at':utc(),'same_conditions_except_harness':not differences,
            'different_condition_fields':differences,'attempts':attempts,
            'model_ranking_eligible':False,'whole_ticket_attested':False,
            'limits':['One attempt per harness, no causal estimate or model ranking.',
                      'Only BU02/BU10/BU12/BU13 have the implemented runtime grader.',
                      'The native client records the requested model but does not attest its effective ID.',
                      'Subscription charges are unknown; API figures use the pinned base-rate illustration.',
                      'Historical 900-second attempts have a different time budget.']}


def render(comparison):
    attempts=comparison['attempts']
    labels=[a['result']['harness'] for a in attempts]
    rows=[]
    def add(label,callback):rows.append((label,[callback(a) for a in attempts]))
    def seconds(a,key):
        v=a['result']['time'][key]
        return None if v is None else round(v/1000,3)
    add('Исход процесса',lambda a:a['result']['process']['status'])
    add('Лимит решения, с',lambda a:a['plan']['solve_timeout_seconds'])
    add('Решение, с',lambda a:seconds(a,'solve_ms'))
    add('Подготовка, с',lambda a:seconds(a,'prepare_ms'))
    add('Первичная проверка сдачи, с',lambda a:seconds(a,'grade_ms'))
    add('Дополнительная формальная приёмка, с',lambda a:round(a['supplemental']['evaluation_ms']/1000,3) if a.get('supplemental') else None)
    for title,key in [('Токены всего','total'),('Input','input'),('Из них cache','cached_input'),('Output','output'),('Из них reasoning','reasoning_output')]:
        add(title,lambda a,key=key:a['result']['metrics']['tokens'][key])
    add('Полнота usage',lambda a:a['result']['metrics']['tokens']['coverage'])
    add('Нативные субагенты',lambda a:a['result']['metrics']['agents']['spawned_total'])
    add('Вызовы MCP',lambda a:a['result']['metrics'].get('tools',{}).get('mcp_calls'))
    add('Пакет харнеса неизменён',lambda a:a['harness_package_unchanged'])
    add('Совместимость сдачи с адаптером',lambda a:a['result']['submission']['valid'])
    add('Частичная приёмка',lambda a:a['result']['grade']['status'])
    add('Дополнительная формальная приёмка',lambda a:(a.get('supplemental') or {}).get('status','not_run'))
    add('Загрузка исходников в чистую 1С',lambda a:(a.get('native_load') or {}).get('status','not_run'))
    add('API, условная иллюстрация USD',lambda a:a['result']['billing'].get('api_base_rate_illustration',{}).get('value'))
    add('Фактическое списание по подписке',lambda a:a['result']['billing']['actual_charge'])
    def value(v):
        if v is None:return 'нет данных'
        if isinstance(v,bool):return 'да' if v else 'нет'
        return str(v).replace('|','\\|').replace('\n',' ')
    text='# GPT-6.1 Sol: Unica 0.12.3 и skills Широкова\n\n'
    text+='Два последовательных прогона одного задания; по 30 минут, `medium`, Codex CLI 0.162.1, подписка, открытая сеть shell, нативное делегирование отключено. '
    text+='Общие закреплённые условия '+('совпадают' if comparison['same_conditions_except_harness'] else 'различаются: '+str(comparison['different_condition_fields']))+'.\n\n'
    text+='| Показатель | '+' | '.join(labels)+' |\n|---|'+ '|'.join('---' for _ in labels)+'|\n'
    for title,values in rows:text+='| '+title+' | '+' | '.join(value(v) for v in values)+' |\n'
    text+='\nCache входит в input, reasoning входит в output. Условная API-иллюстрация не является счётом; её тариф закреплён в планах/результатах. Квота аккаунта общая, её изменение нельзя приписать отдельной попытке.\n'
    for a in attempts:
        r=a['result'];run=Path(a['directory']);relative='../'+str(run.relative_to(ROOT))
        text+='\n## '+r['harness']+'\n\n'
        text+='[Отчёт]('+relative+'/report.md), [результат]('+relative+'/result.json), [исходники]('+relative+'/artifacts/src/), [план]('+relative+'/plan.json).\n'
        if r['submission']['error']:text+='\nОшибка адаптера: `'+r['submission']['error'].replace('`','')+'`.\n'
        text+='\n| Правило | Вердикт | Покрытие |\n|---|---|---|\n'
        for rule in r['grade']['rules']:
            text+='| '+rule['id']+' | '+rule['verdict']+' | '+rule.get('coverage','not_run')+' |\n'
        if a.get('supplemental'):
            text+='\nДополнительная проверка: формально нормализована только описательная метка хранения аналогов по объявленным типам метаданных; исходники, исходные привязки и первичный вердикт сохранены.\n\n'
            text+='| Правило | Вердикт | Покрытие |\n|---|---|---|\n'
            for rule in a['supplemental']['rules']:
                text+='| '+rule['id']+' | '+rule['verdict']+' | '+rule.get('coverage','not_run')+' |\n'
            text+='\n[Дополнительная приёмка]('+relative+'/compatible-binding-v1/result.json).\n'
        text+='\nПравил вне выбранного профиля: '+str(len(r['grade'].get('uncovered_rule_ids',[])))+'. Невыполненная проверка не означает отсутствие раздела.\n'
    text+='\nПолный экзаменационный балл не определён. Старые 15-минутные попытки не входят в эту пару. Один прогон на харнес показывает наблюдения, но не устойчивый эффект харнеса.\n'
    text+='\nПубличный контракт разрешает свободное описание `analogs.mode`, а первичный адаптер ожидает буквальную строку `information_register`. Это несоответствие контракта в стенде; отказ не доказывает дефект решения или отсутствие раздела. Прежний формальный классификатор определяет хранение по типу объекта и двум различным полям со ссылками на номенклатуру. Полные первичные результаты сохранены.\n'
    if comparison.get('campaign'):
        campaign=comparison['campaign'];excluded=campaign.get('excluded_attempt')
        if excluded:
            text+='\nПри первом запуске `'+excluded['run_id']+'` стенд передал runtime 0.12.3 схему подключения из 0.13. Попытка остановлена как инфраструктурно невалидная: '+str(excluded['solve_ms']/1000)+' с, '+str(excluded['tokens']['total'])+' учтённых токенов. Последний незавершённый запрос в этот счётчик не входит. Попытка исключена из пары, расход сохранён. Генератор настроек исправлен по версии, выполнена реальная applied-сборка каркаса; её свидетельство теперь обязательно для preflight 0.12.3.\n'
        quota=campaign.get('quota')
        if quota:text+='\nОбщая недельная квота аккаунта: '+str(quota['before_used_percent'])+'% → '+str(quota['after_used_percent'])+'% использовано. В неё входят контроллер, прерванная попытка и другие чаты; это не расход отдельного прогона и не денежная стоимость.\n'
        text+='\n[Доказательства кампании](../'+campaign['directory']+'/), [сбой первичного адаптера](../'+campaign['directory']+'/adapter-contract-mismatch.json).\n'
    return text


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--run',action='append',required=True)
    p.add_argument('--json',required=True);p.add_argument('--report',required=True);p.add_argument('--campaign')
    a=p.parse_args();comparison=compare([load_attempt(r) for r in a.run])
    if a.campaign:
        campaign=Path(a.campaign).resolve()
        if not campaign.is_relative_to(ROOT):raise ValueError('Campaign must be inside workspace')
        state=json.loads((campaign/'state.json').read_text())
        if [r['run_id'] for r in state['runs']]!=[r['result']['run_id'] for r in comparison['attempts']]:raise ValueError('Campaign/run mismatch')
        extra={'directory':str(campaign.relative_to(ROOT)),'state':state,
               'excluded_attempt':json.loads((campaign/'excluded-attempt.json').read_text())}
        before=json.loads(json.loads((campaign/'quota-before.json').read_text())['content'][0]['text'])
        after=json.loads(json.loads((campaign/'quota-after-model-runs.json').read_text())['content'][0]['text'])
        b=before['rateLimitsByLimitId']['codex']['primary'];e=after['rateLimitsByLimitId']['codex']['primary']
        extra['quota']={'before_used_percent':b['usedPercent'],'after_used_percent':e['usedPercent'],
                        'window_duration_mins':b['windowDurationMins'],'attributable_to_individual_runs':False}
        comparison['campaign']=extra
    write_json(a.json,comparison)
    report=Path(a.report);report.parent.mkdir(parents=True,exist_ok=True);report.write_text(render(comparison))
    print(json.dumps({'same_conditions_except_harness':comparison['same_conditions_except_harness'],'report':str(report)},ensure_ascii=False))


if __name__=='__main__':main()
