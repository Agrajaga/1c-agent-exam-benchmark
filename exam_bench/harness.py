"""Pinned additional tools; no access to curator or user-wide plugin state."""
import json,shutil,os,signal,subprocess,time
from pathlib import Path
from .common import tree_manifest,digest,write_json

ROOT=Path(__file__).parents[1]
PROFILE_FILES={'none':'none-macos.json','unica-0.13.0':'unica-0.13.0-macos.json',
               'unica-0.12.3':'unica-0.12.3-macos.json','shirokov-skills':'shirokov-skills-macos.json',
               'mcp-toolkit-1.9.0':'mcp-toolkit-1.9.0-macos.json',
               **{n:n+'-macos.json' for n in ('bsl-ls-1.1.0-rc.6','bsl-analyzer-0.3.2','rlm-tools-bsl-1.43.0','code-index-1.9.0')}}


def is_unica(name):
    return name in ('unica-0.12.3','unica-0.13.0','unica-0.14.0-rc.1')


def mcp_call_succeeded(item):
    """Accept native structured output or the older JSON-in-text envelope."""
    if item.get('status')!='completed' or item.get('error') is not None:return False
    result=item.get('result') or {}
    structured=result.get('structured_content')
    if structured is not None:return isinstance(structured,dict) and structured.get('ok') is True
    blocks=result.get('content') or []
    if len(blocks)!=1 or blocks[0].get('type')!='text':return False
    try:payload=json.loads(blocks[0]['text'])
    except (KeyError,TypeError,json.JSONDecodeError):return False
    return isinstance(payload,dict) and payload.get('ok') is True


def profile_path(name):
    from .portable_harnesses import available,profile
    if available(name):return profile(name)
    if name not in PROFILE_FILES:raise ValueError('Unsupported harness: '+name)
    if name=='none':
        from .runtime import settings
        if settings()['isolation']!='macos':return ROOT/'profiles/none-portable.json'
    return ROOT/'profiles'/PROFILE_FILES[name]


def verify_package(name='unica-0.13.0'):
    from .portable_harnesses import available,verify
    if available(name):return verify(name)
    profile_path(name) # Reject unknown names before resolving filesystem paths.
    root=ROOT/'.local/harnesses'/name
    package=root/('codex-python-package' if name=='shirokov-skills' else 'package')
    profile=json.loads(profile_path(name).read_text(encoding='utf-8'))
    if digest(root/'package-manifest.json')!=profile['package_manifest_sha256']:
        raise ValueError('Harness package manifest differs from pinned profile')
    expected=json.loads((root/'package-manifest.json').read_text(encoding='utf-8'))
    if tree_manifest(package)!=expected:raise ValueError('Pinned harness package changed: '+name)
    if is_unica(name):
        meta=json.loads((package/'.codex-plugin/plugin.json').read_text(encoding='utf-8'))
        if meta['version']!=name.removeprefix('unica-'):raise ValueError('Unica version differs from requested '+name)
    elif name in ('bsl-ls-1.1.0-rc.6','bsl-analyzer-0.3.2','rlm-tools-bsl-1.43.0','code-index-1.9.0'):
        if json.loads((root/'provenance.json').read_text(encoding='utf-8'))['commit']!=profile['source_commit']:raise ValueError('Harness release differs from pinned profile')
    elif name=='mcp-toolkit-1.9.0':
        provenance=json.loads((root/'provenance.json').read_text(encoding='utf-8'))
        if provenance['commit']!=profile['source_commit'] or digest(package/'MCP_Toolkit_macos.epf')!=profile['release_asset_sha256']:
            raise ValueError('1C MCP Toolkit release differs from pinned profile')
    elif name=='shirokov-skills':
        provenance=json.loads((root/'provenance.json').read_text(encoding='utf-8'))
        if provenance['commit']!=profile['source_commit']:raise ValueError('Shirokov skills commit differs from pinned profile')
        if digest(root/'python-manifest.json')!=profile['python_dependencies_manifest_sha256'] or digest(root/'node-manifest.json')!=profile['node_dependencies_manifest_sha256']:
            raise ValueError('Harness dependency manifests differ from pinned profile')
        if tree_manifest(root/'python-site-packages')!=json.loads((root/'python-manifest.json').read_text(encoding='utf-8')):
            raise ValueError('Pinned Shirokov Python dependencies changed')
        if tree_manifest(root/'node-modules')!=json.loads((root/'node-manifest.json').read_text(encoding='utf-8')):
            raise ValueError('Pinned Shirokov Node dependencies changed')
    return root


