#!/usr/bin/env python3
"""Focused tests for bridge jobs."""

from tests.context_support import *  # noqa: F401,F403

class ContextBridgeTest(unittest.TestCase):
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
        self.assertNotIn("observation", result)
        self.assertEqual(bridge.tmux.keys, [("%0", "Enter")])

    def test_job_status_output_is_explicit_opt_in(self):
        bridge = bridge_fixture()
        submitted = bridge.terminal_submit("%0", 1, "printf ok", 60_000, "normal")
        bridge.tmux.content = "prompt$ printf ok\nok\nprompt$ "

        compact = bridge.terminal_job_status(submitted["job_id"])
        detailed = bridge.terminal_job_status(
            submitted["job_id"], include_output=True
        )

        self.assertNotIn("observation", compact)
        self.assertIn("observation", detailed)
        self.assertIn("ok", detailed["observation"]["content"])

    def test_completed_wait_returns_bounded_command_output(self):
        bridge = bridge_fixture()
        submitted = bridge.terminal_submit("%0", 1, "df -h", 60_000, "normal")
        bridge.tmux.content = "prompt$ df -h\nFilesystem  Used\n/dev/x  10G\nprompt$ "
        bridge._refresh_job(submitted["job_id"])
        bridge.jobs[submitted["job_id"]]["last_change_ms"] = unix_ms() - 2_000

        result = bridge.terminal_wait_job(submitted["job_id"], wait_ms=1)

        self.assertEqual(result["state"], "COMPLETED")
        self.assertIn("Filesystem", result["output_excerpt"]["content"])
        self.assertNotIn("observation", result)
        self.assertTrue(result["output_complete"])
        self.assertEqual(result["recommended_action"], "CONTINUE")

    def test_stale_password_prompt_before_command_does_not_trigger_attention(self):
        bridge = bridge_fixture()
        bridge.tmux.content = "old command\n[sudo] password for user:\nprompt$ "
        submitted = bridge.terminal_submit("%0", 1, "df -h", 60_000, "normal")
        bridge.tmux.content += "df -h\nFilesystem Used\n/dev/x 10G\nprompt$ "
        bridge._refresh_job(submitted["job_id"])
        bridge.jobs[submitted["job_id"]]["last_change_ms"] = unix_ms() - 2_000

        result = bridge.terminal_job_status(submitted["job_id"])

        self.assertEqual(result["state"], "COMPLETED")
        self.assertIsNone(result["attention_reason"])

    def test_submit_rejects_definitely_incomplete_quotes_without_writing(self):
        bridge = bridge_fixture()

        with self.assertRaises(BridgeError) as raised:
            bridge.terminal_submit("%0", 1, "printf 'unterminated", 30_000, "normal")

        self.assertEqual(raised.exception.code, "COMMAND_INCOMPLETE")
        self.assertEqual(bridge.tmux.typed, [])
        self.assertEqual(bridge.tmux.keys, [])

    def test_remote_transport_disconnect_wakes_job(self):
        bridge = bridge_fixture()
        bridge.tmux.current_command = "ssh"
        submitted = bridge.terminal_submit("%0", 1, "du /remote", 60_000, "normal")
        bridge.tmux.content = "prompt$ du /remote\nclient_loop: send disconnect: Broken pipe\nlocal$ "
        bridge.tmux.current_command = "zsh"

        result = bridge.terminal_job_status(submitted["job_id"])

        self.assertEqual(result["state"], "NEEDS_ATTENTION")
        self.assertEqual(result["attention_reason"], "session_context_changed")

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
