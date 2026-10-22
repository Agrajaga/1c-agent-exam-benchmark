from pathlib import Path
from .telemetry import token_breakdown


def render(result):
    def value(x):return 'нет данных' if x is None else str(x)
    tokens=token_breakdown(result['metrics']['tokens']);bill=result['billing'];proc=result['process']
    rows=[('Запрошенная модель',result['model']['requested']),('Подтверждение модели',result['model']['provenance']),('Харнес',result['harness']),('Профиль сети',result.get('network_profile','см. план запуска')),('Исход клиента',proc['status']),('Время решения, мс',result['time']['solve_ms']),('Время подготовки, мс',result['time']['prepare_ms']),('Время проверки, мс',result['time']['grade_ms']),('Входные токены',tokens['input']),('Из них кэшированные',tokens['cached_input']),('Выходные токены',tokens['output']),('Из них reasoning',tokens['reasoning_output']),('Всего токенов',tokens['total']),('Полнота usage',tokens['coverage']),('Решающие субагенты',result['metrics']['agents']['spawned_total']),('Канал оплаты',bill['channel']),('Фактическое списание',bill['actual_charge']),('API-эквивалент',bill['api_equivalent']),('Сдача пригодна',result['submission']['valid']),('Общий вердикт по билету',result['grade']['whole_ticket']),('Сопоставление моделей допустимо',result['comparison_eligible'])]
    text=f"# Попытка {result['run_id']}\n\n| Показатель | Значение |\n|---|---|\n"+''.join(f'| {k} | {value(v)} |\n' for k,v in rows)
    text+=f"\nНекешированный вход: {value(tokens['fresh_input'])}. Всего = вход + выход; кеш входит во вход, reasoning входит в выход.\n"
    text+='\nЧастичная техническая проверка не удостоверяет сдачу экзамена. Неизвестные метрики и стоимость не заменены нулём.\n'
    if result['submission']['error']:text+='\nОшибка сдачи: '+result['submission']['error']+'\n'
    if result.get('diagnostic'):
        text+='\nПосле прогона поля проверены отдельно в настоящей 1С. Наблюдаемые имена: '+', '.join(result['diagnostic']['observed_examples'])+'. Доказательство: `'+result['diagnostic']['evidence_ref']+'`. Это подтверждение причины отказа; исходная сдача и вердикт сохранены.\n'
    if bill.get('quota_before') and bill.get('quota_after'):
        text+='\nОбщая квота аккаунта: '+str(bill['quota_before']['window']['used_percent'])+'% → '+str(bill['quota_after']['window']['used_percent'])+'% использовано. В неё входят контроллер и другие задачи; разницу нельзя приписать этой попытке или пересчитать в её стоимость.\n'
    if result.get('billing',{}).get('api_base_rate_illustration'):
        estimate=result['billing']['api_base_rate_illustration']
        text+='\nИллюстрация по базовым API-тарифам: '+value(estimate['value'])+' '+estimate['currency']+'. Это условная оценка для обычного контекста без доплаты за запись кеша; полный API-эквивалент и списание по подписке не подтверждены.\n'
    if result['grade'].get('uncovered_rule_ids'):
        text+='\nПравил вне выбранных проверок: '+str(len(result['grade']['uncovered_rule_ids']))+'. Профиль BU02 охватывает только проведение и остатки; отчёт и остальные пути чтения не входят в него. Фактическое выполнение проверок указано в таблице.\n'
    if result['grade']['rules']:
        text+='\n| Правило | Вердикт | Покрытие |\n|---|---|---|\n'+''.join(f"| {r['id']} | {r['verdict']} | {r.get('coverage','not_run')} |\n" for r in result['grade']['rules'])
    if result['metrics']['limitations']:text+='\nОграничения:\n\n'+''.join('- '+s+'\n' for s in result['metrics']['limitations'])
    if result.get('experiment_limits'):text+='\nОграничения эксперимента:\n\n'+''.join('- '+s+'\n' for s in result['experiment_limits']['reasons'])
    return text


def save(result,path):Path(path).write_text(render(result),encoding='utf-8')
