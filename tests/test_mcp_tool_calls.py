"""Model tasks replace public lease/generation choreography."""
from tests.mcp_support import *  # noqa: F401,F403


class ModelTaskCallsTest(unittest.TestCase):
    def test_all_published_schemas_have_no_internal_authority_fields(self):
        server = MinimalMCPServer(FakeBridgeV9(), enable_actions=True, enable_session_management=True)
        for tool in server.tools:
            self.assertTrue({"generation", "lease", "authorization", "turn_id"}.isdisjoint(
                tool["inputSchema"]["properties"]))

    def test_cancel_before_run_admission_never_submits(self):
        bridge = FakeBridgeV9()
        server = MinimalMCPServer(bridge, enable_actions=True)
        server.cancel_request(77)
        result = self.call(server, "terminal_run", dict(pane="%0", request_id="x", text="echo x"), 77)
        self.assertFalse(result["result"]["structuredContent"]["result"]["task_executed"])
        self.assertEqual(bridge.calls, [])

    def call(self, server, name, arguments, request_id=1):
        return server.handle({"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
            "params": modern_params(name=name, arguments=arguments)})

    def test_run_hides_authority_and_accepts_no_model_generation(self):
        bridge = FakeBridgeV9({"ok": True, "result": {"job_id": "one", "generation": 5,
            "lease": {"state": "ACTIVE"}, "output": "literal generation=5"}})
        server = MinimalMCPServer(bridge, enable_actions=True, turn_resolver=FakeTurnResolver())
        result = self.call(server, "terminal_run", dict(pane="%0", request_id="logical", text="df -h", resource_class="high_io"))
        self.assertFalse(result["result"]["isError"])
        data = result["result"]["structuredContent"]["result"]
        self.assertNotIn("generation", data)
        self.assertNotIn("lease", data)
        self.assertEqual(data["output"], "literal generation=5")
        self.assertEqual(bridge.calls[-1][0], "terminal_run")
        self.assertIn("_authorization", bridge.calls[-1][1])
        self.assertNotIn("generation", bridge.calls[-1][1])

    def test_removed_tools_and_injected_authority_fail_before_bridge(self):
        bridge = FakeBridgeV9()
        server = MinimalMCPServer(bridge, enable_actions=True)
        for name in ["terminal_submit", "terminal_type", "terminal_key", "terminal_interrupt",
                     "terminal_session_acquire", "terminal_task_block_execute"]:
            self.assertIn("error", self.call(server, name, {}))
        for field in ["generation", "_authorization"]:
            self.assertIn("error", self.call(server, "terminal_run", dict(
                pane="%0", request_id="x", text="echo x", **{field: 1})))
        self.assertEqual(bridge.calls, [])

    def test_job_interrupt_and_input_use_only_handles(self):
        bridge = FakeBridgeV9({"ok": True, "result": {"accepted": True}})
        server = MinimalMCPServer(bridge, enable_actions=True)
        for name, args in [("terminal_interrupt_job", {"job_id": "one"}),
                           ("terminal_input_job", {"job_id": "one", "request_id": "input-1", "text": "yes"})]:
            result = self.call(server, name, args)
            self.assertFalse(result["result"]["isError"])
            self.assertEqual(bridge.calls[-1], (name, args))

    def test_bridge_rejection_is_tool_error_without_internal_metadata(self):
        bridge = FakeBridgeV9({"ok": False, "error": {"code": "EXECUTION_LEASE_INVALID",
                                                     "generation": 1, "pane": "%0"}})
        result = self.call(MinimalMCPServer(bridge, enable_actions=True),
                           "terminal_interrupt_job", {"job_id": "one"})
        self.assertTrue(result["result"]["isError"])
        self.assertNotIn("generation", result["result"]["structuredContent"]["error"])

    def test_cancel_notification_wakes_wait_or_run_without_interrupt(self):
        for tool_name, arguments in [("terminal_wait_job", {"job_id": "one"}),
                                     ("terminal_run", {"pane": "%0", "request_id": "run", "text": "sleep 60"})]:
            class BlockingBridge(FakeBridgeV9):
                def __init__(self):
                    super().__init__()
                    self.waiting, self.cancelled = threading.Event(), threading.Event()
                def call(self, method, params):
                    if method == "bridge_info":
                        return super().call(method, params)
                    self.calls.append((method, params))
                    if method == tool_name:
                        self.waiting.set()
                        self.cancelled.wait(2)
                        return {"ok": True, "result": {"state": "WAIT_CANCELLED"}}
                    if method == "terminal_cancel_wait":
                        self.cancelled.set()
                        return {"ok": True, "result": {"cancelled": True}}
                    raise AssertionError(method)
            bridge = BlockingBridge()
            server = MinimalMCPServer(bridge, enable_actions=True)
            result = []
            worker = threading.Thread(target=lambda: result.append(self.call(server, tool_name, arguments, 77)))
            worker.start()
            self.assertTrue(bridge.waiting.wait(1))
            server.handle({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 77}})
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result[0]["result"]["structuredContent"]["result"]["state"], "WAIT_CANCELLED")
            self.assertFalse(any("interrupt" in name for name, _ in bridge.calls))
