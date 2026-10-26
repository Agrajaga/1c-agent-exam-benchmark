#!/usr/bin/env python3
"""Export explicitly public benchmark data and immutable solutions for a static site.

Never publishes raw logs, account usage, private fixtures or candidate-authored claims.
Existing judgments are read, not recalculated. New result.json files accumulate on build.
"""
import re
import argparse
import csv
import hashlib
import json
import shutil
import sys
import zipfile
from collections import Counter
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from exam_bench.common import digest, tree_manifest, utc, write_json
from exam_bench.telemetry import token_breakdown
from tools.compare_harness_runs import VARIANT_FIELDS


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def inside(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Path escapes root')
    return path


def public_error(error):
    if error is None:
        return None
    # Only adapter messages with metadata identifiers are safe to export verbatim.
    if error.startswith(('Adapter does not yet interpret analog representation:', 'Ledger field absent or unsupported:')) and '/' not in error:
        return error
    return 'Сдача не прошла первичную проверку; подробности сохранены в локальном журнале стенда.'


def cohort_key(plan, environment_hash):
    # Model and harness are compared within this cohort; other conditions must match.
    conditions = {k: v for k, v in plan.items() if k not in VARIANT_FIELDS | {'model'}}
    conditions['environment_sha256'] = environment_hash
    return hashlib.sha256(json.dumps(conditions, sort_keys=True).encode()).hexdigest()[:12]


def normalize_charges(assessment, catalogue):
    if assessment is None:
        return None
    seen, charges = set(), []
    for charge in assessment['charges']:
        key = (charge['defect_id'], charge['penalty_id'])
        if key in seen:
            continue
        seen.add(key)
        entry = catalogue[charge['penalty_id']]
        # Generic penalties are assigned by the proved defect, not by their catalogue category.
        section = charge.get('section') or ('PR' if charge['defect_id'].startswith('payroll.') else entry['category'])
        charges.append({k: charge.get(k) for k in ('penalty_id', 'defect_id', 'points_min', 'points_max', 'proof_kind', 'evidence')} | {
            'section': section, 'title': entry['label']})
    totals = assessment['confirmed_deductions']
    if (sum((Decimal(c['points_min']) for c in charges), Decimal(0)) != Decimal(totals['min'])
            or sum((Decimal(c['points_max']) for c in charges), Decimal(0)) != Decimal(totals['max'])):
        raise ValueError('Inconsistent deduction total')
    return charges


def package_solution(run, dist):
    artifacts = run / 'artifacts'
    manifest = read(run / 'artifact-manifest.json')
    if tree_manifest(artifacts) != manifest:
        raise ValueError('Frozen artifacts changed: ' + run.name)
    selected = [p for p in manifest if p.startswith('src/') or p in ('binding.json', 'solution.cf')]
    if not any(p.startswith('src/') for p in selected):
        return []
    target = dist / 'downloads' / run.name
    target.mkdir(parents=True, exist_ok=True)
    public_manifest = {p: manifest[p] for p in sorted(selected)}
    archive = target / 'solution.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in sorted(selected):
            path = inside(artifacts, name)
            if path.is_symlink():
                raise ValueError('Symlink refused')
            # Fixed timestamps make unchanged solutions byte-identical across exports.
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, path.read_bytes())
        z.writestr(zipfile.ZipInfo('SHA256.json', date_time=(2026, 1, 1, 0, 0, 0)), json.dumps(public_manifest, ensure_ascii=False, indent=2))
        z.writestr(zipfile.ZipInfo('README.txt', date_time=(2026, 1, 1, 0, 0, 0)), 'Замороженная сдача: ' + run.name + '\nИсходники src/ в формате выгрузки 1С.\n'
                   'Архив не исправляет ошибки решения и не подтверждает сдачу экзамена.\n'
                   'Если есть solution.cf, это артефакт агента; приёмка проверяла src/, а не этот CF.\n')
    def link(p, label):
        return {'label': label, 'url': p.relative_to(dist).as_posix(), 'sha256': digest(p), 'bytes': p.stat().st_size}
    links = [link(archive, 'Решение · ZIP')]
    if 'solution.cf' in manifest:
        cf = target / 'solution.cf'
        shutil.copyfile(artifacts / 'solution.cf', cf)
        links.append(link(cf, 'CF агента · отдельно не проверен'))
    write_json(target / 'manifest.json', {'run_id': run.name, 'files': public_manifest,
                'frozen_artifact_manifest_sha256': digest(run / 'artifact-manifest.json')})
    links.append(link(target / 'manifest.json', 'Контрольные суммы · JSON'))
    return links


