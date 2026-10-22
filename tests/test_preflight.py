import copy,json,unittest
from pathlib import Path
from exam_bench.preflight import validate_plan
class PlanTest(unittest.TestCase):
    def setUp(self):self.p=json.loads(Path('profiles/codex-probe-plan.json').read_text())
    def test_explicit_model_and_limits(self):self.assertTrue(validate_plan(self.p))
    def test_missing_model(self):
        del self.p['model']
        with self.assertRaisesRegex(ValueError,'model'):validate_plan(self.p)
    def test_bad_time(self):
        self.p['solve_timeout_seconds']=True
        with self.assertRaises(ValueError):validate_plan(self.p)
    def test_no_silent_profile_switch(self):
        self.p['harness']='unica'
        with self.assertRaises(ValueError):validate_plan(self.p)
    def test_exact_supported_unica_version(self):
        self.p['harness']='unica-0.13.0'
        self.assertTrue(validate_plan(self.p))
        self.p['harness']='unica-0.13.0-rc.7'
        with self.assertRaises(ValueError):validate_plan(self.p)

class IntegrationBoundaryTest(unittest.TestCase):
    def test_dependency_change_invalidates_calibration(self):
        from exam_bench.preflight import verify_calibration
        from exam_bench.common import grading_fingerprint,digest
        from exam_bench import grader
        c={'accepted':True,'readonly_sources_verified':True,'grader_sha256':digest(grader.__file__),'implementation_files':grading_fingerprint()}
        verify_calibration(c)
        c['implementation_files']['observer.py']='different'
        with self.assertRaisesRegex(ValueError,'stale'):verify_calibration(c)

    def test_worker_receives_no_private_acceptance_plan(self):
        from exam_bench.codex import public_plan_values
        p={'run_id':'test','model':'gpt-5.6-sol','acceptance_profile':'private-scope',
           'purpose':'grade BU only','grader_sha256':'private-hash',
           'implementation_files':{'grader.py':'private-hash'}}
        self.assertEqual(public_plan_values(p),{'run_id':'test','model':'gpt-5.6-sol'})

    def test_repeated_run_id_reserves_once(self):
        import tempfile
        from exam_bench.codex import prepare
        p=json.loads(Path('profiles/codex-probe-plan.json').read_text())
        with tempfile.TemporaryDirectory() as td:
            run=Path(td)/'already-reserved';run.mkdir()
            with self.assertRaises(FileExistsError):prepare(p,run,Path('/unavailable'),Path('/unavailable'),Path('/unavailable'),Path('/unavailable'))
