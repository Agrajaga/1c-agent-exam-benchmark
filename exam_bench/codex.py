"""Single client adapter. No implicit retry, fallback, or delegate."""
import json
import hashlib
import xml.etree.ElementTree as ET
import os
import shutil
import tempfile
from .locking import file_lock as bootstrap_lock
from .runtime import platform_binary, cache_directory, child_environment, machine_identity, require_execution_mode, settings
from pathlib import Path
from .common import digest, tree_manifest, utc, write_json
from .isolation import wrapped, verify
from .process import supervise
from .submission import extra_sections, freeze, validate,UnsupportedBindings
from .telemetry import normalize,native_session_usage
from .harness import configure,tool_usage,stop_owned_runtimes,is_unica
from datetime import datetime, timedelta, timezone
from .materials import DEFAULT_PROMPT, solver_prompt, verify_delivery_plan
from .mcp_toolkit import NAME as TOOLKIT, URL as TOOLKIT_URL
from .stdio_harnesses import is_stdio_harness

FEATURES=('apps','browser_use','browser_use_external','browser_use_full_cdp_access','computer_use','hooks','memories','multi_agent','plugin_hooks','plugins','shell_snapshot','skill_search','workspace_dependencies','remote_plugin','plugin_sharing','image_generation','in_app_browser','in_app_chat','in_app_local_automation','multi_agent_v2','unbounded_connection_retries','skill_mcp_dependency_install')


def portable_harness_run(run):
    return (Path(run)/'portable-harness.json').is_file()


def public_plan_values(plan):
    return {k:plan[k] for k in ('run_id','client_version','model','reasoning_effort','billing_channel','harness','solve_timeout_seconds','stop_grace_seconds','delegation','input_revision','methodical_requirements_disclosed','deadline_disclosed') if k in plan}


def worker_document(plan,ws,harness,cache_paths,has_dt,starter_dt_given=None):
    """The worker.json the solver reads: public plan values, platform paths and the additional tools.

    starter_dt_given: the starter dump is delivered since open-methodics-v5; earlier runs had only the infobase."""
    starter_dt_given=has_dt if starter_dt_given is None else starter_dt_given
    return {'schema_version':1,'native_system_skills':['review-agent','skill-creator','plugin-creator','skill-installer','openai-docs','imagegen'],
            'network_profile':'open-book',**public_plan_values(plan),'platform_binary':platform_binary(False),'client_home_isolated':True,
            'infobase':str(ws/'ib') if has_dt else None,**({'starter_dt':str(ws/'starter.dt')} if starter_dt_given else {}),
            'platform_cache_namespaces':cache_paths,'additional_tools':harness,
            **({'environment':environment_description(ws,has_dt)} if starter_dt_given else {}),
            # Written right before the solve starts: the limit cannot end later than this moment.
            **({'deadline_utc':(datetime.now(timezone.utc)+timedelta(seconds=plan['solve_timeout_seconds'])).isoformat(timespec='seconds')} if plan.get('deadline_disclosed') else {})}


def environment_description(ws,has_dt):
    """Everything a solver needs to configure its own tools: platform, infobase, sources and their format."""
    binary=platform_binary(False)
    return {'platform':{'version':settings().get('platform_version'),'directory':str(Path(binary).parent) if binary else None,'designer_and_client':binary,
                        'ibcmd':str(Path(binary).with_name('ibcmd.exe' if os.name=='nt' else 'ibcmd')) if binary else None},
            'infobase':{'path':str(ws/'ib'),'connection_string':'File="%s";'%(ws/'ib'),'authentication':'none'} if has_dt else None,
            'starter':{'dump':str(ws/'starter.dt'),'sources':str(ws/'starter'),'read_only':True} if has_dt else None,
            'sources':{'path':str(ws/'out'/'src'),'format':'Configurator XML export (Конфигурация → Выгрузить конфигурацию в файлы)',
                       'configuration_xml':str(ws/'out'/'src'/'Configuration.xml')},
            'output':str(ws/'out'),'temporary_directory':str(ws/'tmp')}


