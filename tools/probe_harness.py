#!/usr/bin/env python3
"""Short native Codex/Claude Code model, MCP and skill integration probe, never an exam solve."""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from exam_bench import claude,codex
from exam_bench.common import digest,write_json
from exam_bench.harness import profile_path,mcp_call_succeeded
from exam_bench.isolation import wrapped
from exam_bench.preflight import claude_mcp_call_succeeded
from exam_bench.process import supervise

PROMPTS={
 'unica-0.12.3':'Это только проверка окружения, не решение экзамена. Не открывай условие экзамена. Прочитай worker.json и client-home/skills/unica/meta-info/SKILL.md. Через подключенный MCP unica выполни unica.project.status для текущего workspace; затем unica.meta.info для Catalog.Номенклатура из sourceSet main. Используй схемы подключённых инструментов. Если оба вызова успешны, создай out/probe.txt с байтами READY без перевода строки. Не изменяй исходники, skills, конфигурацию или правила. При ошибке зафиксируй её и завершись. Дополнительных разрешений не запрашивай.',
 'shirokov-skills':'Это только проверка окружения, не решение экзамена. Не открывай условие экзамена. Прочитай worker.json и навык meta-info (.codex/skills/meta-info/SKILL.md). Выполни авторский Python-скрипт meta-info для out/src/Catalogs/Номенклатура.xml в режиме overview, сохрани его stdout без редактирования в out/meta-info.txt. Выполни проверку импорта lxml, PIL, psutil и запиши их версии в out/python-deps.json. Проверь импорт playwright через Node в директории .codex/skills/web-test/scripts; браузер не запускай. Если все команды успешны, создай out/probe.txt с байтами READY без перевода строки. Не изменяй исходники, skills, конфигурацию или правила. При ошибке зафиксируй её и завершись. Дополнительных разрешений не запрашивай.'}
MODEL_PROMPT='Read worker.json. Create out/probe.txt containing exactly READY. Do not solve the exam. End the session.'
# The exam itself places no tool configuration (the solver writes it from worker.json); the probe hands it over.
PROJECT='workPath: .local/unica-work\nformat: DESIGNER\nsource-set:\n  - name: main\n    type: CONFIGURATION\n    path: out/src\n'
# Claude Code loads skills natively from its isolated user skill root, so the prompts name skills, not Codex paths.
CLAUDE_PROMPTS={
 'none':MODEL_PROMPT,
 'unica-0.13.0':'Это только проверка окружения, не решение экзамена. Не открывай условие экзамена. Прочитай worker.json. Создай в корне workspace v8project.yaml:\n'+PROJECT+'Через подключенный MCP unica выполни unica.view с пустыми аргументами; затем unica.view по адресу main:Catalog.Номенклатура. Используй схемы подключённых инструментов. Если оба вызова успешны, создай out/probe.txt с байтами READY без перевода строки. Кроме v8project.yaml не изменяй исходники, skills, конфигурацию или правила. При ошибке зафиксируй её и завершись. Дополнительных разрешений не запрашивай.',
 'unica-0.12.3':PROMPTS['unica-0.12.3'].replace('client-home/skills/unica/meta-info/SKILL.md','навык meta-info. Создай в корне workspace v8project.yaml:\n'+PROJECT.replace('format: DESIGNER\n','format: DESIGNER\nbuilder: DESIGNER\n')).replace('Не изменяй','Кроме v8project.yaml не изменяй'),
 'shirokov-skills':PROMPTS['shirokov-skills']}
TOOLKIT_PROMPT=('Это только проверка окружения, не решение экзамена. Не открывай условие экзамена. Прочитай worker.json. '
                'Через подключенный MCP onec выполни execute_query с запросом ВЫБРАТЬ ПЕРВЫЕ 1 Н.Наименование ИЗ Справочник.Номенклатура КАК Н; '
                'затем get_metadata без фильтра. Если оба вызова успешны, создай out/probe.txt с байтами READY без перевода строки. '
                'Не изменяй исходники, skills, конфигурацию, базу или правила. При ошибке зафиксируй её и завершись. Дополнительных разрешений не запрашивай.')
