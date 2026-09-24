#!/usr/bin/env python3
"""Focused tests for bridge long run."""

from tests.context_support import *  # noqa: F401,F403

class ContextBridgeTest(unittest.TestCase):
    def test_long_run_requires_exact_single_use_approval(self):
        bridge = bridge_fixture()
        bridge.leases["%0"]["authorization"] = {
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "turn_started_at_ms": 1000,
        }
        command = "du -xhd1 /large"
        with self.assertRaises(BridgeError) as raised:
            bridge.terminal_submit(
                "%0", 1, command,
                expected_duration_ms=180_000,
                resource_class="high_io",
            )
        self.assertEqual(raised.exception.code, "LONG_RUN_APPROVAL_REQUIRED")
        with self.assertRaises(BridgeError) as same_turn:
            bridge.terminal_long_run_approve(
                "%0", 1, command, 180_000, "high_io", 30_000, 180_000
            )
        self.assertEqual(
            same_turn.exception.code,
            "LONG_RUN_APPROVAL_NEW_USER_TURN_REQUIRED",
        )
        bridge.leases["%0"].update(
            {
                "generation": 2,
                "authorization": {
                    "thread_id": "thread-1",
                    "turn_id": "turn-2",
                    "turn_started_at_ms": 2000,
                },
            }
        )
        approval = bridge.terminal_long_run_approve(
            "%0", 2, command, 180_000, "high_io", 30_000, 180_000
        )
        accepted = bridge.terminal_submit(
            "%0", 2, command,
            expected_duration_ms=180_000,
            resource_class="high_io",
            long_run_approval_id=approval["approval_id"],
        )
        self.assertTrue(accepted["accepted"])
        with self.assertRaises(BridgeError):
            bridge.terminal_submit(
                "%0", 2, command,
                expected_duration_ms=180_000,
                resource_class="high_io",
                long_run_approval_id=approval["approval_id"],
            )

    def test_long_run_request_returns_input_required_and_accepts_request_id(self):
        bridge = bridge_fixture()
        bridge.leases["%0"]["authorization"] = {
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "turn_started_at_ms": 1000,
        }
        command = "du -xhd1 /large | sort -h"
        request = bridge.terminal_long_run_request(
            "%0", 1, command, 180_000, "full_scan", 30_000, 180_000
        )
        self.assertEqual(request["interaction"], "input_required")
        self.assertEqual(request["command"], command)
        self.assertTrue(request["request_id"].startswith("lr_"))
        bridge.leases["%0"].update(
            {
                "generation": 2,
                "authorization": {
                    "thread_id": "thread-1",
                    "turn_id": "turn-2",
                    "turn_started_at_ms": 2000,
                },
            }
        )
        approval = bridge.terminal_long_run_approve(
            "%0", 2, request_id=request["request_id"]
        )
        self.assertEqual(approval["request_id"], request["request_id"])
        accepted = bridge.terminal_submit(
            "%0", 2, command, 180_000, "full_scan", approval["approval_id"]
        )
        self.assertTrue(accepted["accepted"])

    def test_cli_decision_can_approve_or_reject_pending_request(self):
        bridge = bridge_fixture()
        bridge.leases["%0"]["authorization"] = {
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "turn_started_at_ms": 1000,
        }
        request = bridge.terminal_long_run_request(
            "%0", 1, "find /large -type f", 180_000, "high_io", 30_000, 180_000
        )
        decided = bridge.terminal_long_run_decide(request["request_id"], "approve")
        self.assertEqual(decided["status"], "APPROVED")
        approval = bridge.terminal_long_run_approve(
            "%0", 1, request_id=request["request_id"]
        )
        self.assertEqual(approval["request_id"], request["request_id"])

    def test_long_run_budgets_are_derived_when_omitted(self):
        bridge = bridge_fixture()
        request = bridge.terminal_long_run_request(
            "%0", 1, "du /", 300_000, "high_io"
        )
        self.assertEqual(request["idle_budget_ms"], 150_000)
        self.assertEqual(request["total_budget_ms"], 600_000)


if __name__ == "__main__":
    unittest.main()
