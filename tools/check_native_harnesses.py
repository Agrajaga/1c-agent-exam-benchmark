"""Verify installed packages and exercise native tools on the issued starter, without an LLM."""
import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from exam_bench.common import digest, tree_manifest, utc, write_json
from exam_bench import portable_harnesses as native
from tools.probe_native_mcp import Client


@contextlib.contextmanager
def probe_workspace():
    temporary = tempfile.TemporaryDirectory(prefix='hp-')
    path = Path(temporary.name).resolve()
    if path.parent != Path(tempfile.gettempdir()).resolve() or not path.name.startswith('hp-'):
        raise ValueError('Unexpected probe workspace')
    try:
        yield str(path)
    finally:
        for attempt in range(20):
            try:
                temporary.cleanup()
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(.2)


def payload(response):
    if response.get('isError'):
        raise ValueError('Tool returned isError: ' + json.dumps(response)[:1000])
    if response.get('structuredContent') is not None:
        value = response['structuredContent']
    else:
        texts = [x['text'] for x in response.get('content', []) if x.get('type') == 'text']
        try:
            value = json.loads(texts[0]) if texts else response
        except ValueError:
            value = texts[0]
    if isinstance(value, dict) and value.get('ok') is False:
        raise ValueError('Tool returned ok=false: ' + json.dumps(value)[:1000])
    if isinstance(value, dict) and isinstance(value.get('result'), str):
        try:
            value = json.loads(value['result'])
        except ValueError:
            pass
    return value


def seal(name, target='windows-x64'):
    root = ROOT / '.local/harnesses' / name
    write_json(root / 'package-manifest.json', tree_manifest(root / 'package'))
    legacy=ROOT/'profiles'/(name+'-macos.json')
    provenance={}
    if legacy.is_file():
        original=json.loads(legacy.read_text(encoding='utf-8'))
        provenance={key:original[key] for key in ('source_commit','source_repository','source_branch','release') if key in original}
    if name.startswith('unica-'):
        manifest=json.loads((root/'package/plugin/runtime-manifest.json').read_text(encoding='utf-8'))
        provenance.update(source_commit=manifest['source']['commit'],source_repository=manifest['source']['repository'],release=manifest['release']['tag'])
    skills_root=root/'package'/native.entry(name).get('skills','skills')
    provenance['skills']=sorted(p.parent.name for p in skills_root.glob('*/SKILL.md'))
    if name=='mcp-toolkit-1.9.0':
        from exam_bench.mcp_toolkit import EPF
        provenance['release_asset_sha256']=digest(root/'package'/EPF)
    write_json(native.profile(name), {**provenance,'schema_version': 1, 'id': name + '-' + target.split('-')[0] + '-native-v1', 'additional_harness': name,
        'target': target, 'memory': False, 'extensions': False, 'delegation': 'disabled',
        'package_manifest_sha256': digest(root / 'package-manifest.json'), 'configuration': native.entry(name)})


def probe_kind(name):
    """The descriptor names a built-in probe or describes a generic MCP call."""
    path = ROOT / 'harnesses' / (name + '.json')
    return json.loads(path.read_text(encoding='utf-8')).get('probe') if path.is_file() else None


