import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from exam_bench.process import supervise,active_group
from exam_bench.submission import freeze,descriptor
from exam_bench.telemetry import normalize,api_estimate
from exam_bench.common import tree_manifest
from exam_bench.report import render

class ProcessTest(unittest.TestCase):
    def run_client(self,code,timeout=2):
        with tempfile.TemporaryDirectory() as td:
            r=supervise([sys.executable,'-c',code],td,dict(os.environ),'',timeout,.15,Path(td)/'raw')
            output=(Path(td)/'raw'/'stdout.jsonl').read_text()
            return r,output
    def test_success(self):
        r,out=self.run_client('print("ready")');self.assertEqual(r['status'],'completed');self.assertTrue(r['stop_confirmed']);self.assertIn('ready',out)
    def test_failure(self):
        r,_=self.run_client('raise SystemExit(7)');self.assertEqual(r['status'],'client_error');self.assertEqual(r['exit_code'],7)
    def test_timeout_with_descendant(self):
        r,_=self.run_client('import subprocess,sys,time;subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]);time.sleep(30)',.5)
        self.assertEqual(r['status'],'timeout');self.assertTrue(r['stop_confirmed']);self.assertFalse(active_group(r['pid']))
    def test_completed_root_stops_background_child(self):
        r,_=self.run_client('import subprocess,sys;subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"])')
        self.assertEqual(r['status'],'completed');self.assertTrue(r['stop_confirmed']);self.assertLess(r['elapsed_ms'],2500)
    def test_closed_pipes_do_not_bypass_timeout(self):
        r,_=self.run_client('import os,time;os.close(1);os.close(2);time.sleep(30)',.3)
        self.assertEqual(r['status'],'timeout');self.assertTrue(r['stop_confirmed'])

    def test_controller_interrupt_stops_group(self):
        import signal,threading
        with tempfile.TemporaryDirectory() as td:
            seen={}
            cancelled=threading.Event()
            def interrupt():
                import _thread
                if not cancelled.wait(.5): _thread.interrupt_main()
            import exam_bench.process as process
            original=process.subprocess.Popen
            def popen(*a,**k):
                child=original(*a,**k);seen['pid']=child.pid;return child
            process.subprocess.Popen=popen
            try:
                interrupter=threading.Thread(target=interrupt);interrupter.start()
                with self.assertRaises(KeyboardInterrupt):
                    supervise([sys.executable,'-c','import subprocess,sys,time;subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]);time.sleep(30)'],td,dict(os.environ),'',30,.15,Path(td)/'raw')
            finally:
                cancelled.set();interrupter.join();process.subprocess.Popen=original
            self.assertFalse(active_group(seen['pid']))

class TelemetryTest(unittest.TestCase):
    def event(self,usage,**kw):return json.dumps({'type':'turn.completed','usage':usage,**kw})
    def test_categories_not_double_counted(self):
        e=self.event({'input_tokens':100,'cached_input_tokens':70,'output_tokens':20,'reasoning_output_tokens':8},event_id='u1')
        r=normalize([e,e],True);self.assertEqual(r['tokens']['total'],120);self.assertEqual(r['tokens']['cached_input'],70);self.assertEqual(r['agents']['spawned_total'],0)
    def test_distinct_turns_equal_usage_not_deduplicated(self):
        e=self.event({'input_tokens':5,'output_tokens':1,'cached_input_tokens':0});self.assertEqual(normalize([e,e])['tokens']['total'],12)
    def test_missing_is_not_zero(self):
        r=normalize([self.event({'input_tokens':9})]);self.assertIsNone(r['tokens']['output']);self.assertIsNone(r['tokens']['total']);self.assertIsNone(r['agents']['spawned_total'])
    def test_unsupported_cumulative_scope(self):
        r=normalize([self.event({'input_tokens':10,'output_tokens':3,'usage_scope':'all_agents_cumulative'})]);self.assertIsNone(r['tokens']['total'])
    def test_bad_line_and_non_object(self):
        r=normalize(['not-json','[]']);self.assertEqual(len(r['limitations'])>0,True)
    def test_money_decimal(self):
        self.assertEqual(api_estimate({'input':1000000,'cached_input':500000,'output':100000},{'input_per_million':'2','cached_input_per_million':'.2','output_per_million':'10'}),'2.1')
        self.assertIsNone(api_estimate({'input':None},{}))

class SubmissionTest(unittest.TestCase):
    def test_freeze_is_an_independent_copy(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/'ws'/'out').mkdir(parents=True);(p/'ws'/'out'/'a').write_text('before')
            m=freeze(p/'ws',p/'frozen');(p/'ws'/'out'/'a').write_text('after');self.assertEqual(tree_manifest(p/'frozen'),m);self.assertEqual((p/'frozen'/'a').read_text(),'before')
    def test_symlinks_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/'out').mkdir()
            try:(p/'out'/'link').symlink_to('/etc/passwd')
            except OSError as exc:self.skipTest('Symlink permission unavailable: '+str(exc))
            with self.assertRaises(ValueError):freeze(p,p/'copy')
    def test_injected_metadata_reference_rejected(self):
        with self.assertRaises(ValueError):descriptor(Path('/tmp'),'Catalog.X;EXECUTE')

if __name__=='__main__':unittest.main()
