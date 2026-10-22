import json
import tempfile
import unittest
from pathlib import Path

from exam_bench.harness import PROFILE_FILES, profile_path
from exam_bench.mcp_toolkit import DANGER, NAME, URL, EPF, call_succeeded


def text(payload):
    return json.dumps(payload, ensure_ascii=False)


class Toolkit(unittest.TestCase):
    def test_profile_pins_the_release_and_the_author_maximum_of_approvals(self):
        self.assertIn(NAME, PROFILE_FILES)
        profile = json.loads(profile_path(NAME).read_text())
        self.assertEqual(profile['source_commit'], 'c36aba2fc744f27c8fc8084b4d231732bad0837c')
        self.assertEqual(profile['skills'], ['calling-1c-rest-api-via-curl', 'composing-1c-queries'])
        self.assertEqual(DANGER, {'danger_auto_write': True, 'danger_auto_priv': True, 'danger_confirm': False})
        self.assertEqual(URL, 'http://127.0.0.1:6003/mcp')

    def test_codex_call_counts_only_a_successful_payload(self):
        def item(payload, status='completed'):
            return {'type': 'item.completed', 'item': {'type': 'mcp_tool_call', 'server': 'onec', 'tool': 'execute_query', 'status': status,
                                                       'error': None, 'result': {'content': [{'type': 'text', 'text': text(payload)}]}}}
        self.assertTrue(call_succeeded([item({'success': True, 'data': 'x'})], 'execute_query', 'codex'))
        self.assertFalse(call_succeeded([item({'success': False, 'error': 'Операция запрещена'})], 'execute_query', 'codex'))
        self.assertFalse(call_succeeded([item({'success': True}, status='failed')], 'execute_query', 'codex'))

    def test_claude_call_matches_tool_use_and_result(self):
        events = [{'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 't1', 'name': 'mcp__onec__get_metadata'}]}},
                  {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't1', 'content': [{'type': 'text', 'text': text({'success': True})}]}]}}]
        self.assertTrue(call_succeeded(events, 'get_metadata', 'claude'))
        self.assertFalse(call_succeeded(events, 'execute_query', 'claude'))

    def test_registration_for_both_clients(self):
        from exam_bench import mcp_toolkit
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for client in ('codex', 'claude'):
                ws, runtime, run = root / client / 'ws', root / client / 'runtime', root / client / 'run'
                for p in (ws, runtime / 'skills', run):
                    p.mkdir(parents=True)
                try:
                    harness, mcp = mcp_toolkit.configure(ws, runtime, run, client)
                except (ValueError, FileNotFoundError) as exc:
                    self.skipTest('pinned package absent: %s' % exc)
                self.assertTrue((ws / 'harness/mcp-toolkit'/EPF).is_file())
                self.assertTrue((runtime / 'skills/composing-1c-queries/SKILL.md').is_file())
                if client == 'codex':
                    self.assertIn('url = "%s"' % URL, harness['codex_config'])
                else:
                    self.assertEqual(json.loads(mcp.read_text())['mcpServers']['onec'], {'type': 'http', 'url': URL})


class StdioHarnesses(unittest.TestCase):
    def test_registration_and_second_model_off(self):
        from exam_bench.stdio_harnesses import HARNESSES, codex_overrides, server_spec
        ws = Path('/w')
        for name in HARNESSES:
            self.assertIn(name, PROFILE_FILES)
            command, args, env = server_spec(name, ws)
            self.assertTrue(command.replace('\\','/').startswith('/w/harness/') or command.endswith('/java'))
            self.assertTrue(any('mcp_servers.%s.command=' % HARNESSES[name]['server'] in a for a in codex_overrides(name, ws)))
        _, _, env = server_spec('rlm-tools-bsl-1.43.0', ws)
        self.assertEqual((env['_RLM_SERVICE_NO_ENV'], env['ANTHROPIC_API_KEY'], env['RLM_LLM_BASE_URL'], env['RLM_LLM_MODEL']), ('1', '', '', ''))
        command, args, _ = server_spec('bsl-analyzer-0.3.2', ws)
        self.assertNotIn('--onec-url', args)

    def test_probe_call_detection(self):
        from exam_bench.stdio_harnesses import call_succeeded
        ok = {'type': 'item.completed', 'item': {'type': 'mcp_tool_call', 'server': 'code-index', 'tool': 'get_object_structure', 'status': 'completed', 'error': None, 'result': {'content': []}}}
        self.assertTrue(call_succeeded([ok], 'code-index-1.9.0', 'codex'))
        bad = {**ok, 'item': {**ok['item'], 'result': {'isError': True}}}
        self.assertFalse(call_succeeded([bad], 'code-index-1.9.0', 'codex'))


if __name__ == '__main__':
    unittest.main()