def interpretations_view(run, plan, ticket):
    """The agent's own reading of ambiguous places next to the stand's answers; required since open-methodics-v2."""
    from exam_bench.interpretations import read as read_interpretations, compare
    required = plan.get('input_revision') not in (None, 'open-methodics-v1')
    found = read_interpretations(run / 'artifacts') if (run / 'artifacts').is_dir() else {'status': 'missing', 'items': []}
    view = {'required': required, 'status': found['status'], 'reason': found.get('reason'), 'items': []}
    if found['items'] and ticket:
        checks, ledger = ticket
        view['items'] = compare(found['items'], ledger, checks['requirements'], checks.get('questions', []))
        numbers = {r['id']: r['number'] for r in checks['requirements']}
        for item in view['items']:
            item['requirements'] = [numbers.get(r, r) for r in item['requirements']]
    return view


def official_view(assessment, root):
    """Penalties of the official list proved for a run and the score bound they imply (exam_bench.penalties)."""
    if not assessment:
        return None
    book = {r['id']: r for r in read(root / 'rules/1c-specialist-platform/rules.json')['rules']}
    charges = {c['defect_id']: c for c in assessment['score']['charges']}
    findings = []
    for f in assessment['findings']:
        charge = charges.get(f['defect_id'])
        if not charge or charge['penalty_id'] != f['penalty_id']:
            continue
        rule = book.get(f['penalty_id'].replace('F1C-', ''), {})
        findings.append({'number': rule.get('number'), 'title': rule.get('title'), 'points': charge['points'], 'reason': f['reason']})
    statuses = assessment['statuses']
    return {'score_upper_bound': assessment['score']['score_upper_bound'], 'deductions': assessment['score']['deductions'],
            'attestation': assessment['score']['attestation'], 'grade': assessment['score']['grade'], 'findings': findings,
            'assessed': len(assessment['assessed']), 'applicable': len(statuses), 'policy': assessment['policy']}


def posting_failure(evaluation):
    """One short line on why fixture documents did not post, when the cause is a code error rather than a refusal."""
    grade = evaluation / 'grade/grade.json'
    if not grade.is_file():
        return None
    for observation in read(grade).get('observations', {}).values():
        error = observation.get('posting_error') or ''
        if observation.get('posted') or not error or 'Failed to post' in error or 'Не удалось провести' in error:
            continue
        # Drop platform stack prefixes "{Module(line)}: ..." and keep the innermost message.
        message = re.split(r'\}:\s*', error)[-1].split('\n')[0].strip()
        # Platform text quotes the solver's query; filesystem paths are never exported.
        return 'Проведение документа падает с ошибкой платформы' + ('' if '/' in message else ': ' + message[:220])
    return None


PAGES = ('index.html', 'results.html', 'leaderboard.html', 'checks.html', 'inputs.html')
SCRIPTS = ('style.css', 'nav.js', 'local.js', 'submit.js', 'harness-prompt.js', 'harness-versions.js', 'measure.js', 'results.js', 'leaderboard.js', 'checks.js', 'inputs.js', 'penalty-cards.js')
SITE_FILES = PAGES + SCRIPTS