def worker_environment(ws,runtime,harness):
    # zsh here-documents use TMPPREFIX, independently of TMPDIR. Keep both
    # inside this worker instead of granting write access to host /tmp.
    env=child_environment(ws)
    env['CODEX_HOME']=str(runtime)
    env.update(harness.get('worker_env',{}))
    if 'HOME' in os.environ:env['HOME']=os.environ['HOME']
    return env


def project_configuration(harness,workspace,has_infobase):
    """Use the schema of the pinned runtime, rather than the current plugin."""
    main='workPath: .local/unica-work\nformat: DESIGNER\n'
    if harness=='unica-0.12.3':main+='builder: DESIGNER\n'
    main+='source-set:\n  - name: main\n    type: CONFIGURATION\n    path: out/src\n'
    local=None
    if has_infobase:
        connection=json.dumps('File='+str(workspace/'ib'))
        if harness=='unica-0.12.3':
            local='infobase:\n  connection: '+connection+'\n'
            local+='tools:\n  platform:\n    path: "/opt/1cv8/8.3.27.2074"\n    version: "8.3.27.2074"\n    strict: true\n'
        else:local='infobases:\n  origin:\n    connection: '+connection+'\n'
    return main,local


def project_configuration_fingerprint(harness):
    parts=project_configuration(harness,Path('/BENCHMARK_WORKER'),True)
    return hashlib.sha256(json.dumps(parts,ensure_ascii=False).encode()).hexdigest()


