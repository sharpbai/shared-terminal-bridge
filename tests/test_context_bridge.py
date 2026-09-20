#!/usr/bin/env python3
"""Bridge-level tests for cursor observations and terminal task blocks."""

import pathlib
import sys
import threading
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from bridge.local_bridge import BridgeError, LocalBridge, unix_ms  # noqa: E402


class FakeTmux:
    socket_name = "test"

    def __init__(self):
        self.content = "prompt$ "
        self.typed = []
        self.keys = []

    def read(self, pane, lines):
        return self.content

    def send_text(self, pane, text):
        self.typed.append((pane, text))

    def send_key(self, pane, key):
        self.keys.append((pane, key))


def bridge_fixture():
    bridge = LocalBridge.__new__(LocalBridge)
    bridge.tmux = FakeTmux()
    bridge.allowed_panes = {"%0"}
    bridge.leases = {"%0": {"pane": "%0", "generation": 1, "state": "ACTIVE"}}
    bridge.observation_cursors = {}
    bridge.task_blocks = {}
    bridge.long_run_requests = {}
    bridge.long_run_approvals = {}
    bridge.jobs = {}
    bridge.wait_handles = {}
    bridge.cancelled_wait_ids = set()
    bridge.interrupt_sources = {}
    bridge.audit = []
    bridge.lock = threading.RLock()
    bridge.persist_state = lambda: None
    bridge._notify_job = lambda job: None
    return bridge