def configure(name,ws,runtime,run):
    if name=='none':return {'name':'none','mcp_servers':[],'additional_skills':[]},''
    from .portable_harnesses import available,configure as configure_portable
    if available(name) and name!='mcp-toolkit-1.9.0':return configure_portable(name,ws,runtime,run)
    if name=='shirokov-skills':return configure_shirokov(ws,runtime,run)
    from .stdio_harnesses import is_stdio_harness
    if is_stdio_harness(name):
        from .stdio_harnesses import configure as configure_stdio
        return configure_stdio(name,ws,runtime,run,'codex')[0],''
    if name=='mcp-toolkit-1.9.0':
        from .mcp_toolkit import configure as configure_toolkit
        harness,_=configure_toolkit(ws,runtime,run,'codex')
        return harness,harness.pop('codex_config')
    if not is_unica(name):raise ValueError('Unsupported harness')
    source=verify_package(name);package=ws/'harness/unica'
    shutil.copytree(source/'package',package)
    shutil.copytree(source/'client-home/unica',runtime/'unica',ignore=shutil.ignore_patterns('.transactions'))
    shutil.copytree(package/'skills',runtime/'skills/unica')
    for directory in ('references','third-party'):
        shutil.copytree(package/directory,runtime/'skills'/directory)
    # Skill relative references ../../references stay valid in the isolated skill root.
    skills=sorted(p.parent.name for p in (package/'skills').glob('*/SKILL.md'))
    state=runtime/'unica/provider-state';state.mkdir(parents=True,exist_ok=True)
    spec=json.loads((package/'.mcp.json').read_text(encoding='utf-8'))['mcpServers']['unica']
    mcp={'command':spec['command'],'args':spec['args'],'cwd':str(ws),
         'startup_timeout_sec':spec['startup_timeout_sec'],
         'env':{'CLAUDE_PLUGIN_ROOT':str(package),'CLAUDE_PROJECT_DIR':str(ws),
                'UNICA_HOST_CONTEXT_REQUIRED':'1','UNICA_RUNTIME_CACHE_DIR':str(runtime/'unica/runtimes'),
                'UNICA_PROVIDER_STATE_DIR':str(state),'CODEX_HOME':str(runtime),
                'GIT_CONFIG_GLOBAL':'/dev/null','GIT_CONFIG_SYSTEM':'/dev/null','TMPDIR':str(ws/'tmp'),
                'UNICA_DAEMON_IDLE_GRACE_MS':'1000'}}
    # JSON arrays/strings are valid TOML values; command/args come from the published package.
    config='\n[mcp_servers.unica]\n'+''.join(k+' = '+json.dumps(mcp[k])+'\n' for k in ('command','args','cwd','startup_timeout_sec'))
    config+='[mcp_servers.unica.env]\n'+''.join(k+' = '+json.dumps(v)+'\n' for k,v in mcp['env'].items())
    write_json(run/'unica-mcp-registration.json',mcp)
    write_json(run/'unica-package-manifest.json',tree_manifest(package))
    return {'name':name,'version':name.removeprefix('unica-'),'registration':'published MCP plus exact skills; isolated native plugin loader disabled','mcp_servers':['unica'],'additional_skills':skills,'runtime_manifest_sha256':digest(package/'runtime-manifest.json')},config