def prepare(plan, run, starter, task, client, auth_seed, starter_dt=None):
    from .preflight import validate_plan
    validate_plan(plan)
    if Path(run).exists():
        raise FileExistsError(run)
    require_execution_mode()
    if plan.get('machine') is not None and plan['machine']!=machine_identity():
        raise ValueError('Machine settings differ from the pinned plan')
    from .portable_harnesses import available as portable_harness
    if settings()['isolation']!='macos' and plan['harness']!='none' and not portable_harness(plan['harness']):
        raise ValueError('Portable Codex execution currently supports harness=none; extra harnesses require separate porting')
    run=Path(run).resolve()
    run.mkdir(parents=True,exist_ok=False) # idempotency reservation before any paid call
    verify_delivery_plan(plan, task)
    implementation=run/'implementation';implementation.mkdir()
    for source in Path(__file__).parent.glob('*.py'):
        shutil.copyfile(source,implementation/source.name)
    write_json(run/'implementation-manifest.json',tree_manifest(implementation))
    ws=Path(tempfile.mkdtemp(prefix='1c-exam-worker-')).resolve()
    write_json(run/'workspace.json',{'path':str(ws)})
    (ws/'tmp').mkdir();(ws/'out').mkdir()
    cache_paths=[]
    if starter_dt is not None:
        from .platform import OneC
        cache_parent=cache_directory()
        cache_parent.mkdir(parents=True,exist_ok=True)
        # Shared host lock, not one lock per project/workspace. Failure remains
        # closed if another non-benchmark application changes the same cache.
        lock_path=cache_parent/'.exam-benchmark-bootstrap.lock'
        with bootstrap_lock(lock_path):
            before=set(cache_parent.iterdir())
            adapter=OneC(platform_binary(),run/'worker-bootstrap',90)
            adapter.restore(ws/'ib',starter_dt)
            adapter.export(ws/'ib',ws/'bootstrap-export')
            cache_paths=[str(p.resolve()) for p in set(cache_parent.iterdir())-before if p.is_dir()]
            write_json(run/'worker-bootstrap/cache-allocation.json',{'before':[str(p) for p in sorted(before)],
                       'new_directories':cache_paths,'shared_host_lock':str(lock_path)})
            if settings()['isolation']!='dedicated-host' and len(cache_paths)!=1:raise ValueError('Cannot uniquely identify the new worker platform cache namespace; check platform_cache in the machine settings')
        write_json(ws/'platform-cache-grant.json',{'paths':cache_paths,'owner':'new benchmark worker only'})
        shutil.rmtree(ws/'bootstrap-export')
    shutil.copytree(starter,ws/'starter')
    if starter_dt is not None:
        # The starter as issued on the exam: the infobase dump with its data (catalogs, chart of accounts).
        shutil.copyfile(starter_dt,ws/'starter.dt')
    shutil.copytree(starter,ws/'out/src')
    # No ready tool configuration (v8project.yaml) is placed: worker.json lists every path and version the solver needs
    # to configure its own tools. project_configuration stays for the harness capability probe only.
    shutil.copytree(task/'public',ws/'task')
    runtime=ws/'client-home';runtime.mkdir(mode=0o700)
    # All external integrations are disabled regardless of the user's native defaults.
    config='web_search = "disabled"\napproval_policy = "never"\nsandbox_mode = "danger-full-access"\n'
    config+='[features]\n'+''.join(f'{k} = false\n' for k in FEATURES)
    config+='[sandbox_workspace_write]\nnetwork_access = false\n'
    (runtime/'skills').mkdir();(runtime/'rules').mkdir()
    harness,harness_config=configure(plan['harness'],ws,runtime,run)
    (runtime/'config.toml').write_text(config+harness_config, encoding='utf-8')
    # The client home is created empty for this attempt: no memory or personal instructions may reach the agent.
    leftovers=[p.name for p in runtime.iterdir() if p.name.lower() in ('memories','memory','agents.md','agents.override.md')]
    if leftovers:raise ValueError('Client home must hold no memory or personal instructions: '+', '.join(leftovers))
    write_json(ws/'worker.json',worker_document(plan,ws,harness,cache_paths,starter_dt is not None))
    write_json(run/'harness.json',harness)
    public=tree_manifest(ws/'task')
    public={'task/'+k:v for k,v in public.items()}
    public.update({'starter/'+k:v for k,v in tree_manifest(ws/'starter').items()})
    if (ws/'starter.dt').is_file():public['starter.dt']=digest(ws/'starter.dt')
    write_json(run/'input-manifest.json',public)
    repo=Path(__file__).resolve().parents[1]
    probe=verify(ws,task/'private'/'fixtures.json',[task/'private'/'rules.json',repo/'exam_bench'/'grader.py',repo/'.local'/'runs',Path(auth_seed),Path.home()/'.codex'/'auth.json',Path.home()/'.ssh'])
    write_json(run/'isolation.json',probe)
    argv=[str(client),'exec','--model',plan['model'],'--json','--cd',str(ws),'--skip-git-repo-check','--ignore-user-config','--ignore-rules','--strict-config','--sandbox','danger-full-access','-c','web_search="disabled"','-c','approval_policy="never"']
    for f in FEATURES:argv+=['--disable',f]
    if harness.get('portable'):
        from .portable_harnesses import codex_overrides
        argv+=codex_overrides(harness,ws,runtime)
    if is_unica(plan['harness']) and not harness.get('portable'):
        mcp=json.loads((run/'unica-mcp-registration.json').read_text(encoding='utf-8'))
        for k in ('command','args','cwd','startup_timeout_sec'):argv+=['-c','mcp_servers.unica.'+k+'='+json.dumps(mcp[k])]
        for k,v in mcp['env'].items():argv+=['-c','mcp_servers.unica.env.'+k+'='+json.dumps(v)]
    if is_stdio_harness(plan['harness']) and not harness.get('portable'):
        from .stdio_harnesses import codex_overrides
        argv+=codex_overrides(plan['harness'],ws)
    if plan['harness']==TOOLKIT:
        argv+=['-c','mcp_servers.onec.url='+json.dumps(TOOLKIT_URL),'-c','mcp_servers.onec.startup_timeout_sec=60','-c','mcp_servers.onec.tool_timeout_sec=600']
    # A selected harness must be ready for the first turn. Optional MCP servers
    # can miss Codex's startup grace and silently disappear from the tool catalog.
    for server in harness.get('mcp_servers',[]):
        argv+=['-c','mcp_servers.'+server+'.required=true']
    if plan.get('reasoning_effort'):argv+=['-c','model_reasoning_effort='+json.dumps(plan['reasoning_effort'])]
    argv+=['-']
    # HOME is inherited as required by the native runtime; user config/skills are isolated with CODEX_HOME.
    env=worker_environment(ws,runtime,harness)
    if starter_dt is not None:
        # Prove that this worker can operate 1C before seeding credentials or
        # spending the solve budget. The source export is not delivered.
        export=ws/'platform-capability-export';export.mkdir()
        capability=supervise(wrapped([platform_binary(),'DESIGNER','/F',str(ws/'ib'),
                              '/DumpConfigToFiles',str(export),'/DisableStartupMessages',
                              '/DisableStartupDialogs','/Out',str(ws/'platform-capability.log')],ws),
                              ws,env,'',90,3,run/'worker-platform-capability')
        capability['configuration_exported']=(export/'Configuration.xml').is_file()
        write_json(run/'worker-platform-capability.json',capability)
        if capability['status']!='completed' or not capability['stop_confirmed'] or not capability['configuration_exported']:
            raise ValueError('1C is unavailable inside the selected worker boundary; see worker-platform-capability.json')
        shutil.rmtree(export)
    write_json(run/'plan.json',plan)
    write_json(run/'plan-integrity.json',{'sha256':digest(run/'plan.json')})
    write_json(run/'client-profile.json',{'argv':argv,'disabled_features':FEATURES,'web_search':'disabled','shell_network_access':True,'external_network_profile':'open-book','code_home':str(runtime),'native_version':plan['client_version'],'models_fallback':False,
               # Known gap: the client reads auth.json from the worker home, so solver shell commands can read it too. Use a dedicated benchmark account.
               'credential_readable_by_solver':True})
    # Seed credentials last: failed preparation never leaves an authenticated worker.
    auth=runtime/'auth.json'
    try:
        auth.touch(mode=0o600)
        shutil.copyfile(auth_seed,auth)
        auth.chmod(0o600)
    except BaseException:
        auth.unlink(missing_ok=True)
        raise
    return ws,argv,env,public


