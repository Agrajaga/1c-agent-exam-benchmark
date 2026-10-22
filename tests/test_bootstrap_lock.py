import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class HostBootstrapLockTest(unittest.TestCase):
    def test_independent_preparations_cannot_overlap(self):
        # A live subprocess attempts a nonblocking host lock while the parent
        # owns it; after release that very process must be able to acquire it.
        from exam_bench.codex import bootstrap_lock
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'lock'
            code='''import sys
from exam_bench.locking import file_lock
try:
 with file_lock(sys.argv[1], blocking=False):
  print('acquired')
except BlockingIOError:
 print('blocked')
'''
            with bootstrap_lock(path):
                result=subprocess.run([sys.executable,'-c',code,str(path)],capture_output=True,text=True,check=True)
                self.assertEqual(result.stdout.strip(),'blocked')
            result=subprocess.run([sys.executable,'-c',code,str(path)],capture_output=True,text=True,check=True)
            self.assertEqual(result.stdout.strip(),'acquired')