# What each delivered file is for; shown on the «Что получает агент» page.
PUBLIC_PURPOSE = {
    'statement.docx': 'Условие билета — официальный документ, как его видит человек на экзамене',
    'statement.txt': 'Текстовая копия условия',
    'methodical-requirements.txt': 'Методика 1С: форма экзамена и полный перечень ошибок со штрафами',
    'assessment-policy.md': 'Правила стенда: чем оценка отличается от официальной',
    'protocol.md': 'Протокол сдачи: что и куда положить, как объявить привязки',
    'binding-contract.json': 'Схема out/binding.json: какие объекты и поля назвать стенду',
}
WORKSPACE = [
    ('starter.dt', 'Каркас в том виде, в каком его выдают на экзамене: выгрузка информационной базы с данными'),
    ('starter/', 'Конфигурация каркаса в выгрузке Конфигуратора — только для чтения'),
    ('out/src/', 'Копия конфигурации каркаса, которую агент дорабатывает; это и есть сдача'),
    ('ib/', 'Информационная база, развёрнутая из starter.dt, с данными каркаса: номенклатура, контрагенты, физлица, подразделения, план счетов, валюты'),
    ('worker.json', 'Параметры запуска и окружение: модель, лимит, харнес, пути и версия платформы, база, исходники — всё, чтобы агент сам настроил свои инструменты'),
]
WITHHELD = [
    'Тестовые данные и ожидаемые результаты стенда (сценарии, суммы, остатки)',
    'Код проверяющего и калибровочные решения',
    'Ответы на вопросы по билету (Q01–Q09) и разметка требований — это трактовка проверяющего',
    'Решения и результаты других прогонов',
    'Веб-поиск и встроенные интеграции клиента (сеть из shell открыта)',
    'Память агента и личные настройки: память Codex отключена, домашний каталог клиента на каждую попытку пустой, пользовательский конфиг игнорируется',
]


def inputs_export(root, config, stage, catalogue_only=False):
    """Everything the solver gets: prompt, workspace layout, public task files (copied for viewing), worker.json values."""
    import sys
    sys.path.insert(0, str(root))
    from exam_bench.materials import DEFAULT_PROMPT, INPUT_REVISION
    from exam_bench.codex import public_plan_values, worker_document
    placeholder = Path('<workspace>')  # the real workspace is a temporary path, shown as a placeholder
    tickets = []
    for spec in config['tasks']:
        task_root = inside(root, spec['directory'])
        manifest = read(task_root / 'manifest.json')
        public = task_root / 'public'
        files = []
        for path in sorted(p for p in public.rglob('*') if p.is_file()):
            rel = path.relative_to(public).as_posix()
            target = stage / 'inputs' / manifest['task_id'] / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            item = {'path': 'task/' + rel, 'href': f"inputs/{manifest['task_id']}/{rel}", 'bytes': path.stat().st_size,
                    'purpose': PUBLIC_PURPOSE.get(rel) or ('Рисунок из условия' if rel.startswith('assets/') else ''),
                    'kind': 'image' if path.suffix == '.png' else 'text' if path.suffix in ('.txt', '.md', '.json') else 'binary'}
            if item['kind'] == 'text':
                item['lines'] = len(path.read_text(encoding='utf-8-sig').splitlines())
            files.append(item)
        tickets.append({'id': manifest['task_id'], 'title': manifest['title'], 'files': files})
    runs = []
    for run in ([] if catalogue_only else sorted((root / '.local/runs').glob('*'))):
        if (run / 'plan.json').is_file() and (run / 'result.json').is_file():
            plan = read(run / 'plan.json')
            if plan.get('purpose') == config['purpose']:
                harness = read(run / 'harness.json') if (run / 'harness.json').is_file() else {}
                files = {'worker.json': json.dumps(worker_document(plan, placeholder, harness, ['<platform-cache>'], True,
                                                                    plan.get('input_revision') not in (None, 'open-methodics-v1', 'open-methodics-v2', 'open-methodics-v3', 'open-methodics-v4')), ensure_ascii=False, indent=2)}
                runs.append({'run_id': run.name, 'worker': public_plan_values(plan), 'network_profile': plan.get('network_profile'), 'files': files,
                             'harness': {'name': harness.get('name'), 'skills': len(harness.get('additional_skills') or []),
                                         'mcp': harness.get('mcp_servers') or []}})
    if runs:
        # What the next campaign gets: the latest plan with the current materials revision (harness of that run).
        latest = read(root / '.local/runs' / runs[0]['run_id'] / 'plan.json')
        upcoming = dict(latest, input_revision=INPUT_REVISION, run_id='<run-id>')
        harness_file = root / '.local/runs' / runs[0]['run_id'] / 'harness.json'
        harness = read(harness_file) if harness_file.is_file() else {}
        runs.insert(0, {'run_id': 'upcoming', 'upcoming': True, 'worker': public_plan_values(upcoming), 'harness': {'name': harness.get('name'), 'skills': 0, 'mcp': []},
                        'files': {'worker.json': json.dumps(worker_document(upcoming, placeholder, harness, ['<platform-cache>'], True), ensure_ascii=False, indent=2)}})
    return {'schema_version': 1, 'input_revision': INPUT_REVISION, 'prompt': DEFAULT_PROMPT, 'tickets': tickets,
            'workspace': [{'path': p, 'purpose': t} for p, t in WORKSPACE], 'withheld': WITHHELD, 'runs': runs}


