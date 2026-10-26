#!/usr/bin/env python3
"""Serve only the public dist directory; rebuild when completed evidence changes."""
import argparse
import functools
import hashlib
import http.server
import json
import secrets
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_result_site import build


def watch_signature(root, catalogue_only=False):
    from tools.build_result_site import SITE_FILES, RULEBOOK_INPUTS
    refs = ['site/catalogue.json', '.local/demo/config.json'] + ['site/' + name for name in SITE_FILES]
    refs = [r for r in refs if (root / r).is_file()]
    refs += [str(p.relative_to(root)) for p in (root / 'community/results').rglob('*') if p.is_file()]
    refs += [str(p.relative_to(root)) for p in (root / 'docs').glob('*RUN.md')]
    if (root / 'docs/COMMUNITY.md').is_file(): refs.append('docs/COMMUNITY.md')
    refs += [str(p.relative_to(root)) for p in sorted((root / 'rules').glob('*/rules.json'))]
    refs += [str(p.relative_to(root)) for name in RULEBOOK_INPUTS.values() for p in sorted((root / 'rules').glob('*/' + name))]
    # Penalty changes affect stale-result notices even though immutable evaluations stay unchanged.
    if (root / 'exam_bench/common.py').is_file():
        from exam_bench.common import grading_inputs
        refs += [str(p.relative_to(root)) for p in grading_inputs(root).values() if p.is_file()]
    refs += [str(p.relative_to(root)) for p in sorted((root / 'starters').glob('*/starter.json'))]
    refs += [str(p.relative_to(root)) for p in sorted((root / 'tasks').glob('*/checks.json'))]
    refs += [str(p.relative_to(root)) for p in sorted(root.glob('*/*/ledger.json'))]
    refs += [str(p.relative_to(root)) for p in sorted((root / 'rules').glob('*/decisions.json'))]
    config = json.loads((root / 'site/catalogue.json').read_text(encoding='utf-8'))
    if catalogue_only:
        config = {**config, 'assessments': [], 'exclusions': [], 'campaign_state_ref': None}
    refs += config['assessments'] + config['exclusions']
    if config.get('campaign_state_ref'):
        refs.append(config['campaign_state_ref'])
    for item in config['tasks']:
        refs += [item['directory'] + '/' + name for name in
                 ('manifest.json', 'private/rules.json', 'private/official-assessment-mapping.json', 'private/owner-scoring-policy.json')
                 if (root / item['directory'] / name).is_file()]
    for result in (root / '.local/runs').glob('*/result.json'):
        run = result.parent
        for name in ('result.json', 'plan.json', 'artifact-manifest.json', 'artifacts/interpretations.json',
                     'compatible-binding-v1/result.json', 'native-load-unchanged/load-gate.json'):
            if (run / name).is_file():
                refs.append(str((run / name).relative_to(root)))
    refs += [str(e.relative_to(root)) for e in (root / '.local/assessments').glob('*/*/evaluation.json')]
    refs += [str(e.relative_to(root)) for e in (root / '.local/demo/jobs').glob('*/evaluation.json')]
    refs += [str(e.relative_to(root)) for e in (root / '.local/harnesses').glob('*/capability.json')]
    refs += [str(e.relative_to(root)) for e in (root / 'profiles').glob('*-portable.json')]
    refs += [str(e.relative_to(root)) for e in (root / '.local/harnesses').glob('*/profile.json')]
    if (root / '.local/harnesses/portable.json').is_file():
        refs.append('.local/harnesses/portable.json')
    if (root / '.local/demo/config.json').is_file():
        demo_config = json.loads((root / '.local/demo/config.json').read_text(encoding='utf-8'))
        # A participant's stand has no owner baseline; the configured path may not exist.
        if (root / demo_config['baseline_evaluation']).is_file():
            refs.append(demo_config['baseline_evaluation'])
    hasher = hashlib.sha256()
    for ref in sorted(refs):
        path = root / ref
        hasher.update(ref.encode())
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    controller = None
    community_token = secrets.token_urlsafe(32)

    def json_response(self, status, data):
        payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def ensure_controller(self):
        # Calibration creates the demo configuration while the server is running.
        if not self.controller and (ROOT / '.local/demo/config.json').is_file():
            from tools.demo_runner import Controller
            controller = Controller(ROOT)
            controller.token = self.community_token
            type(self).controller = controller
        return self.controller

    def csrf(self):
        return self.controller.token if self.controller else self.community_token

    def local_request(self):
        host = self.headers.get('Host', '')
        return host in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

    def do_GET(self):
        if self.path.split('?')[0] == '/api/results/log':
            if not self.local_request():
                return self.json_response(403, {'error': 'Local host required'})
            from urllib.parse import parse_qs, urlsplit
            from tools.demo_runner import agent_log
            try:
                return self.json_response(200, agent_log(ROOT, parse_qs(urlsplit(self.path).query)['id'][0]))
            except (ValueError, KeyError, OSError) as error:
                return self.json_response(404, {'error': str(error) if isinstance(error, ValueError) else 'Лог не найден'})
        if self.path.split('?')[0] in ('/api/readiness', '/api/results'):
            if not self.local_request():
                return self.json_response(403, {'error': 'Local host required'})
            self.ensure_controller()
            if self.path.split('?')[0] == '/api/results':
                from tools.demo_runner import history
                return self.json_response(200, {'results': history(ROOT), 'csrf': self.csrf()})
            from tools.readiness import snapshot
            try:
                result = snapshot(ROOT)
            except Exception:
                return self.json_response(503, {'error': 'Не удалось проверить готовность стенда.'})
            result['csrf'] = self.csrf()
            return self.json_response(200, result)
        if self.path.split('?')[0] == '/api/community':
            if not self.local_request():
                return self.json_response(403, {'error': 'Local host required'})
            from tools.community_service import snapshot
            result = snapshot(ROOT)
            result['csrf'] = self.csrf()
            return self.json_response(200, result)
        if self.path.split('?')[0] == '/api/community/download':
            if not self.local_request():
                return self.json_response(403, {'error': 'Local host required'})
            from urllib.parse import parse_qs, urlsplit
            from tools.community_results import check_id
            try:
                result_id = check_id(parse_qs(urlsplit(self.path).query)['id'][0])
                archive = ROOT / '.local/community/prepared' / (result_id + '.zip')
                if not archive.is_file():
                    raise ValueError('Package not ready')
                self.send_response(200)
                self.send_header('Content-Type', 'application/zip')
                self.send_header('Content-Disposition', f'attachment; filename="{result_id}.zip"')
                self.send_header('Content-Length', str(archive.stat().st_size))
                self.end_headers()
                with archive.open('rb') as stream:
                    import shutil
                    shutil.copyfileobj(stream, self.wfile)
                return
            except (ValueError, KeyError):
                return self.json_response(404, {'error': 'Package not found'})
        if self.path.split('?')[0] == '/api/demo':
            if not self.local_request():
                return self.json_response(403, {'error': 'Local host required'})
            if not self.ensure_controller():
                return self.json_response(200, {'enabled': False})
            try:
                return self.json_response(200, self.controller.snapshot())
            except Exception:
                return self.json_response(503, {'error': 'Не удалось прочитать состояние демонстрационного стенда.'})
        return super().do_GET()

    def do_POST(self):
        community = self.path.startswith(('/api/community/', '/api/readiness/'))
        if not community and (self.path != '/api/demo/start' or not self.ensure_controller()):
            return self.json_response(404, {'error': 'Not found'})
        origin = self.headers.get('Origin')
        if (not self.local_request() or origin not in (None, 'http://' + self.headers.get('Host', ''))
                or self.headers.get('Content-Type') != 'application/json'
                or not secrets.compare_digest(self.headers.get('X-Demo-Token', ''), self.csrf())):
            return self.json_response(403, {'error': 'Запуск разрешён только со страницы локального стенда.'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= (4096 if community else 1024):
                raise ValueError('Invalid request size')
            data = json.loads(self.rfile.read(size))
            if self.path.startswith('/api/readiness/'):
                from tools.readiness import act
                return self.json_response(202, act(self.path.removeprefix('/api/readiness/'), data, ROOT))
            if community:
                from tools.community_service import start
                return self.json_response(202, start(self.path.removeprefix('/api/community/'), data, ROOT))
            if not {'mode'} <= set(data) <= {'mode', 'harness', 'hours', 'model'}:
                raise ValueError('Invalid request fields')
            result=self.controller.start(data['mode'],**{k: data[k] for k in ('harness','hours','model') if k in data})
            return self.json_response(202, result)
        except RuntimeError as error:
            return self.json_response(409, {'error': str(error)})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.json_response(400, {'error': str(error) if community and isinstance(error, ValueError) else
                                           'Некорректное действие или стенд не готов к запуску.'})
        except Exception:
            return self.json_response(503, {'error': 'Не удалось запустить задание. Проверьте настройки стенда.'})

    # Text assets are UTF-8; without an explicit charset browsers may decode CSS and plain text as Latin-1.
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      **{ext: kind + '; charset=utf-8' for ext, kind in {'.css': 'text/css', '.js': 'text/javascript', '.html': 'text/html',
                                                                          '.json': 'application/json', '.txt': 'text/plain', '.md': 'text/markdown',
                                                                          '.csv': 'text/csv'}.items()}}

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Content-Type-Options', 'nosniff')
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404, 'Directory listings disabled')
        return None


