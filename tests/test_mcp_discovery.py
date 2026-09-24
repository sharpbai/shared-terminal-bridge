#!/usr/bin/env python3
"""Focused tests for mcp discovery."""

from tests.mcp_support import *  # noqa: F401,F403

class MinimalMCPServerTest(unittest.TestCase):
    def test_modern_discovery_and_read_only_tools(self):
        server = MinimalMCPServer(FakeBridge())
        discovery = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "server/discover",
                "params": modern_params(),
            }
        )
        self.assertIn(MODERN_VERSION, discovery["result"]["supportedVersions"])
        listed = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": modern_params(),
            }
        )
        names = [tool["name"] for tool in listed["result"]["tools"]]
        self.assertEqual(
            names,
            [
                "terminal_list",
                "get_active_pane",
                "terminal_read",
                "terminal_read_delta",
                "terminal_state",
            ],
        )
        self.assertEqual(listed["result"]["resultType"], "complete")

    def test_legacy_initialize_and_tool_call(self):
        bridge = FakeBridge()
        server = MinimalMCPServer(bridge)
        initialized = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            }
        )
        self.assertEqual(
            initialized["result"]["protocolVersion"], "2025-11-25"
        )
        called = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "terminal_list", "arguments": {}},
            }
        )
        self.assertFalse(called["result"]["isError"])
        self.assertEqual(bridge.calls, [("terminal_list", {})])

    def test_actions_are_absent_by_default(self):
        server = MinimalMCPServer(FakeBridge())
        response = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": modern_params(
                    name="terminal_type",
                    arguments={"pane": "%0", "generation": 1, "text": "id"},
                ),
            }
        )
        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("disabled", response["error"]["message"])

    def test_old_daemon_hides_v2_tools_and_returns_restart_guidance(self):
        class OldBridge:
            def call(self, method, params):
                if method == "bridge_info":
                    return {
                        "ok": False,
                        "error": {"code": "METHOD_NOT_FOUND", "method": method},
                    }
                return {"ok": True, "result": {}}

        server = MinimalMCPServer(OldBridge(), enable_actions=True)
        listed = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": modern_params(),
            }
        )
        names = [tool["name"] for tool in listed["result"]["tools"]]
        self.assertNotIn("terminal_read_delta", names)
        self.assertNotIn("terminal_task_block", names)
        self.assertEqual(
            listed["result"]["bridgeCompatibility"]["status"],
            "restart_required",
        )
        called = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": modern_params(
                    name="terminal_read_delta",
                    arguments={"pane": "%0"},
                ),
            }
        )
        self.assertTrue(called["result"]["isError"])
        self.assertEqual(
            called["result"]["structuredContent"]["error"]["code"],
            "BRIDGE_RESTART_REQUIRED",
        )

    def test_session_management_is_explicit_and_has_no_lease_tool(self):
        default_server = MinimalMCPServer(FakeBridge())
        self.assertNotIn(
            "terminal_session_create",
            [tool["name"] for tool in default_server.tools],
        )
        enabled = MinimalMCPServer(
            FakeBridge(),
            enable_session_management=True,
        )
        names = [tool["name"] for tool in enabled.tools]
        self.assertIn("terminal_session_list", names)
        self.assertIn("terminal_session_create", names)
        self.assertIn("terminal_session_stop", names)
        self.assertNotIn("acquire_execution", names)

    def test_v3_publishes_wait_named_observation_and_long_approval(self):
        server = MinimalMCPServer(
            FakeBridgeV3(),
            enable_actions=True,
            enable_session_management=True,
        )
        names = [tool["name"] for tool in server.list_tools(True)["tools"]]
        self.assertIn("terminal_wait_delta", names)
        self.assertIn("terminal_long_run_approve", names)
        self.assertIn("terminal_session_read_delta", names)
        self.assertIn("terminal_session_wait_delta", names)
        self.assertIn("terminal_session_state", names)
        self.assertNotIn("terminal_long_run_request", names)

    def test_v4_long_run_request_is_structured_input_required(self):
        bridge = FakeBridgeV4(
            {
                "ok": True,
                "result": {
                    "interaction": "input_required",
                    "request_id": "lr_123",
                    "command": "du -xhd1 /large",
                },
            }
        )
        server = MinimalMCPServer(bridge, enable_actions=True)
        names = [tool["name"] for tool in server.list_tools(True)["tools"]]
        self.assertIn("terminal_long_run_request", names)
        response = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": modern_params(
                    name="terminal_long_run_request",
                    arguments={
                        "pane": "%7",
                        "generation": 42,
                        "text": "du -xhd1 /large",
                        "expected_duration_ms": 180_000,
                        "resource_class": "full_scan",
                        "idle_budget_ms": 30_000,
                        "total_budget_ms": 180_000,
                    },
                ),
            }
        )
        self.assertFalse(response["result"]["isError"])
        self.assertEqual(response["result"]["resultType"], "inputRequired")

    def test_v5_publishes_local_job_wait_tools(self):
        server = MinimalMCPServer(FakeBridgeV6(), enable_actions=True)
        names = [tool["name"] for tool in server.list_tools(True)["tools"]]
        self.assertIn("terminal_job_list", names)
        self.assertIn("terminal_job_status", names)
        self.assertIn("terminal_wait_job", names)
        wait_tool = next(
            tool for tool in server.list_tools(True)["tools"]
            if tool["name"] == "terminal_wait_job"
        )
        self.assertEqual(
            wait_tool["inputSchema"]["properties"]["wait_ms"]["maximum"],
            600_000,
        )
        status_tool = next(
            tool for tool in server.list_tools(True)["tools"]
            if tool["name"] == "terminal_job_status"
        )
        self.assertFalse(
            status_tool["inputSchema"]["properties"]["include_output"]["default"]
        )

    def test_v7_publishes_history_and_derives_long_run_budgets(self):
        server = MinimalMCPServer(FakeBridgeV7(), enable_actions=True)
        tools = server.list_tools(True)["tools"]
        names = [tool["name"] for tool in tools]
        self.assertIn("terminal_history", names)
        request_tool = next(
            tool for tool in tools if tool["name"] == "terminal_long_run_request"
        )
        required = request_tool["inputSchema"]["required"]
        self.assertNotIn("idle_budget_ms", required)
        self.assertNotIn("total_budget_ms", required)

    def test_v8_publishes_read_only_task_block_runner(self):
        server = MinimalMCPServer(FakeBridgeV8(), enable_actions=True)
        tools = server.list_tools(True)["tools"]
        names = [tool["name"] for tool in tools]
        self.assertIn("terminal_task_block_execute", names)
        runner = next(
            tool for tool in tools if tool["name"] == "terminal_task_block_execute"
        )
        self.assertEqual(runner["inputSchema"]["properties"]["steps"]["maxItems"], 8)

        old_server = MinimalMCPServer(FakeBridgeV7(), enable_actions=True)
        old_names = [tool["name"] for tool in old_server.list_tools(True)["tools"]]
        self.assertNotIn("terminal_task_block_execute", old_names)

    def test_v9_publishes_program_profiles_and_v8_hides_them(self):
        bridge = FakeBridgeV9()
        server = MinimalMCPServer(bridge, enable_actions=True)
        names = [tool["name"] for tool in server.list_tools(True)["tools"]]
        self.assertIn("terminal_program_profile", names)

        result = server.call_tool(
            {"name": "terminal_program_profile", "arguments": {"program": "testdisk"}},
            modern=True,
            request_id=99,
        )
        self.assertFalse(result["isError"])
        self.assertIn(("terminal_program_profile", {"program": "testdisk"}), bridge.calls)

        old_server = MinimalMCPServer(FakeBridgeV8(), enable_actions=True)
        old_names = [tool["name"] for tool in old_server.list_tools(True)["tools"]]
        self.assertNotIn("terminal_program_profile", old_names)

    def test_v5_hides_v6_cancellable_wait_but_keeps_job_status(self):
        server = MinimalMCPServer(FakeBridgeV5(), enable_actions=True)
        names = [tool["name"] for tool in server.list_tools(True)["tools"]]
        self.assertIn("terminal_job_list", names)
        self.assertIn("terminal_job_status", names)
        self.assertNotIn("terminal_wait_job", names)


if __name__ == "__main__":
    unittest.main()
