"""Discovery works offline and never modifies client configuration."""
import contextlib
import io
import json
import unittest
from unittest import mock

from stb_cli.discovery import handle_discovery_command
from stb_cli.parser import parser
from stb_cli.main import main


class CLIDiscoveryTest(unittest.TestCase):
    def test_offline_discovery_and_custom_socket(self):
        for command in ("discover", "mcp"):
            args = parser().parse_args(["--bridge-socket", "/tmp/custom socket", command, "--json"])
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(handle_discovery_command(args), 0)
            info = json.loads(output.getvalue())
            self.assertTrue(info["discovery_only"])
            self.assertFalse(info["requires_skill"])
            self.assertIn("/tmp/custom socket", info["mcp"]["args"])
            self.assertIn("terminal_run", info["workflow"])

    def test_help_and_human_guide(self):
        self.assertIn("discover", parser().format_help())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            handle_discovery_command(parser().parse_args(["mcp"]))
        self.assertIn("codex mcp add", output.getvalue())
        self.assertIn("660", output.getvalue())

    def test_no_arguments_shows_first_use_guidance(self):
        output = io.StringIO()
        with mock.patch("sys.argv", ["stb"]), contextlib.redirect_stdout(output):
            self.assertEqual(main(), 0)
        help_text = output.getvalue()
        self.assertIn("stb discover --json", help_text)
        self.assertIn("stb mcp", help_text)
        self.assertLess(help_text.index("首次使用"), help_text.index("可用命令"))
