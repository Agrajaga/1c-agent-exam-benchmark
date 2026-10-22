import unittest
from exam_bench.harness import tool_usage


class HarnessUsageTest(unittest.TestCase):
    def test_completed_calls_deduplicate_by_item_id(self):
        item={'id':'1','type':'mcp_tool_call','server':'unica','tool':'unica.view','status':'completed','error':None}
        done={'native':{'type':'item.completed','item':item}}
        start={'native':{'type':'item.started','item':item}}
        failed={'native':{'type':'item.completed','item':{**item,'id':'2','status':'failed','error':{'message':'backend failed'}}}}
        u=tool_usage([start,done,done,failed])
        self.assertEqual((u['mcp_calls'],u['unica_calls'],u['failed_calls']),(2,2,1))

    @unittest.skipIf(__import__('os').name=='nt', 'Legacy Unica POSIX runtime; portable execution uses harness=none')
    def test_detached_owned_runtime_stops_without_killing_unrelated_process(self):
        import tempfile,subprocess,sys,time,shutil
        from pathlib import Path
        from exam_bench.harness import stop_owned_runtimes
        with tempfile.TemporaryDirectory() as td:
            root=Path(td).resolve();exe=root/'client-home/unica/native-sleep'
            exe.parent.mkdir(parents=True);exe.symlink_to('/bin/sleep')
            owned=subprocess.Popen([str(exe),'30'],start_new_session=True)
            foreign=subprocess.Popen(['/bin/sleep','30'],start_new_session=True)
            try:
                time.sleep(.1)
                self.assertIsNone(owned.poll())
                result=stop_owned_runtimes(root,.2)
                owned.wait(timeout=2)
                self.assertTrue(result['stop_confirmed']);self.assertEqual(result['owned_runtimes_found'],1)
                self.assertIsNone(foreign.poll())
            finally:
                for p in (owned,foreign):
                    if p.poll() is None:p.terminate()
                    p.wait(timeout=2)