class ContextBridgeTest(unittest.TestCase):
    def test_cursor_returns_only_new_output_and_is_opaque(self):
        bridge = bridge_fixture()
        first = bridge.terminal_read_delta("%0")
        bridge.tmux.content += "\ncommand output\n"
        second = bridge.terminal_read_delta("%0", cursor=first["cursor"])
        self.assertEqual(second["content"], "command output")
        self.assertNotEqual(first["cursor"], second["cursor"])
        self.assertEqual(bridge.audit[-1]["action"], "READ_DELTA")

    def test_task_block_is_local_metadata_and_writes_nothing(self):
        bridge = bridge_fixture()
        submitted = bridge.terminal_task_block(
            "%0", 1, ["printf 'alpha\\n'", "printf 'beta\\n'"]
        )
        block_id = submitted["block_id"]
        self.assertEqual(bridge.tmux.typed, [])
        self.assertEqual(bridge.tmux.keys, [])
        self.assertEqual(submitted["transport"], "none")
        self.assertFalse(submitted["writes_to_pane"])
        self.assertTrue(submitted["explicit_submits_required"])
        self.assertEqual(bridge.task_blocks[block_id]["commands"], 2)
        bridge.tmux.content += "\nalpha\nbeta\n"
        observed = bridge.terminal_task_observe(block_id)
        self.assertEqual(observed["state"], "ACTIVE")
        self.assertIsNone(observed["exit_code"])
        self.assertEqual(observed["content"], "alpha\nbeta")

    def test_human_override_dominates_a_late_completion_marker(self):
        bridge = bridge_fixture()
        submitted = bridge.terminal_task_block("%0", 1, ["sleep 10"])
        block_id = submitted["block_id"]
        bridge.leases["%0"].update({"state": "REVOKED", "event_seq": 3})
        bridge.tmux.content += "\npartial output\n"
        observed = bridge.terminal_task_observe(block_id)
        self.assertEqual(observed["state"], "INTERRUPTED")
        self.assertTrue(observed["execution"]["human_override"])

    def test_wait_delta_stops_after_two_quiet_windows(self):
        bridge = bridge_fixture()
        cursor = bridge.terminal_read_delta("%0")["cursor"]
        first = bridge.terminal_wait_delta("%0", cursor, wait_ms=1)
        self.assertEqual(first["state"], "QUIET")
        second = bridge.terminal_wait_delta("%0", first["cursor"], wait_ms=1)
        self.assertEqual(second["state"], "BUDGET_EXHAUSTED")
        self.assertEqual(second["budget"]["consecutive_quiet"], 2)

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

    def test_interrupt_source_is_structured(self):
        bridge = bridge_fixture()
        interrupted = bridge.terminal_interrupt("%0", 1)
        self.assertEqual(interrupted["source"], "agent")
        observed = bridge.terminal_read_delta("%0")
        self.assertEqual(observed["execution"]["interrupt_source"], "agent")

    def test_submit_creates_job_and_prompt_return_completes_it(self):
        bridge = bridge_fixture()
        submitted = bridge.terminal_submit("%0", 1, "sleep 1", 60_000, "normal")
        job_id = submitted["job_id"]
        self.assertEqual(bridge.jobs[job_id]["state"], "RUNNING")
        bridge.tmux.content = "prompt$ sleep 1\nfinished\nprompt$ "
        bridge._refresh_job(job_id)
        bridge.jobs[job_id]["last_change_ms"] = unix_ms() - 2_000
        completed = bridge.terminal_job_status(job_id)
        self.assertEqual(completed["state"], "COMPLETED")
        self.assertEqual(completed["completion_confidence"], "prompt_returned")

    def test_job_wait_returns_checkpoint_without_interrupting(self):
        bridge = bridge_fixture()
        submitted = bridge.terminal_submit("%0", 1, "sleep 30", 60_000, "normal")
        result = bridge.terminal_wait_job(submitted["job_id"], wait_ms=1)
        self.assertEqual(result["state"], "WAIT_TIMEOUT")
        self.assertEqual(bridge.tmux.keys, [("%0", "Enter")])

    def test_ten_minute_boundary_requires_strategy_review_without_fake_progress(self):
        bridge = bridge_fixture()
        submitted = bridge.terminal_submit("%0", 1, "du / | sort -h", 120_000, "normal")
        job = bridge.jobs[submitted["job_id"]]
        job["strategy_review_at_ms"] = unix_ms() - 1
        bridge.tmux.content = "Filesystem 88% used\n"
        result = bridge.terminal_wait_job(submitted["job_id"], wait_ms=1)
        self.assertEqual(result["state"], "STRATEGY_REVIEW_REQUIRED")
        self.assertIsNone(result["progress"])
        self.assertEqual(bridge.jobs[submitted["job_id"]]["state"], "RUNNING")

    def test_hard_deadline_requires_human_decision_without_interrupt(self):
        bridge = bridge_fixture()
        submitted = bridge.terminal_submit("%0", 1, "du /", 60_000, "normal")
        bridge.jobs[submitted["job_id"]]["hard_deadline_ms"] = unix_ms() - 1
        result = bridge.terminal_job_status(submitted["job_id"])
        self.assertEqual(result["state"], "HUMAN_DECISION_REQUIRED")

    def test_hard_deadline_survives_unavailable_pane(self):
        bridge = bridge_fixture()
        submitted = bridge.terminal_submit("%0", 1, "du /", 60_000, "normal")
        job = bridge.jobs[submitted["job_id"]]
        job["hard_deadline_ms"] = unix_ms() - 1
        def unavailable(_pane, _lines):
            raise BridgeError("PANE_NOT_FOUND", pane="%0")
        bridge.tmux.read = unavailable

        result = bridge.terminal_job_status(submitted["job_id"])

        self.assertEqual(result["state"], "HUMAN_DECISION_REQUIRED")
        self.assertEqual(
            result["attention_reason"], "pane_unavailable_at_hard_deadline"
        )
        self.assertEqual(bridge.tmux.keys, [("%0", "Enter")])

    def test_wait_cancellation_is_event_driven_and_does_not_interrupt_job(self):
        bridge = bridge_fixture()
        submitted = bridge.terminal_submit("%0", 1, "sleep 30", 60_000, "normal")
        result = {}

        def wait_for_job():
            result.update(
                bridge.terminal_wait_job(
                    submitted["job_id"], wait_ms=10_000, wait_id="wait-test"
                )
            )

        thread = threading.Thread(target=wait_for_job)
        thread.start()
        for _ in range(100):
            if bridge.terminal_wait_list()["waits"]:
                break
            threading.Event().wait(0.01)
        cancelled = bridge.terminal_cancel_wait("wait-test")
        thread.join(timeout=1)
        self.assertTrue(cancelled["cancelled"])
        self.assertFalse(thread.is_alive())
        self.assertEqual(result["state"], "WAIT_CANCELLED")
        self.assertEqual(bridge.jobs[submitted["job_id"]]["state"], "RUNNING")
        self.assertEqual(bridge.tmux.keys, [("%0", "Enter")])

    def test_job_detects_interactive_prompt_and_human_interrupt(self):
        bridge = bridge_fixture()
        submitted = bridge.terminal_submit("%0", 1, "sudo du /", 60_000, "normal")
        bridge.tmux.content = "prompt$ sudo du /\n[sudo] password for user:"
        attention = bridge.terminal_job_status(submitted["job_id"])
        self.assertEqual(attention["state"], "NEEDS_ATTENTION")

        bridge = bridge_fixture()
        submitted = bridge.terminal_submit("%0", 1, "sleep 30", 60_000, "normal")
        bridge.leases["%0"].update({"state": "REVOKED", "event_seq": 7})
        interrupted = bridge.terminal_job_status(submitted["job_id"])
        self.assertEqual(interrupted["state"], "INTERRUPTED_BY_HUMAN")


if __name__ == "__main__":
    unittest.main()
