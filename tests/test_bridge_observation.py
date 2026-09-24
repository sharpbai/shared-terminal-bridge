#!/usr/bin/env python3
"""Focused tests for bridge observation."""

from tests.context_support import *  # noqa: F401,F403

class ContextBridgeTest(unittest.TestCase):
    def test_cursor_returns_only_new_output_and_is_opaque(self):
        bridge = bridge_fixture()
        first = bridge.terminal_read_delta("%0")
        bridge.tmux.content += "\ncommand output\n"
        second = bridge.terminal_read_delta("%0", cursor=first["cursor"])
        self.assertEqual(second["content"], "command output")
        self.assertNotEqual(first["cursor"], second["cursor"])
        self.assertEqual(bridge.audit[-1]["action"], "READ_DELTA")

    def test_wait_delta_stops_after_two_quiet_windows(self):
        bridge = bridge_fixture()
        cursor = bridge.terminal_read_delta("%0")["cursor"]
        first = bridge.terminal_wait_delta("%0", cursor, wait_ms=1)
        self.assertEqual(first["state"], "QUIET")
        second = bridge.terminal_wait_delta("%0", first["cursor"], wait_ms=1)
        self.assertEqual(second["state"], "BUDGET_EXHAUSTED")
        self.assertEqual(second["budget"]["consecutive_quiet"], 2)

    def test_interrupt_source_is_structured(self):
        bridge = bridge_fixture()
        interrupted = bridge.terminal_interrupt("%0", 1)
        self.assertEqual(interrupted["source"], "agent")
        observed = bridge.terminal_read_delta("%0")
        self.assertEqual(observed["execution"]["interrupt_source"], "agent")


if __name__ == "__main__":
    unittest.main()
