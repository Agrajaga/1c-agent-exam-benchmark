import hashlib
import csv
import json
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from pathlib import Path

from tools.build_result_site import ROOT, build, cohort_key, inside, normalize_charges, package_solution
from exam_bench.common import tree_manifest


class ResultSiteTest(unittest.TestCase):
    def test_unknown_assessment_is_not_zero(self):
        self.assertIsNone(normalize_charges(None, {}))

    def test_duplicate_observation_dropped_and_totals_are_an_interval(self):
        charge = {'penalty_id': 'P1', 'defect_id': 'payroll.fault', 'points_min': '0.5', 'points_max': '2', 'proof_kind': 'static', 'evidence': []}
        other = {**charge, 'penalty_id': 'P2', 'defect_id': 'payroll.other', 'points_min': '1', 'points_max': '1'}
        assessment = {'confirmed_deductions': {'min': '1.5', 'max': '3'}, 'charges': [charge, charge, other]}
        catalogue = {i: {'label': i, 'category': 'GEN'} for i in ('P1', 'P2')}
        result = normalize_charges(assessment, catalogue)
        self.assertEqual(len(result), 2)
        self.assertEqual([c['section'] for c in result], ['PR', 'PR'])
        with self.assertRaisesRegex(ValueError, 'Inconsistent'):
            normalize_charges({**assessment, 'confirmed_deductions': {'min': '1.5', 'max': '5'}}, catalogue)

    def test_different_limits_and_environment_are_different_cohorts(self):
        a = {'solve_timeout_seconds': 900, 'harness': 'none', 'model': 'a'}
        self.assertEqual(cohort_key(a, 'e1'), cohort_key({**a, 'model': 'b', 'harness': 'unica'}, 'e1'))
        self.assertNotEqual(cohort_key(a, 'e1'), cohort_key({**a, 'solve_timeout_seconds': 1800}, 'e1'))
        self.assertNotEqual(cohort_key(a, 'e1'), cohort_key(a, 'e2'))

    def test_paths_cannot_escape(self):
        with self.assertRaises(ValueError):
            inside(ROOT, '../outside')

    def test_archive_contains_unchanged_sources_but_not_logs_or_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / 'candidate'
            artifacts = run / 'artifacts'
            (artifacts / 'src').mkdir(parents=True)
            (artifacts / 'src/Configuration.xml').write_text('<original/>')
            (artifacts / 'auth.json').write_text('secret')
            (artifacts / 'log.txt').write_text('account details')
            (run / 'artifact-manifest.json').write_text(json.dumps(tree_manifest(artifacts)))
            dist = Path(tmp) / 'dist'
            links = package_solution(run, dist)
            with zipfile.ZipFile(dist / links[0]['url']) as z:
                self.assertNotIn('auth.json', z.namelist())
                self.assertNotIn('log.txt', z.namelist())
                self.assertEqual(z.read('src/Configuration.xml'), b'<original/>')
            before = links[0]['sha256']
            with patch('zipfile.time.localtime', return_value=(2030, 6, 2, 12, 0, 0, 0, 1, 0)):
                self.assertEqual(package_solution(run, dist)[0]['sha256'], before)
            (artifacts / 'src/Configuration.xml').write_text('<changed/>')
            with self.assertRaisesRegex(ValueError, 'Frozen artifacts changed'):
                package_solution(run, dist)

    def test_new_completed_attempt_accumulates_without_changing_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'site').mkdir()
            for name in ('index.html', 'style.css', 'measure.js'):
                shutil.copyfile(ROOT / 'site' / name, root / 'site' / name)
            config = json.loads((ROOT / 'site/catalogue.json').read_text())
            config['assessments'] = []
            config['exclusions'] = []
            config.pop('campaign_state_ref', None)
            (root / 'site/catalogue.json').write_text(json.dumps(config))
            task = config['tasks'][0]['directory']
            for name in ('manifest.json', 'private/rules.json', 'private/official-assessment-mapping.json'):
                target = root / task / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / task / name, target)
            passport = root / '.local/environment-verified-v1/passport.json'
            passport.parent.mkdir(parents=True)
            passport.write_text(json.dumps({'os':'synthetic-test-os','platform_binary':'/synthetic/8.3/1cv8'}),encoding='utf-8')
            def add(identifier):
                run = root / '.local/runs' / identifier
                (run/'artifacts/src').mkdir(parents=True)
                (run/'artifacts/src/Configuration.xml').write_text('<synthetic/>')
                from exam_bench.common import write_json, digest
                write_json(run/'artifact-manifest.json', tree_manifest(run/'artifacts'))
                manifest = json.loads((root/task/'manifest.json').read_text())
                plan = dict(run_id=identifier, purpose=config['purpose'],
                            statement_sha256=manifest['public']['statement_sha256'],
                            harness='none', client_version='test', reasoning_effort='medium',
                            network_profile='open-book_shell', delegation='native_disabled',
                            profile_sha256='synthetic', solve_timeout_seconds=1800)
                write_json(run/'plan.json', plan)
                write_json(run/'preflight.json', {'environment_sha256':digest(passport)})
                result = dict(run_id=identifier, model={'requested':'gpt-6.1-sol','provenance':'requested_only'},
                              harness='none', time={'solve_ms':100,'prepare_ms':1,'grade_ms':None},
                              metrics={'tokens':{'total':10},'agents':{'spawned_total':0}},
                              billing={}, process={'status':'completed'}, submission={'error':None},
                              grade={'status':'not_run','rules':[]})
                write_json(run/'result.json', result)
                (run / 'plan-integrity.json').write_text(json.dumps({'sha256': hashlib.sha256((run / 'plan.json').read_bytes()).hexdigest()}))
            add('attempt-a')
            self.assertEqual(len(build(root)['runs']), 1)
            add('attempt-b')
            data = build(root)
            self.assertEqual({r['id'] for r in data['runs']}, {'attempt-a', 'attempt-b'})
            self.assertTrue(all(r['deductions'] is None for r in data['runs']))

    @unittest.skipUnless((ROOT/'.local/environment-verified-v1/passport.json').is_file(), 'Historical campaign evidence is in the transfer archive, outside Git')
    def test_real_export_is_consistent_and_sanitized(self):
        data = build()
        for run in data['runs']:
            self.assertFalse(run['whole_ticket_attested'])
            if run['penalties'] is None:
                self.assertIsNone(run['deductions'])
                self.assertIsNone(run['exact_score'])
            else:
                from decimal import Decimal
                self.assertEqual(sum(Decimal(c['points']) for c in run['penalties']), Decimal(run['deductions']))
        payload = json.dumps(data)
        for forbidden in ('access_token', 'refresh_token', 'account_fingerprint', 'quota_before', 'credits', '/Users/', '/private/var/'):
            self.assertNotIn(forbidden, payload)
        dist = ROOT / 'site/dist'
        with (dist/'tokens.csv').open(encoding='utf-8-sig', newline='') as f:
            exported = {r['run_id']: r for r in csv.DictReader(f)}
        for run in data['runs']:
            original = json.loads((ROOT/'.local/runs'/run['id']/'result.json').read_text())['metrics']['tokens']
            for field in ('total','input','output','cached_input','reasoning_output'):
                self.assertEqual(run['tokens'].get(field), original.get(field))
                self.assertEqual(exported[run['id']][field], '' if original.get(field) is None else str(original[field]))
            if run['tokens'].get('input') is not None and run['tokens'].get('cached_input') is not None:
                self.assertEqual(run['tokens']['fresh_input'], run['tokens']['input'] - run['tokens']['cached_input'])
            for download in run['downloads']:
                file = inside(dist, download['url'])
                self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(), download['sha256'])
