"""CLI text and Base64 converge before one Core run call."""
import base64
import contextlib
import io
import json
import unittest
from unittest.mock import patch
from stb_cli.parser import parser
from stb_cli.commands_execution import handle_execution_command


class CliRunTest(unittest.TestCase):
    def test_removed_commands_and_help(self):
        for command in ('lease', 'release', 'watch', 'waits', 'cancel-wait', 'panes', 'jobs', 'create', 'enter', 'stop', 'daemon', 'history', 'cleanup-tasks', 'mcp'):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parser().parse_args([command])
        help_text = parser().format_help()
        self.assertNotIn('stb lease', help_text)
        self.assertNotIn('stb watch', help_text)
        self.assertNotIn('cancel-wait', help_text)
        self.assertNotIn('列出当前活动的等待请求', help_text)
        for command in ('wait', 'interrupt'):
            self.assertIn(command, help_text)

    def test_removed_stdio_and_invalid_encoding_never_call_core(self):
        for command, target in (("run", "ops"),):
            for flag in ("--stdio", "--stdin"):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    parser().parse_args([command, target, flag])
            with patch("stb_cli.commands_execution.bridge_call") as call:
                with self.assertRaises(RuntimeError):
                    handle_execution_command(parser().parse_args([command, target, "--base64", "!!"]))
                call.assert_not_called()

    def test_interrupt_is_one_job_bound_call(self):
        with patch('stb_cli.commands_execution.bridge_call', return_value={'termination_confirmed': True}) as call, \
                contextlib.redirect_stdout(io.StringIO()):
            handle_execution_command(parser().parse_args(['interrupt', 'job-real', '--seconds', '4']))
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[1:], ('terminal_interrupt_job', {'job_id': 'job-real', 'wait_ms': 4000}))

    def test_input_command_removed(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser().parse_args(["input", "job-one", "--text", "yes"])

    def test_discovery_has_exact_cli_routing_rule(self):
        from stb_cli.discovery import discovery
        from pathlib import Path
        guidance = discovery(Path('/tmp/test-stb.sock'))['cli_execution']
        for term in ("200 个 Unicode 字符", "单引号", "双引号",
                     "反斜杠", "反引号", "$"):
            self.assertIn(term, guidance)
        for term in ("stb run 会话名 --text '命令正文'", "stb run 会话名 --base64 PAYLOAD", "都是 run 的参数"):
            self.assertIn(term, guidance)

    def test_mcp_run_does_not_require_model_generated_id(self):
        from mcp_server.tools.tasks import TOOLS
        schema = next(item for item in TOOLS if item['name'] == 'terminal_run')['inputSchema']
        self.assertEqual(schema['required'], ['pane', 'text'])

    def test_both_modes_preserve_text_and_core_owns_id(self):
        text = r"""printf '%s\n' "$HOME" '中文'"""
        for options in (["--text", text], ["--base64", base64.b64encode(text.encode()).decode()]):
            calls = []
            def call(socket, method, params=None):
                calls.append((method, params))
                return {"terminal_session_resolve": {"name": "test", "pane": "%0"},
                        "bridge_info": {"run_auto_request_id": True},
                        "terminal_run": {"job_id": "job-test"}}[method]
            output = io.StringIO()
            with patch("stb_cli.commands_execution.bridge_call", side_effect=call), \
                    patch("sys.stdin", io.StringIO(text + "\n")), contextlib.redirect_stdout(output):
                handle_execution_command(parser().parse_args(["run", "test", *options]))
            self.assertEqual(json.loads(output.getvalue())["job_id"], "job-test")
            self.assertEqual(calls[-1][1]["text"], text)
            self.assertNotIn("request_id", calls[-1][1])
            self.assertEqual([m for m, p in calls].count("terminal_run"), 1)
