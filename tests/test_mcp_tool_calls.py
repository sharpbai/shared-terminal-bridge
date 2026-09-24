#!/usr/bin/env python3
"""Focused tests for mcp tool calls."""

from tests.mcp_support import *  # noqa: F401,F403

class MinimalMCPServerTest(unittest.TestCase):
    def test_cancel_notification_wakes_wait_without_terminal_interrupt(self):
        class BlockingBridge(FakeBridgeV6):
            def __init__(self):
                super().__init__()
                self.waiting = threading.Event()
                self.cancelled = threading.Event()
                self.wait_id = None

            def call(self, method, params):
                if method == "bridge_info":
                    return {"ok": True, "result": {"api_version": 6, "version": "test"}}
                self.calls.append((method, params))
                if method == "terminal_wait_job":
                    self.wait_id = params["wait_id"]
                    self.waiting.set()
                    self.cancelled.wait(1)
                    return {"ok": True, "result": {"state": "WAIT_CANCELLED"}}
                if method == "terminal_cancel_wait":
                    self.cancelled.set()
                    return {"ok": True, "result": {"cancelled": True}}
                raise AssertionError(method)

        bridge = BlockingBridge()
        server = MinimalMCPServer(bridge, enable_actions=True)
        response = {}

        def call_wait():
            response.update(
                server.handle(
                    {
                        "jsonrpc": "2.0",
                        "id": 77,
                        "method": "tools/call",
                        "params": modern_params(
                            name="terminal_wait_job",
                            arguments={"job_id": "job_1", "wait_ms": 600_000},
                        ),
                    }
                )
            )

        worker = threading.Thread(target=call_wait)
        worker.start()
        self.assertTrue(bridge.waiting.wait(1))
        server.handle(
            {
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"requestId": 77},
            }
        )
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(response["result"]["structuredContent"]["result"]["state"], "WAIT_CANCELLED")
        self.assertFalse(any(method == "terminal_interrupt" for method, _ in bridge.calls))

    def test_v3_acquire_resolves_exact_name_without_listing(self):
        class ResolveBridge(FakeBridgeV3):
            def call(self, method, params):
                if method == "bridge_info":
                    return {"ok": True, "result": {"api_version": 3, "version": "test"}}
                self.calls.append((method, params))
                if method == "terminal_session_resolve":
                    return {"ok": True, "result": {"name": "verify33", "pane": "%5"}}
                if method == "acquire_execution":
                    return {"ok": True, "result": {"pane": "%5", "generation": 9, "state": "ACTIVE"}}
                raise AssertionError(method)

        bridge = ResolveBridge()
        server = MinimalMCPServer(
            bridge,
            enable_actions=True,
            enable_session_management=True,
            turn_resolver=FakeTurnResolver(),
        )
        response = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": modern_params(
                    name="terminal_session_acquire",
                    arguments={"name": "verify33"},
                ),
            }
        )
        self.assertFalse(response["result"]["isError"])
        self.assertEqual(bridge.calls[0], ("terminal_session_resolve", {"name": "verify33"}))
        self.assertNotIn(("terminal_session_list", {}), bridge.calls)

    def test_enabled_action_forwards_generation_but_not_lease_acquisition(self):
        bridge = FakeBridge({"ok": True, "result": {"accepted": True}})
        turns = FakeTurnResolver()
        server = MinimalMCPServer(
            bridge,
            enable_actions=True,
            turn_resolver=turns,
        )
        names = [tool["name"] for tool in server.tools]
        self.assertIn("terminal_submit", names)
        self.assertIn("terminal_session_acquire", names)
        self.assertIn("terminal_type", names)
        self.assertIn("terminal_task_block", names)
        self.assertIn("terminal_task_observe", names)
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

    def test_submit_forwards_a_complete_command_in_one_call(self):
        bridge = FakeBridge({"ok": True, "result": {"accepted": True}})
        server = MinimalMCPServer(bridge, enable_actions=True)
        response = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": modern_params(
                    name="terminal_submit",
                    arguments={
                        "pane": "%7",
                        "generation": 42,
                        "text": "df -h; printf '\\nINODES\\n'; df -i",
                        "expected_duration_ms": 30_000,
                        "resource_class": "normal",
                    },
                ),
            }
        )
        self.assertFalse(response["result"]["isError"])
        self.assertEqual(
            bridge.calls,
            [
                (
                    "terminal_submit",
                    {
                        "pane": "%7",
                        "generation": 42,
                        "text": "df -h; printf '\\nINODES\\n'; df -i",
                        "expected_duration_ms": 30_000,
                        "resource_class": "normal",
                    },
                )
            ],
        )

    def test_same_turn_is_denied_but_later_turn_can_supersede(self):
        class LeaseBridge:
            def __init__(self):
                self.calls = []
                self.state = "ACTIVE"
                self.generation = 8
                self.authorization = None

            def call(self, method, params):
                if method == "bridge_info":
                    return {
                        "ok": True,
                        "result": {"api_version": 2, "version": "test"},
                    }
                self.calls.append((method, params))
                if method == "terminal_session_list":
                    return {
                        "ok": True,
                        "result": {
                            "sessions": [{"name": "verify33", "pane": "%5"}]
                        },
                    }
                if method == "execution_status":
                    return {
                        "ok": True,
                        "result": {
                            "lease": {
                                "pane": "%5",
                                "generation": self.generation,
                                "state": self.state,
                                "authorization": self.authorization,
                            }
                        },
                    }
                self.generation += 1
                self.state = "ACTIVE"
                self.authorization = {
                    key: params[key]
                    for key in ("thread_id", "turn_id", "turn_started_at_ms")
                }
                return {
                    "ok": True,
                    "result": {
                        "pane": "%5",
                        "generation": self.generation,
                        "state": "ACTIVE",
                        "authorization": self.authorization,
                    },
                }

        bridge = LeaseBridge()
        turns = FakeTurnResolver()
        server = MinimalMCPServer(
            bridge,
            enable_actions=True,
            turn_resolver=turns,
        )
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": modern_params(
                name="terminal_session_acquire",
                arguments={"name": "verify33"},
            ),
        }
        first = server.handle(request)
        self.assertFalse(first["result"]["isError"])
        self.assertEqual(
            first["result"]["structuredContent"]["result"]["session"],
            "verify33",
        )
        second = server.handle({**request, "id": 2})
        self.assertTrue(second["result"]["isError"])
        self.assertEqual(
            second["result"]["structuredContent"]["error"]["code"],
            "EXECUTION_LEASE_ALREADY_ACTIVE",
        )
        turns.turn = 2
        third = server.handle({**request, "id": 3})
        self.assertFalse(third["result"]["isError"])
        self.assertEqual(
            third["result"]["structuredContent"]["result"]["generation"],
            10,
        )
        bridge.state = "REVOKED"
        turns.turn = 3
        fourth = server.handle({**request, "id": 4})
        self.assertFalse(fourth["result"]["isError"])
        self.assertEqual(
            fourth["result"]["structuredContent"]["result"]["generation"],
            11,
        )
        self.assertEqual(
            bridge.calls,
            [
                ("terminal_session_list", {}),
                (
                    "acquire_execution",
                    {
                        "pane": "%5",
                        "thread_id": "thread-1",
                        "turn_id": "turn-1",
                        "turn_started_at_ms": 1000,
                    },
                ),
                ("terminal_session_list", {}),
                ("execution_status", {"pane": "%5"}),
                ("terminal_session_list", {}),
                ("execution_status", {"pane": "%5"}),
                (
                    "acquire_execution",
                    {
                        "pane": "%5",
                        "thread_id": "thread-1",
                        "turn_id": "turn-2",
                        "turn_started_at_ms": 2000,
                    },
                ),
                ("terminal_session_list", {}),
                ("execution_status", {"pane": "%5"}),
                (
                    "acquire_execution",
                    {
                        "pane": "%5",
                        "thread_id": "thread-1",
                        "turn_id": "turn-3",
                        "turn_started_at_ms": 3000,
                    },
                ),
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
