import json
import subprocess
from pathlib import Path
from .common import digest,tree_manifest,grading_fingerprint
from .harness import profile_path,verify_package,is_unica,mcp_call_succeeded
from .materials import verify_delivery_plan

REQUIRED=('schema_version','run_id','client_version','model','billing_channel','harness','solve_timeout_seconds','stop_grace_seconds','purpose','acceptance_profile')


def validate_plan(plan):
    for k in REQUIRED:
        if k not in plan or plan[k] in (None,''):raise ValueError('Required plan value: '+k)
    if plan['schema_version']!=1:raise ValueError('Unsupported plan version/profile')
    profile_path(plan['harness'])
    if plan['billing_channel']!='subscription':raise ValueError('Only the tested subscription adapter is supported')
    if any(isinstance(plan[k],bool) or not isinstance(plan[k],int) or not 0<plan[k]<=18000 for k in ('solve_timeout_seconds','stop_grace_seconds')):raise ValueError('Invalid time limit')
    if plan['stop_grace_seconds']>10:raise ValueError('Stop grace exceeds tested bound')
    execution_policy_path=Path(__file__).parents[1]/'profiles/ai-exam-execution-policy.json'
    execution_policy=json.loads(execution_policy_path.read_text(encoding='utf-8'))
    if plan['solve_timeout_seconds']>execution_policy['maximum_ai_solve_timeout_seconds']:raise ValueError('AI solve limit exceeds the execution policy maximum')
    # Series are separate cohorts (owner decision A09): a plan names its series and uses exactly its limit.
    series=execution_policy.get('series',{})
    if 'time_series' in plan and (plan['time_series'] not in series or series[plan['time_series']]['solve_timeout_seconds']!=plan['solve_timeout_seconds']):raise ValueError('Plan time limit does not match its time series')
    if plan.get('execution_policy_sha256') is not None and (plan['execution_policy_sha256']!=digest(execution_policy_path) or plan.get('execution_policy_id')!=execution_policy['policy_id']):raise ValueError('Execution policy differs from pinned plan')
    if 'deadline_disclosed' in plan and not isinstance(plan['deadline_disclosed'],bool):raise ValueError('deadline_disclosed must be boolean')
    client=plan.get('client','codex')
    if client not in ('codex','claude'):raise ValueError('Unsupported client: '+str(client))
    if not isinstance(plan['model'],str) or not plan['model'].startswith('gpt-' if client=='codex' else 'claude-'):raise ValueError('Exact model ID required')
    # A clean agent on every attempt: memory off in the client and in the harness profile (execution policy v3).
    if client=='codex':
        from .codex import FEATURES
        memory_off='memories' in FEATURES
    else:
        from .claude import SETTINGS
        memory_off=SETTINGS.get('autoMemoryEnabled') is False
    if execution_policy.get('agent_memory',{}).get('mode')!='disabled' or not memory_off:raise ValueError('Agent memory must be disabled')
    if json.loads(profile_path(plan['harness']).read_text(encoding='utf-8')).get('memory') is not False:raise ValueError('Harness profile must disable memory')
    if not isinstance(plan['run_id'],str) or not all(c.isalnum() or c in '-_' for c in plan['run_id']):raise ValueError('Invalid run ID')
    return True


