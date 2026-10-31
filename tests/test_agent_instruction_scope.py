"""STB instructions stay transport-neutral across MCP and CLI discovery."""
import unittest
from bridge.agent_instructions import INSTRUCTIONS
from mcp_server.server import MinimalMCPServer, LEGACY_VERSION
from tests.mcp_support import FakeBridgeV9
from stb_cli.discovery import discovery
from stb_cli.config import DEFAULT_BRIDGE_SOCKET


class InstructionScopeTest(unittest.TestCase):
    def test_mcp_and_cli_share_transport_neutral_rules(self):
        server = MinimalMCPServer(FakeBridgeV9())
        instructions = [server.discover()["instructions"],
                        server.initialize({"protocolVersion": LEGACY_VERSION})["instructions"],
                        discovery(DEFAULT_BRIDGE_SOCKET)["instructions"]]
        for content in instructions:
            self.assertEqual(content, INSTRUCTIONS)
            for forbidden in ("RDC", "bootstrap", "transport", "one-shot", "capability filtering"):
                self.assertNotIn(forbidden, content)
            for essential in ("人工 Ctrl+C", "不自动重放", "通过对话取得人工同意",
                              "不绕过共享终端", "不授权自动中断"):
                self.assertIn(essential, content)

    def test_cli_routing_rule_is_not_in_general_instructions(self):
        self.assertNotIn("200", INSTRUCTIONS)
        self.assertNotIn("--stdio", INSTRUCTIONS)
        self.assertIn("200 个 Unicode 字符", discovery(DEFAULT_BRIDGE_SOCKET)["cli_execution"])
