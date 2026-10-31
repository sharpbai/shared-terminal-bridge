"""Bootstrap/context are bounded read-only discovery, never execution."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch
from stb_cli.bootstrap import handle_context_command
from stb_cli.parser import parser
from bridge.agent_instructions import INSTRUCTIONS


class CliBootstrapTest(unittest.TestCase):
    def call(self, argv, ready=True):
        calls = []
        def bridge(socket, method, params=None):
            calls.append((method, params))
            return {
                'bridge_info': {'run_auto_request_id': ready, 'input_auto_request_id': ready,
                                'terminal_run': 'receipt-scoped-run-v1', 'model_tasks': 'job-authority-v2'},
                'terminal_session_resolve': {'name': 'ops', 'pane': '%4'},
                'terminal_state': {'current_command': 'ssh'},
                'terminal_read': {'content': 'root@target:~# ',
                                  'execution': {'human_override': True,
                                                'interrupt_source': {'source': 'human'}},
                                  'truncated': False},
            }[method]
        output = io.StringIO()
        with patch('stb_cli.bootstrap.bridge_call', side_effect=bridge), contextlib.redirect_stdout(output):
            self.assertEqual(handle_context_command(parser().parse_args(argv)), 0)
        return json.loads(output.getvalue()), calls

    def test_context_resolves_exact_name_and_reads_bounded_screen(self):
        result, calls = self.call(['context', 'ops', '--lines', '12'])
        self.assertEqual(calls, [('terminal_session_resolve', {'name': 'ops'}),
                                ('terminal_state', {'pane': '%4'}),
                                ('terminal_read', {'pane': '%4', 'lines': 12})])
        self.assertEqual(result['context']['content'], 'root@target:~# ')
        self.assertNotIn('instructions', result)

    def test_bootstrap_includes_context_rules_and_templates_without_writing(self):
        result, calls = self.call(['bootstrap', 'ops'])
        self.assertEqual([m for m, p in calls], ['bridge_info', 'terminal_session_resolve', 'terminal_state', 'terminal_read'])
        self.assertTrue(result['bootstrap_result']['ready'])
        self.assertFalse(result['bootstrap_result']['task_executed'])
        self.assertEqual(result['instructions'], INSTRUCTIONS)
        self.assertIn('context', result['commands'])
        self.assertEqual(result['request_templates']['run']['base64'], 'stb run ops --base64 PAYLOAD')
        self.assertEqual(result['request_templates']['wait'], 'stb wait JOB_ID --seconds 60')
        self.assertIn('1–600', result['commands']['wait'])
        self.assertNotIn('RDC', json.dumps(result))
        self.assertNotIn('stb-manage', json.dumps(result))

    def test_incompatible_core_does_not_advertise_run_or_fallback(self):
        result, calls = self.call(['bootstrap', 'ops'], ready=False)
        self.assertFalse(result['bootstrap_result']['ready'])
        self.assertNotIn('run', result['request_templates'])
        self.assertNotIn('terminal_run', [m for m, p in calls])

    def test_only_bootstrap_omits_previous_interrupt_metadata(self):
        result, _ = self.call(['bootstrap', 'ops'])
        self.assertNotIn('execution', result['context'])
        self.assertEqual(result['context']['content'], 'root@target:~# ')
        context, _ = self.call(['context', 'ops'])
        self.assertTrue(context['context']['execution']['human_override'])
        self.assertEqual(context['context']['execution']['interrupt_source'], {'source': 'human'})

    def test_default_observation_budgets(self):
        cli = parser()
        for command in ("bootstrap", "context"):
            self.assertEqual(cli.parse_args([command, "ops"]).lines, 40)
        self.assertEqual(cli.parse_args(["run", "ops", "--text", "pwd"]).wait_ms, 60000)
        for command in ("wait", "interrupt"):
            self.assertEqual(cli.parse_args([command, "job-1"]).seconds, 60)

    def test_bad_line_budget_fails_before_reading(self):
        for value in ('0', '101', '-1'):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parser().parse_args(['context', 'ops', '--lines', value])