CLAUDE_PROMPTS['mcp-toolkit-1.9.0']=TOOLKIT_PROMPT
PROMPTS['mcp-toolkit-1.9.0']=TOOLKIT_PROMPT
HEAD='Это только проверка окружения, не решение экзамена. Не открывай условие экзамена. Прочитай worker.json. '
TAIL=' Если вызовы успешны, создай out/probe.txt с байтами READY без перевода строки. Не изменяй исходники, конфигурацию или правила. При ошибке зафиксируй её и завершись. Дополнительных разрешений не запрашивай.'
STDIO_PROMPTS={
 'bsl-ls-1.1.0-rc.6':HEAD+'Через подключенный MCP bsl-language-server зарегистрируй папку out/src (абсолютный путь) инструментом register_workspace_folder, затем выполни analyze_file для out/src/DataProcessors/ЗаполнениеГрафика/Ext/ObjectModule.bsl.'+TAIL,
 'bsl-analyzer-0.3.2':HEAD+'Через подключенный MCP bsl-analyzer получи инструментом metadata описание Catalog.Номенклатура; если ответ «загружается», повтори через несколько секунд.'+TAIL,
 'rlm-tools-bsl-1.43.0':HEAD+'Через подключенный MCP rlm-tools-bsl открой сессию rlm_start по абсолютному пути out/src с domains=["структура"], выполни rlm_execute с кодом, который печатает список справочников, и закрой сессию rlm_end.'+TAIL,
 'code-index-1.9.0':HEAD+'Через подключенный MCP code-index выполни get_object_structure для Справочник.Номенклатура.'+TAIL}
for _name,_prompt in STDIO_PROMPTS.items():
    CLAUDE_PROMPTS[_name]=_prompt;PROMPTS[_name]=_prompt
CLIENTS={'codex':(codex,ROOT/'.local/clients/codex-0.162.1/node_modules/@openai/codex-darwin-arm64/vendor/aarch64-apple-darwin/bin/codex',Path.home()/'.codex/auth.json'),
         'claude':(claude,Path.home()/'.local/bin/claude',Path.home()/'.config/1c-exam-bench/claude-oauth-token')}
UNICA_TOOLS={'unica-0.13.0':('unica.view',),'unica-0.12.3':('unica.project.status','unica.meta.info')}
for name in ('unica-0.14.0-rc.1', 'unica-0.15.0-rc.1'):
    PROMPTS[name] = CLAUDE_PROMPTS[name] = CLAUDE_PROMPTS['unica-0.13.0']
    UNICA_TOOLS[name] = ('unica.view',)

# The agents of the stand: client version, exact model ID and reasoning effort of every probe and run.
MODELS={'codex':('0.162.1','gpt-6.1-sol'),'claude':('2.1.290','claude-opus-5-5')}


