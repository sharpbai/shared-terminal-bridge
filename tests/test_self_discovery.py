"""Both protocol entrypoints are self-contained, without a local skill."""
import unittest
from mcp_server.server import MinimalMCPServer, LEGACY_VERSION
from tests.mcp_support import FakeBridgeV9


class SelfDiscoveryTest(unittest.TestCase):
    def test_modern_and_initialize_share_runtime_contract(self):
        server = MinimalMCPServer(FakeBridgeV9(), enable_actions=True)
        modern = server.discover()["instructions"]
        legacy = server.initialize({"protocolVersion": LEGACY_VERSION})["instructions"]
        self.assertEqual(modern, legacy)
        for essential in ["no local skill", "terminal_run", "terminal_input_job",
                          "terminal_interrupt_job", "High-risk", "Human Ctrl+C",
                          "one-shot bypass", "terminal_program_profile"]:
            self.assertIn(essential, modern)
        tools = {t["name"]: t for t in server.list_tools(True)["tools"]}
        self.assertTrue({"terminal_run", "terminal_input_job", "terminal_interrupt_job"} <= set(tools))
        self.assertNotIn("terminal_session_acquire", tools)
        for tool in tools.values():
            self.assertNotIn("generation", tool["inputSchema"]["properties"])
