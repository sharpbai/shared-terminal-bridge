"""Discovery works offline and never modifies client configuration."""
import contextlib
import io
import json
import unittest
from unittest import mock

from stb_cli.discovery import handle_discovery_command
from stb_cli.parser import parser
from stb_manage.parser import parser as management_parser
from stb_cli.main import main


class CLIDiscoveryTest(unittest.TestCase):
    def test_discover_contains_exact_shared_mcp_instructions(self):
        from bridge.agent_instructions import INSTRUCTIONS
        from mcp_server.runtime.protocol import INSTRUCTIONS as MCP_INSTRUCTIONS
        from stb_cli.discovery import discovery
        from stb_cli.config import DEFAULT_BRIDGE_SOCKET
        self.assertEqual(discovery(DEFAULT_BRIDGE_SOCKET)['instructions'], MCP_INSTRUCTIONS)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            handle_discovery_command(parser().parse_args(['discover']))
        self.assertIn(INSTRUCTIONS, output.getvalue())
        for argv in ([], ['run', '--help']):
            output = io.StringIO()
            with mock.patch('sys.argv', ['stb', *argv]), contextlib.redirect_stdout(output):
                if argv:
                    with self.assertRaises(SystemExit):
                        main()
                else:
                    main()
            self.assertNotIn('200', output.getvalue())
        self.assertIn('200 个 Unicode 字符', discovery(DEFAULT_BRIDGE_SOCKET)['cli_execution'])
    def test_offline_discovery_and_custom_socket(self):
        for command in ("discover", "mcp"):
            argv = ["--bridge-socket", "/tmp/custom socket", command, "--json"] if command == "mcp" else [command, "--json"]
            args = (management_parser() if command == "mcp" else parser()).parse_args(argv)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(handle_discovery_command(args), 0)
            info = json.loads(output.getvalue())
            self.assertTrue(info["discovery_only"])
            self.assertFalse(info["requires_skill"])
            if command == "mcp":
                self.assertIn("/tmp/custom socket", info["mcp"]["args"])
            else:
                self.assertNotIn("mcp", info)
                self.assertNotIn("--bridge-socket", json.dumps(info))
                self.assertNotIn("stb-manage", json.dumps(info))
                self.assertNotIn("human_commands", info)
            self.assertIn("terminal_run", info["workflow"])

    def test_help_and_human_guide(self):
        self.assertIn("discover", parser().format_help())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            handle_discovery_command(management_parser().parse_args(["mcp"]))
        self.assertIn("codex mcp add", output.getvalue())
        self.assertIn("660", output.getvalue())

    def test_no_arguments_shows_first_use_guidance(self):
        output = io.StringIO()
        with mock.patch("sys.argv", ["stb"]), contextlib.redirect_stdout(output):
            self.assertEqual(main(), 0)
        help_text = output.getvalue()
        self.assertIn("stb bootstrap 会话名", help_text)
        self.assertNotIn("stb discover --json", help_text)
        self.assertIn("discover", help_text)
        self.assertNotIn("stb-manage", help_text)
        self.assertLess(help_text.index("首次使用"), help_text.index("可用命令"))