def write_probe_plan(path,run_id,client,harness):
    from exam_bench.materials import delivery_metadata
    from exam_bench.common import tree_manifest
    task=ROOT/'tasks/1c-platform-official-sample';version,model=MODELS[client]
    plan={'schema_version':1,'run_id':run_id,'client':client,'client_version':version,'model':model,'reasoning_effort':'medium',
          'billing_channel':'subscription','harness':harness,'solve_timeout_seconds':300,'stop_grace_seconds':3,
          'purpose':'integration_probe_not_exam_attempt' if harness=='none' else 'harness_mcp_skill_probe_not_exam_attempt',
          'acceptance_profile':'not_applicable_probe','delegation':'native_disabled',**delivery_metadata(task),'public_inputs':tree_manifest(task/'public')}
    path.parent.mkdir(parents=True,exist_ok=True)
    write_json(path,plan)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--harness',required=True,choices=tuple(CLAUDE_PROMPTS))
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--verify-only',action='store_true',help='Recheck frozen evidence without a model request')
    parser.add_argument('--client',choices=tuple(MODELS),help='Create the probe plan for this agent if it does not exist yet')
    args=parser.parse_args()
    run=ROOT/'.local/runs'/args.run_id
    plan_file=ROOT/'.local/plans'/(args.run_id+'.json')
    if not plan_file.exists() and args.client:write_probe_plan(plan_file,args.run_id,args.client,args.harness)
    plan=json.loads(plan_file.read_text())
    if plan['harness']!=args.harness:raise ValueError('Probe harness mismatch')
    kind=plan.get('client','codex')
    module,client,auth=CLIENTS[kind]
    prompt=CLAUDE_PROMPTS[args.harness] if kind=='claude' else PROMPTS.get(args.harness,MODEL_PROMPT)
    result=json.loads((run/'result.json').read_text()) if args.verify_only else module.start(plan,run,ROOT/'.local/environment-verified-v1/src-2',ROOT/'tasks/1c-platform-official-sample',
                 client,auth,starter_dt=ROOT/'.local/sources/new_carcass_8_3_25_1445.dt',prompt=prompt)
    ready=(run/'artifacts/probe.txt').is_file() and (run/'artifacts/probe.txt').read_bytes()==b'READY'
    if result['process']['status']!='completed' or not ready:raise SystemExit('Native integration probe did not succeed; see '+str(run))
    ws=Path(json.loads((run/'workspace.json').read_text())['path'])
    if args.harness=='shirokov-skills':
        harness=json.loads((run/'harness.json').read_text())
        import os
        env={**os.environ,**harness['worker_env'],'TMPDIR':str(ws/'tmp')}
        script=ws/'.codex/skills/meta-info/scripts/meta-info.py'
        # Independently execute the unchanged author's parser under the same
        # filesystem sandbox and compare its stdout to the agent's saved output.
        outcome=supervise(wrapped(['/opt/homebrew/bin/python3.12',str(script),'-ObjectPath',str(ws/'out/src/Catalogs/Номенклатура.xml'),'-Mode','overview'],ws),ws,env,'',30,3,run/'independent-meta-info')
        observed=(run/'independent-meta-info/stdout.jsonl').read_bytes()
        saved=(run/'artifacts/meta-info.txt').read_bytes()
        unchanged=json.loads((run/'harness-integrity.json').read_text())['package_unchanged']
        receipt={'accepted':outcome['exit_code']==0 and observed==saved and unchanged,
                 'profile_sha256':digest(profile_path(args.harness)), 'native_result_sha256':digest(run/'result.json'),
                 'author_script_matches_independent_execution':observed==saved,
                 'package_unchanged':unchanged,'scope':'native skill/metadata/dependency integration; not exam correctness'}
        write_json(run/'skills-capability.json',receipt)
        if not receipt['accepted']:raise SystemExit('Independent author-skill check failed')
    elif args.harness in STDIO_PROMPTS:
        from exam_bench.stdio_harnesses import call_succeeded as stdio_call_succeeded
        events=[json.loads(line) for line in (run/'raw/stdout.jsonl').read_text().splitlines() if line.strip()]
        receipt={'accepted':stdio_call_succeeded(events,args.harness,kind),
                 'profile_sha256':digest(profile_path(args.harness)),'native_result_sha256':digest(run/'result.json'),
                 'cleanup':json.loads((run/'runtime-cleanup.json').read_text()),
                 'scope':'single published tool as a stdio MCP server over out/src; not exam correctness'}
        write_json(run/'mcp-capability.json',receipt)
        if not receipt['accepted']:raise SystemExit('Harness MCP call not proved successful')
    elif args.harness=='mcp-toolkit-1.9.0':
        from exam_bench.mcp_toolkit import call_succeeded
        events=[json.loads(line) for line in (run/'raw/stdout.jsonl').read_text().splitlines() if line.strip()]
        receipt={'accepted':all(call_succeeded(events,name,kind) for name in ('execute_query','get_metadata')),
                 'profile_sha256':digest(profile_path(args.harness)),'native_result_sha256':digest(run/'result.json'),
                 'launch':json.loads((run/'mcp-toolkit/launch.json').read_text()),
                 'cleanup':json.loads((run/'runtime-cleanup.json').read_text()),
                 'scope':'1C client session with the published processing and MCP over HTTP; not exam correctness'}
        write_json(run/'mcp-capability.json',receipt)
        if not receipt['accepted']:raise SystemExit('1C MCP Toolkit calls not proved successful')
    elif args.harness in UNICA_TOOLS:
        events=[json.loads(line) for line in (run/'raw/stdout.jsonl').read_text().splitlines()]
        calls=[e['item'] for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='mcp_tool_call']
        succeeded=(lambda name:claude_mcp_call_succeeded(events,name)) if kind=='claude' else (lambda name:any(c.get('tool')==name and mcp_call_succeeded(c) for c in calls))
        receipt={'accepted':all(succeeded(name) for name in UNICA_TOOLS[args.harness]),
                 'profile_sha256':digest(profile_path(args.harness)), 'native_result_sha256':digest(run/'result.json'),
                 'scope':'native MCP and metadata integration; not exam correctness'}
        write_json(run/'mcp-capability.json',receipt)
        if not receipt['accepted']:raise SystemExit('Native Unica MCP calls not proved successful')
    print(json.dumps({'run_id':args.run_id,'accepted':True,'tokens':result['metrics']['tokens']},ensure_ascii=False))


if __name__=='__main__':main()
