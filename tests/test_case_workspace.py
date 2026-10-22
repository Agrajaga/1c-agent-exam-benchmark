import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from exam_bench.workspaces import case_workspace


class CaseWorkspace(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Short Windows workspace')
    def test_deep_sources_are_archived_and_runtime_database_is_discarded(self):
        with tempfile.TemporaryDirectory() as td:
            evidence=Path(td)/('a'*70)/('b'*70)
            with case_workspace(evidence) as work:
                self.assertLess(len(str(work)),100)
                (work/'ib').mkdir();(work/'ib/data').write_bytes(b'disposable')
                source=work/'observed-src'/('long-metadata-'*8)/'module.bsl'
                source.parent.mkdir(parents=True);source.write_text('source',encoding='utf-8')
                (work/'observations.json').write_text('{}',encoding='utf-8')
            self.assertFalse(work.exists())
            self.assertFalse((evidence/'ib').exists())
            self.assertEqual((evidence/'observations.json').read_text(encoding='utf-8'),'{}')
            with zipfile.ZipFile(evidence/'observed-src.zip') as archive:
                self.assertEqual(archive.read(('long-metadata-'*8)+'/module.bsl'),b'source')

    @unittest.skipUnless(os.name=='nt','Short Windows workspace')
    def test_failure_keeps_diagnostic_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'evidence'
            with self.assertRaisesRegex(RuntimeError,'failure'):
                with case_workspace(target) as work:
                    (work/'error.log').write_text('reason',encoding='utf-8')
                    raise RuntimeError('failure')
            self.assertEqual((target/'error.log').read_text(encoding='utf-8'),'reason')

    @unittest.skipIf(os.name=='nt','POSIX retains the existing evidence layout')
    def test_posix_keeps_existing_layout(self):
        with tempfile.TemporaryDirectory() as td:
            with case_workspace(td) as work:
                self.assertEqual(work,Path(td).resolve())
