#!/usr/bin/env python3
"""Protocol and safety tests for the minimal MCP adapter."""

import io
import json
import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from mcp_server.server import (  # noqa: E402
    CLIENT_CAPABILITIES_META,
    MODERN_VERSION,
    PROTOCOL_VERSION_META,
    MinimalMCPServer,
)


class FakeBridge:
    def __init__(self, response=None):
        self.response = response or {"ok": True, "result": {"panes": []}}
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))
        return self.response


def modern_params(**values):
    return {
        **values,
        "_meta": {
            PROTOCOL_VERSION_META: MODERN_VERSION,
            CLIENT_CAPABILITIES_META: {},
        },
    }


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

    def test_enabled_action_forwards_generation_but_not_lease_acquisition(self):
        bridge = FakeBridge({"ok": True, "result": {"accepted": True}})
        server = MinimalMCPServer(bridge, enable_actions=True)
        names = [tool["name"] for tool in server.tools]
        self.assertIn("terminal_type", names)
        self.assertNotIn("acquire_execution", names)
        response = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": modern_params(
                    name="terminal_type",
                    arguments={
                        "pane": "%7",
                        "generation": 42,
                        "text": "printf ok",
                    },
                ),
            }
        )
        self.assertFalse(response["result"]["isError"])
        self.assertEqual(
            bridge.calls,
            [
                (
                    "terminal_type",
                    {"pane": "%7", "generation": 42, "text": "printf ok"},
                )
            ],
        )

    def test_bridge_rejection_is_a_tool_error(self):
        bridge = FakeBridge(
            {
                "ok": False,
                "error": {
                    "code": "EXECUTION_LEASE_INVALID",
                    "pane": "%0",
                    "generation": 1,
                },
            }
        )
        server = MinimalMCPServer(bridge, enable_actions=True)
        response = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": modern_params(
                    name="terminal_interrupt",
                    arguments={"pane": "%0", "generation": 1},
                ),
            }
        )
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(
            response["result"]["structuredContent"]["error"]["code"],
            "EXECUTION_LEASE_INVALID",
        )

    def test_stdio_framing(self):
        server = MinimalMCPServer(FakeBridge())
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "server/discover",
            "params": modern_params(),
        }
        output = io.StringIO()
        server.run_stdio(io.StringIO(json.dumps(request) + "\n"), output)
        response = json.loads(output.getvalue())
        self.assertEqual(response["id"], 1)
        self.assertIn(MODERN_VERSION, response["result"]["supportedVersions"])


if __name__ == "__main__":
    unittest.main()
