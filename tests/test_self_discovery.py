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
        for essential in ["确认目标会话", "通过 run", "job ID", "interrupt",
                          "高风险", "人工 Ctrl+C", "不重复提交", "CLI", "TUI"]:
            self.assertIn(essential, modern)
        tools = {t["name"]: t for t in server.list_tools(True)["tools"]}
        self.assertTrue({"terminal_run", "terminal_interrupt_job"} <= set(tools))
        self.assertNotIn("terminal_session_acquire", tools)
        self.assertNotIn("terminal_input_job", tools)
        self.assertIn("不使用 TUI", modern)
        for tool in tools.values():
            self.assertNotIn("generation", tool["inputSchema"]["properties"])