def checks_export(root, config):
    """The three agent inputs: shared starters and rulebooks, plus per-ticket checks (no oracle values)."""
    tickets, rulebooks, starters = [], {}, {}
    for spec in config['tasks']:
        path = inside(root, spec['directory']) / 'checks.json'
        if not path.is_file():
            continue
        ticket = read(path)
        if (path.parent / 'ledger.json').is_file():
            ticket['ledger'] = read(path.parent / 'ledger.json')
        tickets.append(ticket)
        if ticket['rulebook'] not in rulebooks:
            book = read(inside(root, f"rules/{ticket['rulebook']}/rules.json"))
            ledger = inside(root, f"rules/{ticket['rulebook']}/ledger.json")
            if ledger.is_file():
                book['ledger'] = read(ledger)
            decisions = inside(root, f"rules/{ticket['rulebook']}/decisions.json")
            if decisions.is_file():
                book['decisions'] = read(decisions)
            examiner = inside(root, f"rules/{ticket['rulebook']}/examiner.json")
            if examiner.is_file():
                book['examiner'] = read(examiner)
            course = inside(root, f"rules/{ticket['rulebook']}/chistov.json")
            if course.is_file():
                book['course'] = read(course)
            std = inside(root, f"rules/{ticket['rulebook']}/standards.json")
            if std.is_file():
                book['standards'] = read(std)
            rulebooks[ticket['rulebook']] = book
        starters.setdefault(ticket['starter'], read(inside(root, f"starters/{ticket['starter']}/starter.json")))
    for ticket in tickets:
        known = {r['id'] for r in rulebooks[ticket['rulebook']]['rules']}
        unknown = {r['rule_id'] for r in ticket['official_rules']} - known
        if unknown:
            raise ValueError('Ticket references rules absent from its rulebook: ' + ', '.join(sorted(unknown)))
    return {'schema_version': 1, 'starters': starters, 'rulebooks': rulebooks, 'tickets': tickets}


def penalty_metadata(checks):
    """Public presentation labels only; never modify evaluations or export grader oracles."""
    def labels(groups, key):
        values, ambiguous = {}, set()
        for group in groups:
            for item in group.get(key, []):
                value = {field: item[field] for field in ('title', 'number')}
                identifier = item['id']
                if identifier in values and values[identifier] != value:
                    ambiguous.add(identifier)
                values[identifier] = value
        return {key: value for key, value in values.items() if key not in ambiguous}
    return {'rules': labels(checks['rulebooks'].values(), 'rules'),
            'requirements': labels(checks['tickets'], 'requirements')}


