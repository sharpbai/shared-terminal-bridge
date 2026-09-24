#!/usr/bin/env python3
"""Focused tests for bridge audit human."""

from tests.context_support import *  # noqa: F401,F403

class ContextBridgeTest(unittest.TestCase):
    def test_human_override_dominates_a_late_completion_marker(self):
        bridge = bridge_fixture()
        submitted = bridge.terminal_task_block("%0", 1, ["sleep 10"])
        block_id = submitted["block_id"]
        bridge.leases["%0"].update({"state": "REVOKED", "event_seq": 3})
        bridge.tmux.content += "\npartial output\n"
        observed = bridge.terminal_task_observe(block_id)
        self.assertEqual(observed["state"], "INTERRUPTED")
        self.assertTrue(observed["execution"]["human_override"])

    def test_persistent_history_filters_and_redacts_sensitive_commands(self):
        bridge = bridge_fixture()
        bridge.managed_sessions = {
            "managed": {"name": "verify", "pane": "%0"}
        }
        with tempfile.TemporaryDirectory() as directory:
            bridge.history_file = pathlib.Path(directory) / "history.jsonl"
            bridge.record("SUBMIT", pane="%0", command="printf ok")
            bridge.record(
                "SUBMIT", pane="%0",
                command=bridge._history_command("export API_TOKEN=secret"),
            )
            result = bridge.terminal_history(session="verify", limit=10)

            self.assertEqual(len(result["entries"]), 2)
            self.assertEqual(result["entries"][1]["command"], "[REDACTED_SENSITIVE_COMMAND]")
            self.assertEqual(bridge.history_file.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
