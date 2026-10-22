import json,tempfile,unittest
from pathlib import Path
from exam_bench.telemetry import native_session_usage, token_breakdown, normalize

class NativeUsageTest(unittest.TestCase):
    def test_breakdown_preserves_total_and_input_including_cache(self):
        original = {'input':100, 'cached_input':80, 'output':20, 'total':120}
        detailed = token_breakdown(original)
        self.assertEqual(detailed['fresh_input'], 20)
        self.assertEqual(detailed['total'], detailed['input'] + detailed['output'])
        self.assertNotIn('fresh_input', original)
        event = json.dumps({'type':'turn.completed','usage':{'input_tokens':100,'cached_input_tokens':80,'output_tokens':20}})
        self.assertEqual(normalize([event], True)['tokens']['fresh_input'], 20)
    def test_missing_or_invalid_cache_is_not_zero(self):
        for cached in (None, -1, 101, True):
            self.assertIsNone(token_breakdown({'input':100,'cached_input':cached})['fresh_input'])
        self.assertEqual(token_breakdown({'input':0,'cached_input':0})['fresh_input'], 0)
    def write(self,home,name,snapshots):
        p=home/'sessions'/name;p.parent.mkdir(parents=True,exist_ok=True)
        lines=[{'type':'session_meta','payload':{'id':name}}]
        for x in snapshots:lines.append({'type':'event_msg','payload':{'type':'token_count','info':{'total_token_usage':x}}})
        p.write_text('\n'.join(json.dumps(x) for x in lines))
    def test_cumulative_snapshots_are_not_summed(self):
        with tempfile.TemporaryDirectory() as td:
            h=Path(td);self.write(h,'root.jsonl',[{'input_tokens':10,'output_tokens':2,'cached_input_tokens':0},{'input_tokens':30,'output_tokens':8,'cached_input_tokens':10}])
            r=native_session_usage(h);self.assertEqual(r['tokens']['total'],38);self.assertEqual(len(r['counter_events']),2)
            self.assertEqual(r['tokens']['fresh_input'],20)
    def test_multiple_sessions_do_not_double_count_children(self):
        with tempfile.TemporaryDirectory() as td:
            h=Path(td)
            for name in ('root.jsonl','child.jsonl'):self.write(h,name,[{'input_tokens':10,'output_tokens':2}])
            self.assertIsNone(native_session_usage(h)['tokens'])
    def test_unreported_cached_reasoning_are_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            h=Path(td);self.write(h,'root.jsonl',[{'input_tokens':10,'output_tokens':2}])
            r=native_session_usage(h);self.assertIsNone(r['tokens']['cached_input']);self.assertIsNone(r['tokens']['reasoning_output'])