def configure_shirokov(ws,runtime,run):
    source=verify_package('shirokov-skills')
    package=source/'codex-python-package'
    # Keep the author's relative .codex/skills/... commands usable. The isolated
    # CODEX_HOME supplies native discovery; it points to the same project tree.
    shutil.copytree(package/'.codex',ws/'.codex')
    shutil.copytree(source/'node-modules',ws/'.codex/skills/web-test/scripts/node_modules')
    (runtime/'skills/shirokov').symlink_to(ws/'.codex/skills',target_is_directory=True)
    shutil.copytree(source/'python-site-packages',runtime/'python-site-packages')
    binary=runtime/'bin';binary.mkdir()
    for name in ('python','python3'):
        path=binary/name
        path.write_text('#!/bin/sh\nexec /opt/homebrew/bin/python3.12 "$@"\n', encoding='utf-8')
        path.chmod(0o755)
    if (ws/'ib').exists():
        write_json(ws/'.v8-project.json',{'v8path':'/opt/1cv8/8.3.27.2074/1cv8',
                   'databases':[{'id':'origin','name':'Benchmark worker','type':'file','path':str(ws/'ib'),
                                 'aliases':['origin','dev'],'configSrc':str(ws/'out/src')}]})
    manifest=tree_manifest(ws/'.codex')
    write_json(run/'shirokov-package-manifest.json',manifest)
    skills=sorted(p.parent.name for p in (ws/'.codex/skills').glob('*/SKILL.md'))
    return {'name':'shirokov-skills','registration':'author Codex Python port; exact project skills; native plugin hooks disabled',
            'mcp_servers':[],'additional_skills':skills,'source_commit':json.loads((source/'provenance.json').read_text(encoding='utf-8'))['commit'],
            'worker_env':{'PATH':str(binary)+':/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin',
                          'PYTHONPATH':str(runtime/'python-site-packages'), 'PYTHONDONTWRITEBYTECODE':'1',
                          'PLAYWRIGHT_BROWSERS_PATH':str(ws/'.local/playwright')}},''


def tool_usage(events):
    calls=[];seen=set()
    for e in events:
        native=e['native'];item=native.get('item',{})
        if native.get('type')!='item.completed' or item.get('type')!='mcp_tool_call':continue
        key=(item.get('id'),item.get('server'),item.get('tool'))
        if key[0] is not None and key in seen:continue
        seen.add(key)
        calls.append({'server':item.get('server'),'tool':item.get('tool'),'status':item.get('status'),'error':item.get('error')})
    return {'mcp_calls':len(calls),'unica_calls':sum(c['server']=='unica' for c in calls),'failed_calls':sum(c['status']=='failed' or c['error'] is not None for c in calls),'calls':calls}


def stop_owned_runtimes(workspace,grace=3):
    prefix=str(Path(workspace).resolve())+'/client-home/unica/'
    def rows():
        output=subprocess.run(['ps','-axo','pid=,pgid=,args='],capture_output=True,text=True,check=True).stdout
        found=[]
        for line in output.splitlines():
            p=line.strip().split(None,2)
            if len(p)==3 and p[2].startswith(prefix):found.append((int(p[0]),int(p[1]),p[2]))
        return found
    initial=rows();actions=[]
    for pid,pgid,command in initial:
        if pid==pgid:
            try:os.killpg(pgid,signal.SIGTERM)
            except ProcessLookupError:continue
            actions.append({'pid':pid,'pgid':pgid,'signal':'SIGTERM','scope':'owned worker runtime group'})
    end=time.monotonic()+grace
    while rows() and time.monotonic()<end:time.sleep(.05)
    # A surviving runtime is stopped only while its executable/argv identity
    # still matches the initial owned snapshot; unrelated PIDs are untouched.
    for row in rows():
        if row in initial:
            try:os.kill(row[0],signal.SIGKILL)
            except ProcessLookupError:continue
            actions.append({'pid':row[0],'signal':'SIGKILL','scope':'owned worker runtime'})
    end=time.monotonic()+1
    while rows() and time.monotonic()<end:time.sleep(.05)
    remaining=rows()
    return {'owned_runtimes_found':len(initial),'actions':actions,'owned_processes_remaining':len(remaining),'stop_confirmed':not remaining}
