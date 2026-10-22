import tempfile,unittest
from pathlib import Path
from exam_bench.observer import inject
from exam_bench.common import tree_manifest
class ObserverTest(unittest.TestCase):
    def test_readonly_submission_is_never_modified(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);s=p/'frozen';s.mkdir();c=s/'Configuration.xml'
            c.write_text('<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config"><Configuration><ChildObjects/></Configuration></MetaDataObject>'.replace('<ChildObjects/>','<ChildObjects></ChildObjects>'))
            c.chmod(0o444);before=tree_manifest(s)
            target=inject(s,p/'copy','Функция Run() Экспорт Возврат Истина; КонецФункции')
            self.assertEqual(tree_manifest(s),before);self.assertEqual(c.stat().st_mode & 0o222,0)
            self.assertIn('BenchmarkObserver',(target/'Configuration.xml').read_text())
            self.assertIn('xmlns:cfg=',(target/'Configuration.xml').read_text())
