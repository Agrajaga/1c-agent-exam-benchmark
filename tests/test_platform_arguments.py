import unittest
from unittest.mock import patch
from exam_bench.platform import platform_argv


class PlatformArguments(unittest.TestCase):
    def test_windows_nested_quotes_follow_1c_syntax(self):
        args=['C:/Program Files/1cv8/bin/1cv8.exe','CREATEINFOBASE',
              'File="C:/test bases/my base";','/Out','C:/test logs/log.txt']
        with patch('exam_bench.platform.os.name','nt'):
            actual=platform_argv(args)
        self.assertIn('"File=""C:/test bases/my base"";"',actual)
        self.assertNotIn('\\"',actual)
        self.assertTrue(actual.endswith('/Out "C:/test logs/log.txt"'))

    def test_posix_keeps_an_argument_vector(self):
        args=['/opt/1cv8/1cv8','CREATEINFOBASE','File="/tmp/test bases";']
        with patch('exam_bench.platform.os.name','posix'):
            self.assertIs(platform_argv(args),args)

    def test_designer_uses_standard_subprocess_arguments(self):
        args=['C:/Program Files/1cv8/bin/1cv8.exe','DESIGNER','/F','C:/test bases/my base']
        with patch('exam_bench.platform.os.name','nt'):
            self.assertIs(platform_argv(args),args)
