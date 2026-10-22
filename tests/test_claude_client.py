import json
import unittest

from exam_bench.claude import normalize, SETTINGS, DENIED_TOOLS
from exam_bench.preflight import claude_mcp_call_succeeded, validate_plan


STREAM = [
    {'type': 'system', 'subtype': 'init', 'model': 'claude-opus-5-5'},
    {'type': 'assistant', 'message': {'model': 'claude-opus-5-5', 'content': [
        {'type': 'tool_use', 'id': 't1', 'name': 'mcp__unica__unica_view', 'input': {}},
        {'type': 'tool_use', 'id': 't2', 'name': 'Bash', 'input': {}}]}},
    {'type': 'user', 'message': {'content': [
        {'type': 'tool_result', 'tool_use_id': 't1', 'content': [{'type': 'text', 'text': json.dumps({'ok': True})}]},
        {'type': 'tool_result', 'tool_use_id': 't2', 'content': 'done'}]}},
    {'type': 'result', 'total_cost_usd': 1.25, 'modelUsage': {'claude-opus-5-5': {
        'inputTokens': 100, 'cacheReadInputTokens': 900, 'cacheCreationInputTokens': 50, 'outputTokens': 40}}},
]


class ClaudeTelemetry(unittest.TestCase):
    def test_usage_cost_and_tools(self):
        parsed = normalize([json.dumps(e) for e in STREAM])
        self.assertEqual(parsed['tokens']['input'], 1050)
        self.assertEqual(parsed['tokens']['cached_input'], 900)
        self.assertEqual(parsed['tokens']['fresh_input'], 150)
        self.assertEqual(parsed['tokens']['total'], 1090)
        self.assertEqual(parsed['native_cost_usd'], 1.25)
        self.assertEqual(parsed['models_observed'], ['claude-opus-5-5'])
        self.assertEqual((parsed['tools']['mcp_calls'], parsed['tools']['unica_calls'], parsed['tools']['failed_calls']), (1, 1, 0))
        self.assertEqual(parsed['agents']['spawned_total'], 0)

    def test_missing_result_is_a_limitation(self):
        parsed = normalize([json.dumps(STREAM[0])])
        self.assertIsNone(parsed['tokens']['total'])
        self.assertTrue(parsed['limitations'])

    def test_unica_probe_reads_the_tool_result(self):
        self.assertTrue(claude_mcp_call_succeeded(STREAM, 'unica.view'))
        failed = [dict(e) for e in STREAM]
        failed[2] = {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't1', 'content': [{'type': 'text', 'text': '{"ok": false}'}]}]}}
        self.assertFalse(claude_mcp_call_succeeded(failed, 'unica.view'))


class ClaudeIsolation(unittest.TestCase):
    def test_memory_web_and_subagents_off(self):
        self.assertIs(SETTINGS['autoMemoryEnabled'], False)
        self.assertTrue({'WebSearch', 'WebFetch', 'Task', 'Agent'} <= set(DENIED_TOOLS))

    def test_plan_requires_a_claude_model_for_the_claude_client(self):
        base = {'schema_version': 1, 'run_id': 'x', 'client': 'claude', 'client_version': '2.1.290', 'model': 'gpt-6.1-sol',
                'reasoning_effort': 'medium', 'billing_channel': 'subscription', 'harness': 'none', 'solve_timeout_seconds': 1800,
                'stop_grace_seconds': 3, 'input_revision': 'x'}
        with self.assertRaises(ValueError):
            validate_plan(base)


if __name__ == '__main__':
    unittest.main()
