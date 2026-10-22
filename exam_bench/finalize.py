import json,time
from pathlib import Path
from .common import digest,write_json
from .grader import grade,PROFILE
from .gates import check_all,starter_for
from .penalties import assess
from .report import save
from .telemetry import api_estimate


def finalize(run,task,starter_dt,binary,tariff=None):
    run=Path(run);result=json.loads((run/'result.json').read_text(encoding='utf-8'))
    start=time.monotonic()
    rules=json.loads((Path(task)/'private'/'rules.json').read_text(encoding='utf-8'))['rules']
    if result['submission']['valid']:
        binding=json.loads((run/'artifacts'/'binding.json').read_text(encoding='utf-8'))
        # Mandatory conditions first: starter origin (М1.4), loadability (A11), demo data (A10).
        gates,ticket_verdict,may_grade=check_all(run/'artifacts'/'src',binding,starter_dt,binary,run/'gates')
        result['gates']=gates
        if may_grade:
            g=grade(run/'artifacts'/'src',binding,starter_dt,binary,run/'grade')
            result['grade']={'scope':'technical_partial','whole_ticket':'not_evaluated','status':g['status'],'rules':g['rules'],'profile':PROFILE['id'],'profile_sha256':digest(Path(__file__).parent/'grader.py'),'evidence_ref':'grade/grade.json'}
            # Official penalties proved so far and the score they imply (owner policy, minimum penalty).
            task_root=Path(task)
            result['assessment']=assess(g['rules'],run/'artifacts'/'src',binding,json.loads((task_root/'checks.json').read_text(encoding='utf-8'))['requirements'],
                                        starter_for(starter_dt),json.loads((task_root/'private'/'official-assessment-mapping.json').read_text(encoding='utf-8')),
                                        json.loads((task_root/'private'/'owner-scoring-policy.json').read_text(encoding='utf-8')),gates,g['observations'])
        else:
            result['grade'].update(status=ticket_verdict['reason'] if ticket_verdict else 'infrastructure_error',profile=PROFILE['id'],
                                   whole_ticket=ticket_verdict['verdict'] if ticket_verdict else 'not_evaluated',ticket_verdict=ticket_verdict,
                                   rules=[{'id':r,'verdict':'not_run','reason':'Mandatory condition not met'} for r in PROFILE['rules']])
    else:
        result['grade'].update(status='adapter_inconclusive' if not result['submission'].get('adapter_compatible',True) else 'invalid_submission',profile=PROFILE['id'],rules=[{'id':r,'verdict':'not_run','reason':'No valid ready submission'} for r in PROFILE['rules']])
    checked={r['id'] for r in result['grade']['rules']}
    result['grade']['uncovered_rule_ids']=[r['id'] for r in rules if r['id'] not in checked]
    result['time']['grade_ms']=round((time.monotonic()-start)*1000)
    if result.get('client')=='claude' and result['billing'].get('api_equivalent') is not None:
        # Claude Code reports the session cost at API rates itself; the OpenAI tariff file does not apply.
        result['billing']['api_base_rate_illustration']={'value':result['billing']['api_equivalent'],'currency':'USD','source':'client-reported total_cost_usd'}
    elif tariff:
        rates=json.loads(Path(tariff).read_text(encoding='utf-8'));value=api_estimate(result['metrics']['tokens'],rates)
        result['billing']['api_base_rate_illustration']={'value':value,'currency':rates['currency'],'tariff_sha256':digest(tariff),'assumptions':rates['estimate_limits']}
    write_json(run/'result.json',result);save(result,run/'report.md')
    return result