def build(root=ROOT, output=None, catalogue_only=False):
    root = Path(root).resolve()
    site = root / 'site'
    output = Path(output or site / 'dist').resolve()
    # Only an owned dist tree may be replaced; cannot expose the workspace HTTP root.
    if output != site / 'dist':
        raise ValueError('Output must be site/dist')
    config = read(site / 'catalogue.json')
    if catalogue_only:
        config = {**config, 'assessments': [], 'exclusions': [], 'campaign_state_ref': None}
    assessments = {}
    for ref in config['assessments']:
        item = read(inside(root, ref))
        if item['run_id'] in assessments:
            raise ValueError('Select one assessment revision per run')
        assessments[item['run_id']] = item
    exclusions = {d['run_id']: d for d in (read(inside(root, p)) for p in config['exclusions'])}
    passport = None if catalogue_only else read(root / '.local/environment-verified-v1/passport.json')
    passport_hash = None if catalogue_only else digest(root / '.local/environment-verified-v1/passport.json')
    tasks, specs, ticket_checks = [], [], {}
    for spec in config['tasks']:
        task_root = inside(root, spec['directory'])
        manifest = read(task_root / 'manifest.json')
        rules = read(task_root / 'private/rules.json')['rules']
        penalties = read(task_root / 'private/official-assessment-mapping.json')
        task = {'id': manifest['task_id'], 'title': manifest['title'], 'version': manifest['task_version'],
                'statement_sha256': manifest['public']['statement_sha256'], 'ready': manifest['ready'],
                'sections': spec['sections'], 'rules': [{'id': r['id'], 'title': r['obligation']} for r in rules],
                'penalty_count': len(penalties['items']), 'source_url': manifest['source']['index_url']}
        tasks.append(task)
        specs.append((task, {p['id']: p for p in penalties['items']}))
        if (task_root / 'checks.json').is_file() and (task_root / 'ledger.json').is_file():
            ticket_checks[task['id']] = (read(task_root / 'checks.json'), read(task_root / 'ledger.json'))
    # Stage output then replace only after all integrity checks succeed.
    stage = site / '.dist-staging'
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    for name in SITE_FILES:
        if (site / name).is_file():
            shutil.copyfile(site / name, stage / name)
    # Entry-point versions must also refresh their shared presentation module.
    presenter = stage / 'penalty-cards.js'
    if presenter.is_file():
        for name in ('measure.js', 'leaderboard.js'):
            script = stage / name
            if script.is_file():
                script.write_text(script.read_text(encoding='utf-8').replace(
                    "'./penalty-cards.js'", f"'./penalty-cards.js?v={digest(presenter)[:12]}'"), encoding='utf-8')
    versions = stage / 'harness-versions.js'
    measure = stage / 'measure.js'
    if versions.is_file() and measure.is_file():
        measure.write_text(measure.read_text(encoding='utf-8').replace(
            "'./harness-versions.js'", f"'./harness-versions.js?v={digest(versions)[:12]}'"), encoding='utf-8')
    # Content-hashed asset URLs: browsers never run a stale script or stylesheet after a rebuild.
    for page in PAGES:
        if (stage / page).is_file():
            html = (stage / page).read_text(encoding='utf-8')
            for asset in SCRIPTS:
                if (stage / asset).is_file():
                    html = html.replace(f'"{asset}"', f'"{asset}?v={digest(stage / asset)[:12]}"')
            (stage / page).write_text(html, encoding='utf-8')
    checks = checks_export(root, config)
    write_json(stage / 'checks.json', checks)
    write_json(stage / 'penalty-info.json', penalty_metadata(checks))
    write_json(stage / 'inputs.json', inputs_export(root, config, stage, catalogue_only))
    from tools.demo_runner import export as export_demo
    export_demo(root, stage)
    from tools.community_results import export_public
    export_public(root, stage)
    runs = []
    for run in ([] if catalogue_only else sorted((root / '.local/runs').glob('*'))):
        if not (run / 'result.json').is_file() or not (run / 'plan.json').is_file():
            continue
        plan, result = read(run / 'plan.json'), read(run / 'result.json')
        if plan.get('purpose') != config['purpose']:
            continue
        matches = [(task, items) for task, items in specs if task['statement_sha256'] == plan.get('statement_sha256')]
        if len(matches) != 1:
            raise ValueError('Exam attempt has unknown task: ' + run.name)
        if digest(run / 'plan.json') != read(run / 'plan-integrity.json')['sha256']:
            raise ValueError('Frozen plan changed: ' + run.name)
        task, penalties = matches[0]
        harness = read(run / 'harness.json') if (run / 'harness.json').exists() else {'name': plan['harness']}
        preflight = read(run / 'preflight.json')
        environment_hash = preflight.get('environment_sha256')
        if environment_hash != passport_hash:
            raise ValueError('Unregistered environment passport: ' + run.name)
        assessment = assessments.get(run.name)
        charges = normalize_charges(assessment, penalties)
        supplemental_file = run / 'compatible-binding-v1/result.json'
        supplemental = read(supplemental_file) if supplemental_file.exists() else None
        # A later calibrated re-evaluation of the same frozen artifact (tools/regrade_runs.py) supersedes it.
        evaluations = sorted((read(e) for e in (root / '.local/assessments' / run.name).glob('*/evaluation.json')),
                             key=lambda e: e['created_at'])
        evaluations = [e for e in evaluations if e['artifact_manifest_sha256'] == digest(run / 'artifact-manifest.json')]
        failure_reason = None
        official = official_view(evaluations[-1].get('assessment') if evaluations else None, root)
        if evaluations:
            supplemental = {'status': evaluations[-1]['status'], 'rules': evaluations[-1]['rules'],
                            'evaluation_id': evaluations[-1]['evaluation_id']}
            failure_reason = posting_failure(root / '.local/assessments' / run.name / evaluations[-1]['evaluation_id'])
        rules = {r['id']:r for r in (supplemental or result['grade']).get('rules', [])}
        rules.update({r['id']:r for r in (assessment or {}).get('rule_results', [])})
        rules = list(rules.values())
        load_file = run / 'native-load-unchanged/load-gate.json'
        load_state = read(load_file).get('status') if load_file.exists() else (assessment or {}).get('load_gate', 'not_checked')
        if load_state == 'not_checked' and evaluations and evaluations[-1]['status'] in ('partial_pass', 'partial_fail'):
            load_state = 'loaded'
        excluded = exclusions.get(run.name)
        pilot = bool(result.get('experiment_limits', {}).get('grading_scope_disclosed'))
        record = {'id': run.name, 'task_id': task['id'], 'started_at': result.get('started_at'),
                  'model': result['model']['requested'], 'model_provenance': result['model']['provenance'],
                  'harness': {'id': result['harness'], 'version': harness.get('version'),
                              'skills': len(harness.get('additional_skills', [])),
                              'mcp_servers': harness.get('mcp_servers', []), 'source_commit': harness.get('source_commit'),
                              'runtime_manifest_sha256': harness.get('runtime_manifest_sha256')},
                  'environment': {'os': passport['os'], 'platform': Path(passport['platform_binary']).parent.name,
                                  'sha256': environment_hash, 'client': ('Claude Code ' if plan.get('client') == 'claude' else 'Codex CLI ') + plan['client_version'],
                                  'agent': plan.get('client', 'codex'), 'model': plan.get('model'),
                                  'reasoning': plan['reasoning_effort'], 'network': plan['network_profile'],
                                  'delegation': plan['delegation'], 'profile_sha256': plan['profile_sha256']},
                  'cohort': cohort_key(plan, environment_hash), 'timeout_seconds': plan['solve_timeout_seconds'],
                  'time': result['time'], 'tokens': token_breakdown(result['metrics']['tokens']),
                  'subagents': result['metrics']['agents']['spawned_total'],
                  'mcp_calls': result['metrics'].get('tools', {}).get('mcp_calls'),
                  'billing': {k: result['billing'].get(k) for k in ('channel', 'actual_charge', 'currency',
                              'api_equivalent', 'subscription_allocation', 'api_base_rate_illustration')},
                  'process_status': result['process']['status'], 'load_state': load_state,
                  'primary_status': result['grade']['status'],
                  'primary_error': public_error(result['submission'].get('error')),
                  'supplemental_status': (supplemental or {}).get('status'),
                  'grading_ms': ((supplemental or {}).get('evaluation_ms') or 0) + (assessment or {}).get('native_evaluation_ms',0) if supplemental or assessment else None,
                  'rules': [{'id': r['id'], 'verdict': r['verdict'], 'coverage': r.get('coverage', 'not_run'),
                             'reason': ('Отчёт не объявлен агентом в binding.reports (протокол этого прогона этого не требовал)' if 'Report not declared' in (r.get('reason') or '') else None) if r['verdict'] == 'inconclusive' else None} for r in rules],
                  'penalties': charges, 'assessment': None, 'official': official,
                  'excluded': bool(excluded) or pilot, 'exclusion_reason':
                      ((excluded.get('reason_ru') or excluded.get('reason') or 'Исключено решением куратора; причина в файле исключения.') if excluded else
                       'Пилот с раскрытым профилем частичной приёмки; исключён из экзаменационного рейтинга.' if pilot else None),
                  'exact_score': (assessment or {}).get('exact_score'),
                  'score_upper_bound': (assessment or {}).get('score_upper_bound'),
                  'grade': (assessment or {}).get('grade'),
                  'deductions': (assessment or {}).get('confirmed_deductions'),
                  'whole_ticket_attested': False, 'sections_passed': None, 'failure_reason': failure_reason,
                  'interpretations': interpretations_view(run, plan, ticket_checks.get(task['id'])),
                  'submission_received': (run / 'artifacts/submission.ready.json').exists(),
                  'sections': [], 'downloads': package_solution(run, stage)}
        if assessment:
            record['assessment'] = {k: assessment[k] for k in ('profile_id', 'policy_id', 'whole_catalogue_checked', 'grade_proof')}
            record['assessment']['native_cases'] = [{'id':c['case_id'],'verdict':c['verdict']} for c in assessment.get('case_results',[])]
            record['assessment']['retrospective'] = assessment.get('retrospective',True)
            record['assessment']['inventory'] = dict(Counter(p['status'] for p in assessment['penalty_inventory']))
        for section in task['sections']:
            scope = [r for r in record['rules'] if r['id'].startswith(section['id'])]
            proved = [c for c in charges or [] if c['section'] == section['id']]
            state = 'defects' if proved else 'partial' if any(r['verdict'] == 'pass' for r in scope) else 'not_checked'
            record['sections'].append({'id': section['id'], 'title': section['title'], 'status': state,
                'passed_checks': sum(r['verdict'] == 'pass' for r in scope),
                'rule_count': sum(r['id'].startswith(section['id']) for r in task['rules']),
                'confirmed_deductions': str(sum((Decimal(c['points']) for c in proved), Decimal(0))) if assessment else None,
                'deductions_complete': False, 'submission_status': 'not_independently_checked'})
        # Only proven snippets from published solution sources, never raw platform/auth logs.
        for charge in charges or []:
            for evidence in charge['evidence']:
                source = inside(run / 'artifacts/src', evidence['file'])
                lines = source.read_text(encoding='utf-8-sig').splitlines()
                line = evidence['line']
                evidence['snippet'] = '\n'.join(f'{i + 1}: {lines[i]}' for i in range(max(0, line - 2), min(len(lines), line + 2)))
        runs.append(record)
    campaign = None
    if config.get('campaign_state_ref'):
        current = read(inside(root, config['campaign_state_ref']))
        campaign = {k: current.get(k) for k in ('campaign_id', 'status', 'execution', 'started_at',
                    'finished_at', 'model', 'input_revision', 'timeout_seconds_per_run')}
        campaign['runs'] = [{k: r.get(k) for k in ('run_id', 'harness', 'status', 'started_at',
                            'finished_at', 'process_status', 'solve_ms', 'tokens', 'grade_status')}
                            for r in current['runs']]
    data = {'schema_version': 1, 'generated_at': utc(), 'tasks': tasks, 'runs': runs, 'campaign': campaign,
            'ranking_ready': False, 'policy': {'initial_score': 5, 'deduction_choice': 'interval',
            'one_penalty_per_defect': True, 'clamp_negative': False, 'is_official_1c_attestation': False}}
    write_json(stage / 'data.json', data)
    # Explicit public metrics only; no native transcripts or account counters.
    token_fields = ('total', 'input', 'output', 'cached_input', 'fresh_input', 'reasoning_output', 'coverage')
    with (stage / 'tokens.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=('run_id', 'model', 'harness', *token_fields))
        writer.writeheader()
        for r in runs:
            writer.writerow({'run_id': r['id'], 'model': r['model'], 'harness': r['harness']['id'],
                             **{k: r['tokens'].get(k) for k in token_fields}})
    receipts = {p.relative_to(stage).as_posix(): digest(p) for p in sorted(stage.rglob('*')) if p.is_file()}
    write_json(stage / 'export-manifest.json', {'generated_at': data['generated_at'], 'files': receipts})
    if output.exists():
        shutil.rmtree(output)
    stage.rename(output)
    return data


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    data = build()
    print(json.dumps({'site': str(ROOT / 'site/dist'), 'runs': len(data['runs']),
                      'exam_attempts': sum(not r['excluded'] for r in data['runs']), 'generated_at': data['generated_at']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
