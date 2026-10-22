"""Pin a future attempt without making a model call."""
import argparse,json,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from exam_bench.common import digest,tree_manifest
from exam_bench.preflight import validate_plan,verify_calibration,verify_model_probe
from exam_bench.harness import profile_path,PROFILE_FILES
from exam_bench.materials import delivery_metadata
from exam_bench.runtime import machine_identity, require_execution_mode


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--run-id',required=True);p.add_argument('--model',required=True)
    p.add_argument('--reasoning',required=True,choices=('low','medium','high'))
    execution_policy_path=ROOT/'profiles/ai-exam-execution-policy.json'
    execution_policy=json.loads(execution_policy_path.read_text(encoding='utf-8'))
    p.add_argument('--series',required=True,choices=tuple(execution_policy['series']),help='exam: 5 hours as in the 1C exam; fast: 30 minutes');p.add_argument('--channel',required=True,choices=('subscription',))
    p.add_argument('--client',required=True);p.add_argument('--calibration',required=True)
    p.add_argument('--starter-dt',required=True);p.add_argument('--output',required=True)
    p.add_argument('--harness',default='none',choices=tuple(PROFILE_FILES));p.add_argument('--model-probe');p.add_argument('--runtime-probe')
    p.add_argument('--deadline',action='store_true',help='give the solver the absolute deadline (worker.json deadline_utc and a prompt line)')
    a=p.parse_args();out=Path(a.output)
    require_execution_mode()
    a.timeout=execution_policy['series'][a.series]['solve_timeout_seconds']
    if out.exists():raise FileExistsError(out)
    c=json.loads(Path(a.calibration).read_text(encoding='utf-8'));verify_calibration(c)
    if not a.model_probe and a.model not in c['models_probed']:raise ValueError('Selected model has no accepted native probe; no fallback')
    version=subprocess.run([a.client,'--version'],capture_output=True,text=True,check=True).stdout.strip()
    if version.startswith('codex-cli '):client,client_version='codex',version.removeprefix('codex-cli ')
    else:raise ValueError('Portable execution requires Codex CLI')
    task=ROOT/'tasks/1c-platform-official-sample'
    plan={'schema_version':1,'run_id':a.run_id,'client':client,'client_version':client_version,'machine':machine_identity(),
          'model':a.model,'reasoning_effort':a.reasoning,'billing_channel':a.channel,'harness':a.harness,
          'solve_timeout_seconds':a.timeout,'time_series':a.series,'stop_grace_seconds':3,
          'execution_policy_id':execution_policy['policy_id'],'execution_policy_sha256':digest(execution_policy_path),
          'purpose':'full_statement_technical_partial_attempt','acceptance_profile':c['profile_id'],
          'statement_sha256':digest(task/'public/statement.docx'),'public_inputs':tree_manifest(task/'public'),
          **delivery_metadata(task),
          'profile_sha256':digest(profile_path(a.harness)),
          'grader_sha256':digest(ROOT/'exam_bench/grader.py'),'starter_dt_sha256':digest(a.starter_dt),
          'delegation':'native_disabled','network_profile':'open-book_shell',
          'implementation_files':{'exam_bench/'+f.name:digest(f) for f in sorted((ROOT/'exam_bench').glob('*.py'))}}
    if a.deadline:plan['deadline_disclosed']=True
    if a.model_probe:
        plan['model_probe_ref']=a.model_probe;verify_model_probe(plan)
    if a.runtime_probe:plan['runtime_probe_ref']=a.runtime_probe
    if a.harness=='unica-0.12.3':
        from exam_bench.preflight import verify_runtime_capability
        verify_runtime_capability(plan)
    validate_plan(plan);out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('x', encoding='utf-8') as f:json.dump(plan,f,ensure_ascii=False,indent=2);f.write('\n')
    print('Plan pinned; no model request made: '+str(out))


if __name__=='__main__':main()