def check(name):
    probe = probe_kind(name)
    cfg = json.loads((ROOT / '.local/demo/config.json').read_text(encoding='utf-8'))
    os.environ['EXAM_BENCH_CONFIG'] = str(ROOT / cfg['machine_config'])
    root = ROOT / '.local/harnesses' / name
    native.verify(name, require_probe=False)
    transcript = []
    try:
        with probe_workspace() as temporary:
            ws = Path(temporary)
            (ws / 'tmp').mkdir(); (ws / 'out').mkdir(); (ws / 'client-home/skills').mkdir(parents=True)
            run = ws / 'evidence'; run.mkdir()
            shutil.copytree(ROOT / cfg['starter_source'], ws / 'out/src')
            harness, _ = native.configure(name, ws, ws / 'client-home', run, require_probe=False)
            package = Path(harness['package_path'])
            if probe == 'skill-script':
                script = ws / '.codex/skills/meta-info/scripts/meta-info.py'
                xml = next((ws / 'out/src/Catalogs').glob('*.xml'))
                env = {**os.environ, **harness['worker_env']}
                result = subprocess.run([sys.executable, str(script), '-ObjectPath', str(xml), '-Mode', 'overview'],
                    cwd=ws, env=env, capture_output=True, text=True, encoding='utf-8', timeout=45)
                (root / 'probe-skill.stdout.txt').write_text(result.stdout, encoding='utf-8')
                (root / 'probe-skill.stderr.txt').write_text(result.stderr, encoding='utf-8')
                if result.returncode or xml.stem not in result.stdout:
                    raise ValueError('Author metadata parser did not read the starter object')
                transcript.append({'skill': 'meta-info', 'object': xml.stem, 'exit_code': result.returncode})
            elif not native.entry(name).get('server'):
                # Skills only: the agent must find at least one SKILL.md where the harness declares them.
                skills = sorted(p.parent.name for p in (package / native.entry(name).get('skills', 'skills')).glob('*/SKILL.md'))
                if not skills:
                    raise ValueError('No SKILL.md found in the declared skills folder')
                transcript.append({'skills': skills})
            else:
                command, args, extra = native.spec(name, ws, ws / 'client-home', package)
                env = {**os.environ, **extra}
                (ws / 'v8project.yaml').write_text('workPath: .local/probe\nformat: DESIGNER\nsource-set:\n  - name: main\n    type: CONFIGURATION\n    path: out/src\n', encoding='utf-8')
                try:
                    native.launch(ws, env, run)
                    with Client(command, args, ws, env, root / 'probe-mcp.stderr.log') as client:
                        info = client.initialize(); tools = client.request('tools/list')['tools']
                        write_json(root / 'tool-surface.json', tools)
                        transcript.append({'initialize': info, 'tools': [x['name'] for x in tools]})
                        def call(tool, arguments):
                            response = client.request('tools/call', {'name': tool, 'arguments': arguments}, timeout=120)
                            value = payload(response); transcript.append({'tool': tool, 'arguments': arguments, 'response': value})
                            return value
                        if probe == 'unica':
                            value = call('unica.view', {})
                            if not value.get('data', {}).get('sourceSets'):
                                raise ValueError('Unica did not discover starter source set')
                            call('unica.view', {'at': 'main:Configuration'})
                        elif probe == 'rlm':
                            value = call('rlm_start', {'query': 'Inspect the issued starter configuration', 'path': str(ws / 'out/src'), 'domains': []})
                            session = value.get('session_id')
                            if not session:
                                raise ValueError('RLM did not create an analysis session')
                            value = call('rlm_execute', {'session_id': session, 'code': "print(len(glob_files('**/*.xml')))"})
                            if value.get('error'):
                                raise ValueError('RLM execution failed')
                            if int(value.get('stdout', '0').strip()) <= 0:
                                raise ValueError('RLM did not read any starter XML files')
                            call('rlm_end', {'session_id': session})
                        elif probe == 'bsl-analyzer':
                            xml = next((ws / 'out/src/Catalogs').glob('*.xml'))
                            for attempt in range(20):
                                value = call('metadata', {'action': 'object', 'object_type': 'Справочник', 'object_name': xml.stem})
                                if xml.stem in json.dumps(value, ensure_ascii=False):
                                    break
                                time.sleep(.5)
                            else:
                                raise ValueError('Analyzer did not return the requested starter object')
                        elif probe == 'bsl-ls':
                            module = next((ws / 'out/src').rglob('*.bsl'), None)
                            if module is None:
                                module = ws / 'out/src/BenchmarkProbe.bsl'
                                module.write_text('Процедура Проверка()\nКонецПроцедуры\n', encoding='utf-8')
                            call('register_workspace_folder', {'path': str(ws / 'out/src')})
                            schema = next(x['inputSchema'] for x in tools if x['name'] == 'analyze_file')
                            key = next(k for k in schema['properties'] if k.lower() in ('path', 'file', 'filepath', 'file_path'))
                            call('analyze_file', {key: str(module)})
                        elif probe == 'code-index':
                            schema = next(x['inputSchema'] for x in tools if x['name'] == 'get_object_structure')
                            key = next(k for k in schema['properties'] if k in ('full_name', 'object_name', 'name', 'objectName'))
                            xml = next((ws / 'out/src/Catalogs').glob('*.xml'))
                            call('get_object_structure', {key: 'Catalog.' + xml.stem})
                        elif isinstance(probe, dict):
                            arguments = json.loads(json.dumps(probe.get('arguments', {})).replace('{src}', json.dumps(str(ws / 'out/src'))[1:-1]))
                            value = call(probe['tool'], arguments)
                            if probe.get('expect') and probe['expect'] not in json.dumps(value, ensure_ascii=False):
                                raise ValueError('Probe answer lacks the expected text: ' + probe['expect'])
                        elif not tools:
                            raise ValueError('MCP server exposes no tools')
                finally:
                    cleanup = native.stop(ws)
                    for log in run.glob('*.log'):
                        shutil.copyfile(log, root / log.name)
                    if not cleanup['stop_confirmed']:
                        raise ValueError('Native helper did not stop')
            if not native.integrity(ws, run):
                raise ValueError('Probe changed the supplied harness files')
        write_json(root / 'probe-evidence.json', transcript)
        receipt = {'accepted': True, 'created_at': utc(), 'profile_sha256': digest(native.profile(name)),
                   'evidence_sha256': digest(root / 'probe-evidence.json'), 'model_requests': 0,
                   'scope': 'Проверены нативный запуск и чтение каркаса; экзаменационный прогон ещё не выполнялся.'}
    except Exception as error:
        write_json(root / 'probe-evidence.json', transcript)
        receipt = {'accepted': False, 'created_at': utc(), 'profile_sha256': digest(native.profile(name)),
                   'reason': str(error)[:500], 'cause': str(error.__context__)[:500] if error.__context__ else None, 'model_requests': 0}
    write_json(root / 'capability.json', receipt)
    print(name, json.dumps(receipt, ensure_ascii=False), flush=True)
    return receipt['accepted']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('harness', choices=list(native.registry()))
    args = parser.parse_args()
    raise SystemExit(0 if check(args.harness) else 1)
