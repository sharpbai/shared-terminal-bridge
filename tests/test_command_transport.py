"""Codex MCP preserves payloads and Core admits logical submits once."""

import json
from pathlib import Path
import tempfile
import threading
import unittest

from bridge.common import BridgeError
from bridge.runtime.command_requests import submit_once
from tests.context_support import bridge_fixture
from tests.mcp_support import FakeBridgeV6, MinimalMCPServer, modern_params


COMMANDS = [
    "awk '{n[$1]++;s[$1]+=$2}'",
    '''printf '%s' "double ' single"''',
    r"printf '%s' 'C:\Users\name\file'",
    r"printf '%s' '\n\u0003'",
    "printf '%s' '中文 😀 $(not-executed) `not-executed`'",
    r"grep -E 'a\.[0-9]+$' file",
]


def submit(bridge, text, request_id="logical-1"):
    return bridge.dispatch("terminal_submit", dict(
        pane="%0", generation=1, text=text, request_id=request_id,
        expected_duration_ms=1000, resource_class="normal"))


class CommandTransportTest(unittest.TestCase):
    def test_codex_mcp_json_and_core_preserve_exact_commands(self):
        for text in COMMANDS:
            with self.subTest(text=text):
                core = bridge_fixture()
                class Client(FakeBridgeV6):
                    def call(self, method, params):
                        if method == "bridge_info":
                            return super().call(method, params)
                        return {"ok": True, "result": core.dispatch(method, params)}
                server = MinimalMCPServer(Client(), enable_actions=True)
                message = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": modern_params(name="terminal_run", arguments=dict(
                               pane="%0", text=text, request_id="logical-1", wait_ms=1,
                               expected_duration_ms=1000, resource_class="normal"))}
                result = server.handle(json.loads(json.dumps(message)))
                self.assertFalse(result["result"]["isError"], result)
                self.assertEqual(core.tmux.typed, [("%0", text)])
                repeated = server.handle(message)
                self.assertEqual(result["result"]["structuredContent"]["result"]["job_id"],
                                 repeated["result"]["structuredContent"]["result"]["job_id"])
                self.assertEqual(len(core.tmux.keys), 1)

    def test_duplicate_after_human_override_does_not_renew_or_execute(self):
        core = bridge_fixture()
        core.event_sequence = 0
        original = submit(core, "sleep 60")
        core.handle_human_event(dict(type="human_interrupt", pane="%0", pre_interrupt_content="busy"))
        self.assertEqual(submit(core, "sleep 60"), original)
        self.assertEqual(core.leases["%0"]["state"], "REVOKED")
        self.assertEqual(len(core.tmux.typed), 1)
        core.generations = {"%0": 1}
        self.assertEqual(submit(core, "sleep 60", "new-call")["generation"], 2)

    def test_conflicting_id_and_reserved_restart_fail_closed(self):
        core = bridge_fixture()
        submit(core, "echo first")
        with self.assertRaises(BridgeError) as raised:
            submit(core, "echo second")
        self.assertEqual(raised.exception.code, "COMMAND_REQUEST_CONFLICT")
        entries = json.loads(json.dumps(core.command_requests))
        restarted = bridge_fixture()
        restarted.command_requests = entries
        self.assertEqual(submit(restarted, "echo first")["job_id"],
                         submit(core, "echo first")["job_id"])
        self.assertEqual(restarted.tmux.typed, [])
        entries["logical-1"] = dict(entries["logical-1"], state="RESERVED")
        with self.assertRaises(BridgeError) as raised:
            submit(restarted, "echo first")
        self.assertEqual(raised.exception.code, "COMMAND_REQUEST_AMBIGUOUS")

    def test_actual_newline_and_control_keys_are_not_command_text(self):
        for text in ["echo one\necho two", "echo\r", "\x03", "\x00"]:
            core = bridge_fixture()
            with self.assertRaises(BridgeError):
                submit(core, text)
            self.assertEqual(core.tmux.typed, [])


    def test_durable_state_survives_real_persist_and_load(self):
        with tempfile.TemporaryDirectory() as directory:
            core = bridge_fixture()
            core.generations = {"%0": 1}
            core.tmux_server_id = "test-server"
            core.allow_session_management = False
            core.binding_snapshot_taken = False
            core.human_binding_installed = False
            core.original_human_binding = None
            core.state_file = Path(directory) / "state.json"
            del core.persist_state
            original = submit(core, "echo persisted")
            self.assertEqual(core.state_file.stat().st_mode & 0o777, 0o600)
            core.command_requests = {}
            core.load_state()
            self.assertEqual(submit(core, "echo persisted"), original)
            self.assertEqual(len(core.tmux.typed), 1)

    def test_pane_prompt_survives_task_cleanup_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            core = bridge_fixture()
            core.generations = {'%0': 1}
            core.tmux_server_id = 'test-server'
            core.allow_session_management = False
            core.binding_snapshot_taken = False
            core.human_binding_installed = False
            core.original_human_binding = None
            core.state_file = Path(directory) / 'state.json'
            core.command_requests = {}
            core.pane_prompts = {'%0': dict(prompt='root@host:/work#', pane_command='ssh')}
            del core.persist_state
            core.jobs.clear()
            core.persist_state()
            core.pane_prompts = {}
            core.load_state()
            self.assertEqual(core.jobs, {})
            self.assertEqual(core.pane_prompts['%0']['prompt'], 'root@host:/work#')

    def test_concurrent_duplicate_cannot_execute(self):
        core = bridge_fixture()
        entered, release = threading.Event(), threading.Event()
        params = dict(request_id="concurrent", pane="%0", text="echo x")
        def execute():
            entered.set()
            release.wait(2)
            return {"job_id": "one"}
        worker = threading.Thread(target=lambda: submit_once(core, params, execute))
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            with self.assertRaises(BridgeError) as raised:
                submit_once(core, params, lambda: self.fail("duplicate executed"))
            self.assertEqual(raised.exception.code, "COMMAND_REQUEST_AMBIGUOUS")
        finally:
            release.set()
            worker.join(2)

    def test_known_rejection_is_replayed_not_readmitted(self):
        core = bridge_fixture()
        for _ in range(2):
            with self.assertRaises(BridgeError) as raised:
                submit(core, "first\nsecond")
            self.assertEqual(raised.exception.code, "COMMAND_INCOMPLETE")
        self.assertEqual(core.command_requests["logical-1"]["state"], "REJECTED")


if __name__ == "__main__":
    unittest.main()
