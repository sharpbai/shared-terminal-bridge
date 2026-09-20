#!/usr/bin/env python3
"""Protocol and safety tests for the minimal MCP adapter."""

import io
import datetime
import json
import pathlib
import sys
import tempfile
import threading
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from mcp_server.server import (  # noqa: E402
    CLIENT_CAPABILITIES_META,
    CodexTurnResolver,
    MODERN_VERSION,
    PROTOCOL_VERSION_META,
    MinimalMCPServer,
)


class FakeBridge:
    def __init__(self, response=None):
        self.response = response or {"ok": True, "result": {"panes": []}}
        self.calls = []

    def call(self, method, params):
        if method == "bridge_info":
            return {
                "ok": True,
                "result": {"api_version": 2, "version": "test"},
            }
        self.calls.append((method, params))
        return self.response


class FakeBridgeV3(FakeBridge):
    def call(self, method, params):
        if method == "bridge_info":
            return {"ok": True, "result": {"api_version": 3, "version": "test"}}
        self.calls.append((method, params))
        return self.response


class FakeBridgeV4(FakeBridgeV3):
    def call(self, method, params):
        if method == "bridge_info":
            return {"ok": True, "result": {"api_version": 4, "version": "test"}}
        self.calls.append((method, params))
        return self.response


class FakeBridgeV5(FakeBridgeV4):
    def call(self, method, params):
        if method == "bridge_info":
            return {"ok": True, "result": {"api_version": 5, "version": "test"}}
        self.calls.append((method, params))
        return self.response


class FakeBridgeV6(FakeBridgeV5):
    def call(self, method, params):
        if method == "bridge_info":
            return {"ok": True, "result": {"api_version": 6, "version": "test"}}
        self.calls.append((method, params))
        return self.response


class FakeTurnResolver:
    def __init__(self, turn=1):
        self.turn = turn

    def current(self):
        return {
            "thread_id": "thread-1",
            "turn_id": f"turn-{self.turn}",
            "turn_started_at_ms": 1_000 * self.turn,
        }


def modern_params(**values):
    return {
        **values,
        "_meta": {
            PROTOCOL_VERSION_META: MODERN_VERSION,
            CLIENT_CAPABILITIES_META: {},
        },
    }


class MinimalMCPServerTest(unittest.TestCase):
    def test_turn_resolver_uses_latest_verified_user_message(self):
        with tempfile.TemporaryDirectory() as directory:
            session_dir = pathlib.Path(directory) / "sessions" / "2026" / "09" / "20"
            session_dir.mkdir(parents=True)
            path = session_dir / "rollout-thread-1.jsonl"
            records = [
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "item_completed",
                        "thread_id": "thread-1",
                        "turn_id": "turn-1",
                        "item": {"type": "UserMessage"},
                        "started_at_ms": 1000,
                    },
                },
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "item_completed",
                        "thread_id": "other-thread",
                        "turn_id": "untrusted-turn",
                        "item": {"type": "UserMessage"},
                        "started_at_ms": 9999,
                    },
                },
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "item_completed",
                        "thread_id": "thread-1",
                        "turn_id": "turn-2",
                        "item": {"type": "UserMessage"},
                        "started_at_ms": 2000,
                    },
                },
            ]
            path.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            resolved = CodexTurnResolver(
                thread_id="thread-1",
                codex_root=directory,
            ).current()
            self.assertEqual(
                resolved,
                {
                    "thread_id": "thread-1",
                    "turn_id": "turn-2",
                    "turn_started_at_ms": 2000,
                },
            )

    def test_turn_resolver_binds_process_to_nearest_session_meta(self):
        with tempfile.TemporaryDirectory() as directory:
            session_dir = pathlib.Path(directory) / "sessions" / "2026" / "09" / "20"
            session_dir.mkdir(parents=True)
            candidates = [
                ("thread-old", "2026-09-20T08:31:20.000Z", 1000),
                ("thread-near", "2026-09-20T08:31:59.900Z", 2000),
            ]
            for thread_id, timestamp, user_ms in candidates:
                records = [
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": thread_id,
                            "timestamp": timestamp,
                        },
                    },
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "item_completed",
                            "thread_id": thread_id,
                            "turn_id": f"turn-{thread_id}",
                            "item": {"type": "UserMessage"},
                            "started_at_ms": user_ms,
                        },
                    },
                ]
                (session_dir / f"rollout-{thread_id}.jsonl").write_text(
                    "".join(json.dumps(record) + "\n" for record in records),
                    encoding="utf-8",
                )
            process_ms = int(
                datetime.datetime.fromisoformat(
                    "2026-09-20T08:32:00+00:00"
                ).timestamp()
                * 1000
            )
            resolver = CodexTurnResolver(
                codex_root=directory,
                process_started_at_ms=process_ms,
            )
            self.assertEqual(resolver.infer_thread_id(), "thread-near")
            self.assertEqual(resolver.current()["turn_id"], "turn-thread-near")

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

    def test_v5_hides_v6_cancellable_wait_but_keeps_job_status(self):
        server = MinimalMCPServer(FakeBridgeV5(), enable_actions=True)
        names = [tool["name"] for tool in server.list_tools(True)["tools"]]
        self.assertIn("terminal_job_list", names)
        self.assertIn("terminal_job_status", names)
        self.assertNotIn("terminal_wait_job", names)

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