def main_gates(plan,task,client,starter,passport,calibration):
    validate_plan(plan)
    from .runtime import require_execution_mode, machine_identity
    mode=require_execution_mode()
    pp=json.loads(Path(passport).read_text(encoding='utf-8'));cc=json.loads(Path(calibration).read_text(encoding='utf-8'))
    if mode=='macos':
        cap=json.loads((Path(passport).parent/'solver-platform-bootstrap-capability-04.json').read_text(encoding='utf-8'))
        if cap['status']!='completed' or not cap['cache_mapping_unchanged']:raise ValueError('Solver cannot operate 1C inside its sandbox')
    elif plan.get('machine')!=machine_identity() or pp.get('machine')!=machine_identity() or cc.get('machine')!=machine_identity():
        raise ValueError('Plan, environment and calibration must be created for this machine and isolation mode')
    if plan['grader_sha256']!=cc['grader_sha256']:raise ValueError('Grader hash differs from the pinned plan')
    if not pp.get('runtime_probe_verified') or not pp.get('reset_verified'):raise ValueError('FR-01 environment has not passed runtime/reset')
    if tree_manifest(starter)!=tree_manifest(Path(passport).parent/'src-2'):raise ValueError('Run starter differs from verified starter')
    verify_calibration(cc)
    root=Path(__file__).parents[1]
    expected={'exam_bench/'+p.name:digest(p) for p in (root/'exam_bench').glob('*.py')}
    if plan.get('implementation_files')!=expected:raise ValueError('Run implementation differs from pinned plan')
    if plan['acceptance_profile']!=cc['profile_id']:raise ValueError('Acceptance profile differs from calibration')
    # Hashes committed to the plan before solve, never filled from the result later.
    if plan['statement_sha256']!=digest(Path(task)/'public'/'statement.docx'):raise ValueError('Statement hash mismatch')
    verify_delivery_plan(plan, task)
    if plan['profile_sha256']!=digest(profile_path(plan['harness'])):raise ValueError('Harness profile hash mismatch')
    if is_unica(plan['harness']):
        verify_package(plan['harness'])
        probe=(root/plan['model_probe_ref']).resolve().parent
        if json.loads((probe/'plan.json').read_text(encoding='utf-8'))['harness']!=plan['harness']:raise ValueError('Unica has no native integration probe')
        events=[json.loads(line) for line in (probe/'raw/stdout.jsonl').read_text(encoding='utf-8').splitlines()]
        root_tool='unica.view' if plan['harness']=='unica-0.13.0' else 'unica.project.status'
        if plan.get('client','codex')=='claude':
            if not claude_mcp_call_succeeded(events,root_tool):raise ValueError('Unica root unavailable in native client')
        else:
            views=[e['item'] for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='mcp_tool_call' and e['item'].get('tool')==root_tool and e['item'].get('status')=='completed']
            if not any(mcp_call_succeeded(v) for v in views):raise ValueError('Unica root unavailable in native client')
        if plan['harness']=='unica-0.12.3':verify_runtime_capability(plan)
    elif plan['harness'] in ('bsl-ls-1.1.0-rc.6','bsl-analyzer-0.3.2','rlm-tools-bsl-1.43.0','code-index-1.9.0'):
        from .stdio_harnesses import call_succeeded as stdio_call_succeeded
        verify_package(plan['harness'])
        probe=(root/plan['model_probe_ref']).resolve().parent
        if json.loads((probe/'plan.json').read_text(encoding='utf-8'))['harness']!=plan['harness']:raise ValueError('Harness has no native integration probe')
        events=[json.loads(line) for line in (probe/'raw/stdout.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
        if not stdio_call_succeeded(events,plan['harness'],plan.get('client','codex')):raise ValueError('Harness MCP tool unavailable in native client')
    elif plan['harness']=='mcp-toolkit-1.9.0':
        from .mcp_toolkit import call_succeeded
        verify_package(plan['harness'])
        probe=(root/plan['model_probe_ref']).resolve().parent
        if json.loads((probe/'plan.json').read_text(encoding='utf-8'))['harness']!=plan['harness']:raise ValueError('1C MCP Toolkit has no native integration probe')
        events=[json.loads(line) for line in (probe/'raw/stdout.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
        if not call_succeeded(events,'execute_query',plan.get('client','codex')):raise ValueError('1C MCP Toolkit query unavailable in native client')
    elif plan['harness']=='shirokov-skills':
        verify_package(plan['harness'])
        probe=(root/plan['model_probe_ref']).resolve().parent
        if json.loads((probe/'plan.json').read_text(encoding='utf-8'))['harness']!=plan['harness']:raise ValueError('Skills harness has no native integration probe')
        receipt=json.loads((probe/'skills-capability.json').read_text(encoding='utf-8'))
        if not receipt.get('accepted') or receipt.get('profile_sha256')!=plan['profile_sha256']:
            raise ValueError('Skills harness capability absent or stale')
    version=subprocess.run([str(client),'--version'],capture_output=True,text=True,check=True).stdout.strip()
    expected_version='codex-cli '+plan['client_version'] if plan.get('client','codex')=='codex' else plan['client_version']+' (Claude Code)'
    if version!=expected_version:raise ValueError('Native client version mismatch')
    if plan.get('model_probe_ref'):
        verify_model_probe(plan)
    elif plan['model'] not in cc['models_probed']:raise ValueError('Selected model has no accepted live probe')
    return {'environment_sha256':digest(passport),'calibration_sha256':digest(calibration),'plan_valid':True,'runtime_ready':True,'partial_grader_calibrated':True,'statement_unchanged':True,'model_requested_only':True,'isolation_mode':mode,'comparison_eligible':mode!='dedicated-host'}


def claude_mcp_call_succeeded(events,tool):
    """A Claude Code stream with a successful call of the Unica MCP tool: mcp__unica__<tool> (dots may become _),
    whose result payload is a JSON object with ok = true."""
    names={'mcp__unica__'+tool,'mcp__unica__'+tool.replace('.','_')}
    ids={b.get('id') for e in events if e.get('type')=='assistant' for b in (e.get('message') or {}).get('content') or []
         if isinstance(b,dict) and b.get('type')=='tool_use' and b.get('name') in names}
    for e in events:
        if e.get('type')!='user':continue
        for b in (e.get('message') or {}).get('content') or []:
            if not (isinstance(b,dict) and b.get('type')=='tool_result' and b.get('tool_use_id') in ids and not b.get('is_error')):continue
            content=b.get('content')
            texts=[content] if isinstance(content,str) else [c.get('text') for c in content or [] if isinstance(c,dict) and c.get('type')=='text']
            for text in texts:
                try:payload=json.loads(text)
                except (TypeError,ValueError):continue
                if isinstance(payload,dict) and payload.get('ok') is True:return True
    return False


def verify_calibration(calibration):
    if not calibration.get('accepted') or calibration.get('grader_sha256')!=digest(Path(__file__).parent/'grader.py') or calibration.get('implementation_files')!=grading_fingerprint() or not calibration.get('readonly_sources_verified'):
        raise ValueError('FR-05 calibration absent or stale')


def verify_model_probe(plan):
    root=Path(__file__).parents[1];probe=(root/plan['model_probe_ref']).resolve()
    if not probe.is_relative_to(root/'.local/runs'):raise ValueError('Invalid model probe reference')
    result=json.loads(probe.read_text(encoding='utf-8'));p=json.loads((probe.parent/'plan.json').read_text(encoding='utf-8'))
    if plan.get('machine') is not None and p.get('machine')!=plan['machine']:
        raise ValueError('Native model probe was made on a different machine/isolation mode')
    if result['process']['status']!='completed' or result['model']['requested']!=plan['model'] or any(p[k]!=plan[k] for k in ('model','client_version','billing_channel')) or (probe.parent/'artifacts/probe.txt').read_bytes()!=b'READY':
        raise ValueError('Selected model/client/channel has no successful native probe')


def verify_runtime_capability(plan):
    from .codex import project_configuration_fingerprint
    root=Path(__file__).parents[1]
    ref=plan.get('runtime_probe_ref')
    if not ref:raise ValueError('Unica 0.12.3 requires a real runtime/config capability check')
    path=(root/ref).resolve()
    if not path.is_relative_to(root/'.local'):raise ValueError('Invalid runtime capability reference')
    receipt=json.loads(path.read_text(encoding='utf-8'))
    if receipt.get('accepted') is not True or receipt.get('profile_sha256')!=plan['profile_sha256'] or receipt.get('project_configuration_sha256')!=project_configuration_fingerprint(plan['harness']):
        raise ValueError('Runtime capability absent or stale')
    evidence=(path.parent/receipt['evidence_ref']).resolve()
    if not evidence.is_relative_to(path.parent) or digest(evidence)!=receipt['evidence_sha256']:
        raise ValueError('Runtime capability evidence changed')
    reply=json.loads(evidence.read_text(encoding='utf-8'))['reply']
    if reply.get('ok') is not True or reply.get('cache',{}).get('mode')!='applied' or 'BuildCompleted' not in reply.get('cache',{}).get('events',[]):
        raise ValueError('Runtime build execution not proved')