def serve(port=8879, watch=True, catalogue_only=False):
    if (ROOT / '.local/demo/config.json').is_file():
        from tools.demo_runner import Controller
        StaticHandler.controller = Controller(ROOT)
    build(catalogue_only=catalogue_only)
    signature = watch_signature(ROOT, catalogue_only)
    stopped = threading.Event()
    def update():
        nonlocal signature
        last_failed = None
        while not stopped.wait(3):
            try:
                current = watch_signature(ROOT, catalogue_only)
                if current != signature:
                    build(catalogue_only=catalogue_only)
                    signature = current
                    last_failed = None
                    print('Site updated from completed run evidence.', flush=True)
            except Exception as error:
                # In-flight or invalid evidence must not replace the last good publication.
                if str(error) != last_failed:
                    print('Keeping previous export; update failed: ' + str(error), file=sys.stderr, flush=True)
                    last_failed = str(error)
    handler = functools.partial(StaticHandler, directory=str(ROOT / 'site/dist'))
    with http.server.ThreadingHTTPServer(('127.0.0.1', port), handler) as server:
        if watch:
            threading.Thread(target=update, daemon=True).start()
        print(f'Local: http://127.0.0.1:{port}/', flush=True)
        print('Only site/dist is served. Ctrl+C stops the local server.', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            stopped.set()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8879)
    parser.add_argument('--no-watch', action='store_true')
    parser.add_argument('--catalogue-only', action='store_true', help='Export tasks without historical .local evidence')
    args = parser.parse_args()
    serve(args.port, not args.no_watch, args.catalogue_only)


if __name__ == '__main__':
    main()