def start(plan, run, starter, task, client, auth_seed, prompt=None, starter_dt=None):
    import time
    machine=machine_identity()
    prep=time.monotonic()
    ws,argv,env,public=prepare(plan,run,Path(starter),Path(task),client,auth_seed,starter_dt)
    run=Path(run).resolve();prep_ms=round((time.monotonic()-prep)*1000)
    start_at=utc()
    default=solver_prompt(plan)
    write_json(run/'solver-prompt.json', {'prompt': prompt or default, 'input_revision': plan['input_revision']})
    cleanup=None
    try:
        if portable_harness_run(run):
            from .portable_harnesses import launch as launch_portable
            launch_portable(ws,env,run)
        elif plan['harness']==TOOLKIT:
            from .mcp_toolkit import launch
            launch(ws,env,run)
        elif is_stdio_harness(plan['harness']):
            from .stdio_harnesses import launch as launch_stdio
            launch_stdio(plan['harness'],ws,env,run)
        outcome=supervise(wrapped(argv,ws),ws,env,prompt or default,plan['solve_timeout_seconds'],plan['stop_grace_seconds'],run/'raw')
    finally:
        # Also clean up when a harness fails before the first model request.
        (ws/'client-home'/'auth.json').unlink(missing_ok=True)
        if portable_harness_run(run):
            from .portable_harnesses import stop as stop_portable
            cleanup=stop_portable(ws)
        elif plan['harness']==TOOLKIT:
            from .mcp_toolkit import stop
            cleanup=stop(ws,plan['stop_grace_seconds'])
        elif is_stdio_harness(plan['harness']):
            from .stdio_harnesses import stop as stop_stdio
            cleanup=stop_stdio(plan['harness'],ws,env,plan['stop_grace_seconds'])
        elif is_unica(plan['harness']):
            cleanup=stop_owned_runtimes(ws,plan['stop_grace_seconds'])
        if cleanup is not None:write_json(run/'runtime-cleanup.json',cleanup)
    if cleanup is not None:outcome['stop_confirmed']=outcome['stop_confirmed'] and cleanup['stop_confirmed']
    write_json(run/'process.json',outcome)
    parsed=normalize((run/'raw'/'stdout.jsonl').read_text(errors='replace', encoding='utf-8').splitlines(),delegation_disabled=True)
    counters=native_session_usage(ws/'client-home')
    write_json(run/'native-usage-counters.json',counters['counter_events'])
    if counters['tokens'] is not None:
        if parsed['tokens']['total'] is not None and parsed['tokens']['total']!=counters['tokens']['total']:
            parsed['limitations'].append('Native cumulative session and exec final usage disagree; counters kept separately')
        elif parsed['tokens']['total'] is None:
            parsed['tokens']=counters['tokens']
    metrics={k:v for k,v in parsed.items() if k!='events'}
    if machine['isolation']=='dedicated-host':
        metrics['limitations'].append('Dedicated-host execution: no outer filesystem/network sandbox; not eligible for comparison')
    metrics['tools']=tool_usage(parsed['events'])
    if portable_harness_run(run):
        from .portable_harnesses import integrity
        unchanged=integrity(ws,run)
        write_json(run/'harness-integrity.json',{'package_unchanged':unchanged})
        if not unchanged:metrics['limitations'].append('Solver changed the pinned native harness package')
    elif is_unica(plan['harness']):
        unchanged=tree_manifest(ws/'harness/unica')==json.loads((run/'unica-package-manifest.json').read_text(encoding='utf-8'))
        write_json(run/'harness-integrity.json',{'package_unchanged':unchanged})
        if not unchanged:metrics['limitations'].append('Solver changed the pinned harness package')
    elif is_stdio_harness(plan['harness']):
        unchanged=tree_manifest(ws/'harness'/plan['harness'])==json.loads((run/'harness-package-manifest.json').read_text(encoding='utf-8'))
        write_json(run/'harness-integrity.json',{'package_unchanged':unchanged})
        if not unchanged:metrics['limitations'].append('Solver changed the pinned harness package')
    elif plan['harness']==TOOLKIT:
        unchanged=tree_manifest(ws/'harness/mcp-toolkit')==json.loads((run/'mcp-toolkit-package-manifest.json').read_text(encoding='utf-8'))
        write_json(run/'harness-integrity.json',{'package_unchanged':unchanged})
        if not unchanged:metrics['limitations'].append('Solver changed the pinned harness package')
    elif plan['harness']=='shirokov-skills':
        unchanged=tree_manifest(ws/'.codex')==json.loads((run/'shirokov-package-manifest.json').read_text(encoding='utf-8'))
        write_json(run/'harness-integrity.json',{'package_unchanged':unchanged})
        if not unchanged:metrics['limitations'].append('Solver changed the pinned harness package')
    write_json(run/'events.json',parsed['events'])
    error=None;adapter_compatible=True;ignored=[]
    try:ignored=extra_sections(validate(ws,public,require_ready=True))
    except UnsupportedBindings as exc:
        error=str(exc);adapter_compatible=False
    except (ValueError,KeyError,OSError,TypeError,json.JSONDecodeError,ET.ParseError) as exc:error=str(exc)
    manifest=None
    if outcome['stop_confirmed']:
        try:manifest=freeze(ws,run/'artifacts')
        except ValueError as exc:error=str(exc)
    else:error='Stopping descendants was not confirmed; artifacts were not frozen'
    # The solver's own reading of ambiguous places; recorded, never part of the verdict.
    from .interpretations import read as read_interpretations
    interpretations=read_interpretations(run/'artifacts') if manifest is not None else {'status':'missing','items':[]}
    result={'schema_version':1,'run_id':plan['run_id'],'interpretations':{'status':interpretations['status'],'count':len(interpretations['items'])},'started_at':start_at,'process':outcome,'time':{'prepare_ms':prep_ms,'solve_ms':outcome['elapsed_ms'],'grade_ms':None},'model':{'requested':plan['model'],'observed':metrics['models_observed'],'provenance':metrics['model_provenance']},'harness':plan['harness'],'network_profile':'open-book shell','metrics':metrics,'billing':{'channel':plan['billing_channel'],'currency':None,'actual_charge':None,'api_equivalent':None,'subscription_allocation':None,'quota_before':None,'quota_after':None,'reason':'Provider billing receipt, quota and tariff snapshot unavailable'},'submission':{'valid':error is None,'adapter_compatible':adapter_compatible,'error':error,'ignored_binding_sections':ignored,'files':len(manifest) if manifest is not None else None},'grade':{'scope':'technical_partial','whole_ticket':'not_evaluated','rules':[],'status':'not_run'},'comparison_eligible':False}
    result['machine']=machine
    result['machine_settings_unchanged']=machine_identity()==machine
    result['isolation_verified']=machine['isolation'] in ('macos','bubblewrap') and result['machine_settings_unchanged']
    write_json(run/'result.json',result)
    return result
