import json
from decimal import Decimal


def token_breakdown(tokens):
    """Cache is a subset of input; missing cache never means zero cache."""
    incoming, cached = tokens.get('input'), tokens.get('cached_input')
    valid = lambda v: isinstance(v, int) and not isinstance(v, bool) and v >= 0
    fresh = incoming - cached if valid(incoming) and valid(cached) and cached <= incoming else None
    return {**tokens, 'fresh_input': fresh}


def normalize(lines, delegation_disabled=False):
    events=[]; seen=set(); turns=[]; children=set(); models=set(); limitations=[]; malformed=0
    for sequence, line in enumerate(lines, 1):
        try:
            event=json.loads(line)
        except (ValueError, TypeError):
            malformed+=1;continue
        if not isinstance(event,dict):
            malformed+=1;continue
        # Native IDs, not equal JSON bodies, define retransmissions. No ID => a new event.
        identity=event.get('event_id')
        if not isinstance(identity,(str,int)):identity=None
        if identity is not None and identity in seen:
            continue
        if identity is not None: seen.add(identity)
        events.append({'source_sequence':sequence, 'native':event})
        kind=event.get('type')
        if kind=='turn.completed' and isinstance(event.get('usage'),dict):
            turns.append(event['usage'])
        if kind=='agent.spawned' and event.get('session_id'):
            children.add(event['session_id'])
        if event.get('model'): models.add(event['model'])
    keys={'input':'input_tokens','cached_input':'cached_input_tokens','output':'output_tokens','reasoning_output':'reasoning_output_tokens'}
    totals={k:sum(t[v] for t in turns) if turns and all(isinstance(t.get(v),int) and not isinstance(t[v],bool) and t[v]>=0 for t in turns) else None for k,v in keys.items()}
    totals['total']=totals['input']+totals['output'] if totals['input'] is not None and totals['output'] is not None else None
    if not turns:limitations.append('No completed turn usage; incomplete attempts may have unreported spend')
    if malformed:limitations.append(f'{malformed} unparseable output lines')
    unsupported_scope=any(u.get('usage_scope') not in (None,'root') for u in turns)
    if unsupported_scope:
        limitations.append('Non-root usage scope requires a provider-specific normalizer')
        totals={k:None for k in totals}
    if totals['input'] is not None and totals['cached_input'] is not None and totals['cached_input']>totals['input']:
        limitations.append('Invalid cached/input relationship');totals={k:None for k in totals}
    if not models:limitations.append('Native exec JSON stream did not attest effective model')
    # This adapter handles only the no-delegation pilot. Do not invent a complete tree.
    if children or not delegation_disabled:
        limitations.append('Child usage/lifecycle coverage not supported by this adapter')
    return {'events':events,'tokens':token_breakdown({**totals,'coverage':'unsupported_scope' if unsupported_scope else 'reported_completed_root_turns' if turns else 'unavailable'}),'models_observed':sorted(models),'model_provenance':'client_reported' if models else 'requested_only','agents':{'spawned_total':0 if delegation_disabled and not children else None,'observed_children':len(children),'coverage':'native_delegation_disabled' if delegation_disabled and not children else 'partial'},'limitations':list(dict.fromkeys(limitations))}


def api_estimate(tokens, tariff):
    if not tariff or any(tokens.get(k) is None for k in ('input','cached_input','output')):
        return None
    value=((Decimal(tokens['input'])-Decimal(tokens['cached_input']))*Decimal(tariff['input_per_million'])+Decimal(tokens['cached_input'])*Decimal(tariff['cached_input_per_million'])+Decimal(tokens['output'])*Decimal(tariff['output_per_million']))/Decimal(1000000)
    return str(value)


def native_session_usage(home):
    """Fresh native session counters are cumulative: take the last value, never sum snapshots."""
    from pathlib import Path
    selected=[]
    for path in sorted(Path(home).glob('sessions/**/*.jsonl')):
        session=None;last=None;events=[]
        for seq,line in enumerate(path.read_text(errors='replace', encoding='utf-8').splitlines(),1):
            try:e=json.loads(line)
            except ValueError:continue
            if e.get('type')=='session_meta':session=e.get('payload',{}).get('id')
            if e.get('type')=='event_msg' and e.get('payload',{}).get('type')=='token_count':
                info=e['payload'].get('info')
                if isinstance(info,dict) and isinstance(info.get('total_token_usage'),dict):
                    last=info['total_token_usage'];events.append({'session_id':session,'source_sequence':seq,'timestamp':e.get('timestamp'),'total_token_usage':last})
        if last is not None:selected.append({'session_id':session,'last':last,'events':events})
    if len(selected)!=1:return {'tokens':None,'counter_events':[],'reason':'Expected exactly one native root session counter'}
    one=selected[0];u=one['last'];mapping={'input':'input_tokens','cached_input':'cached_input_tokens','output':'output_tokens','reasoning_output':'reasoning_output_tokens'}
    tokens={k:u.get(v) if isinstance(u.get(v),int) and not isinstance(u.get(v),bool) and u[v]>=0 else None for k,v in mapping.items()}
    tokens['total']=tokens['input']+tokens['output'] if tokens['input'] is not None and tokens['output'] is not None else None
    if tokens['input'] is not None and tokens['cached_input'] is not None and tokens['cached_input']>tokens['input']:return {'tokens':None,'counter_events':one['events'],'reason':'Invalid native token counter'}
    tokens['coverage']='last_reported_native_session_counter; unreported in-flight request excluded'
    return {'tokens':token_breakdown(tokens),'counter_events':one['events'],'reason':None}
