#!/usr/bin/env python3
"""Bridge-level tests for cursor observations and terminal task blocks."""

import pathlib
import sys
import tempfile
import threading
import types
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from bridge.local_bridge import BridgeError, LocalBridge, TmuxBackend, unix_ms  # noqa: E402


class FakeTmux:
    socket_name = "test"

    def __init__(self):
        self.content = "prompt$ "
        self.typed = []
        self.keys = []
        self.current_command = "zsh"

    def read(self, pane, lines):
        return self.content

    def send_text(self, pane, text):
        self.typed.append((pane, text))

    def send_key(self, pane, key):
        self.keys.append((pane, key))

    def state(self, pane):
        return {"current_command": self.current_command}


def bridge_fixture():
    bridge = LocalBridge.__new__(LocalBridge)
    bridge.tmux = FakeTmux()
    bridge.allowed_panes = {"%0"}
    bridge.leases = {"%0": {"pane": "%0", "generation": 1, "state": "ACTIVE"}}
    bridge.observation_cursors = {}
    bridge.managed_sessions = {}
    bridge.task_blocks = {}
    bridge.long_run_requests = {}
    bridge.long_run_approvals = {}
    bridge.jobs = {}
    bridge.wait_handles = {}
    bridge.cancelled_wait_ids = set()
    bridge.interrupt_sources = {}
    bridge.audit = []
    bridge.history_file = None
    bridge.lock = threading.RLock()
    bridge.persist_state = lambda: None
    bridge._notify_job = lambda job: None
    return bridge


class ContextBridgeTest(unittest.TestCase):
    def test_first_managed_session_starts_server_before_global_options(self):
        tmux = TmuxBackend("fresh-server")
        calls = []

        def run(*arguments, check=True):
            calls.append(arguments)
            if arguments[0] == "has-session":
                return types.SimpleNamespace(returncode=1, stdout="", stderr="no server")
            if arguments[0] == "display-message" and arguments[-1] == "#{pane_id}":
                return types.SimpleNamespace(returncode=0, stdout="%0\n", stderr="")
            if arguments[0] == "display-message" and arguments[-1] == "#{history_limit}":
                return types.SimpleNamespace(returncode=0, stdout="100000\n", stderr="")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        tmux.run = run
        created = tmux.create_managed_session("verify33", "/tmp")

        new_session_index = next(
            index for index, call in enumerate(calls) if call[0] == "new-session"
        )
        global_option_index = next(
            index
            for index, call in enumerate(calls)
            if call[:3] == ("set-option", "-g", "history-limit")
        )
        self.assertLess(new_session_index, global_option_index)
        self.assertEqual(created["pane"], "%0")
        self.assertEqual(created["history_limit"], 100000)

    def test_tmux_submit_orders_literal_text_and_enter_in_one_call(self):
        tmux = TmuxBackend("test")
        calls = []
        tmux.run = lambda *args, **kwargs: calls.append(args)

        tmux.submit("%0", "printf ok")

        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0],
            (
                "send-keys", "-t", "%0", "-l", "printf ok",
                ";", "send-keys", "-t", "%0", "Enter",
            ),
        )

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

    def test_read_only_task_runner_executes_steps_and_assertions(self):
        bridge = bridge_fixture()
        submitted = []

        def submit(pane, generation, text, expected_duration_ms, resource_class):
            submitted.append(text)
            return {"job_id": f"job-{len(submitted)}"}

        outputs = {
            "job-1": "Filesystem Used\n/dev/x 10G",
            "job-2": "x86_64",
        }
        bridge.terminal_submit = submit
        bridge.terminal_wait_job = lambda job_id, wait_ms: {
            "state": "COMPLETED",
            "completion_confidence": "prompt_returned",
            "output_excerpt": {"content": outputs[job_id]},
        }

        result = bridge.terminal_task_block_execute(
            "%0",
            1,
            [
                {"text": "df -h", "assert": {"contains": "Filesystem"}},
                {"text": "uname -m", "assert": {"regex": "x86_64"}},
            ],
        )

        self.assertEqual(result["state"], "COMPLETED")
        self.assertEqual(submitted, ["df -h", "uname -m"])
        self.assertTrue(all(step["assertion"]["passed"] for step in result["steps"]))
        self.assertTrue(all(step["output_ref"].startswith("job://") for step in result["steps"]))

    def test_read_only_task_runner_rejects_shell_programs_before_writing(self):
        bridge = bridge_fixture()

        with self.assertRaises(BridgeError) as raised:
            bridge.terminal_task_block_execute(
                "%0", 1, [{"text": "df -h | sort -h"}]
            )

        self.assertEqual(raised.exception.code, "TASK_BLOCK_COMMAND_NOT_READ_ONLY")
        self.assertEqual(bridge.tmux.keys, [])

    def test_read_only_task_runner_rejects_mutating_variants(self):
        bridge = bridge_fixture()
        commands = (
            "sed -i s/a/b/ file",
            "qemu-img check -r all disk.qcow2",
            "systemctl stop ssh status",
            "journalctl --vacuum-time=1s",
        )
        for command in commands:
            with self.subTest(command=command):
                with self.assertRaises(BridgeError) as raised:
                    bridge.terminal_task_block_execute(
                        "%0", 1, [{"text": command}]
                    )
                self.assertEqual(
                    raised.exception.code, "TASK_BLOCK_COMMAND_NOT_READ_ONLY"
                )
        self.assertEqual(bridge.tmux.keys, [])

    def test_recovery_diagnostics_have_exact_read_only_runner_profiles(self):
        allowed = (
            "fdisk -l /dev/sda",
            "blkid -p /dev/sda1",
            "blkid -p -O 33554432 disk.img",
            "testdisk /version",
            "qemu-nbd --version",
        )
        for command in allowed:
            with self.subTest(command=command):
                self.assertTrue(LocalBridge._validate_read_only_command(command))

        denied = (
            "fdisk /dev/sda",
            "blkid /dev/sda1",
            "blkid -p -c cache /dev/sda1",
            "testdisk /dev/sda",
            "qemu-nbd --connect=/dev/nbd0 disk.qcow2",
        )
        for command in denied:
            with self.subTest(command=command):
                with self.assertRaises(BridgeError) as raised:
                    LocalBridge._validate_read_only_command(command)
                self.assertEqual(raised.exception.code, "TASK_BLOCK_COMMAND_NOT_READ_ONLY")

    def test_program_profile_is_local_guidance(self):
        bridge = bridge_fixture()
        listed = bridge.terminal_program_profile()
        self.assertEqual(
            [item["program"] for item in listed["profiles"]],
            ["photorec", "testdisk"],
        )
        profile = bridge.terminal_program_profile("/usr/local/bin/testdisk")
        self.assertEqual(profile["profile"]["preferred_interface"], "cmd")
        self.assertEqual(profile["profile"]["tui_policy"], "human_assisted")
        self.assertEqual(bridge.tmux.typed, [])
        with self.assertRaises(BridgeError) as raised:
            bridge.terminal_program_profile("unknown-tui")
        self.assertEqual(raised.exception.code, "PROGRAM_PROFILE_NOT_FOUND")

    def test_read_only_task_runner_stops_after_human_interrupt(self):
        bridge = bridge_fixture()
        submitted = []

        def submit(pane, generation, text, expected_duration_ms, resource_class):
            submitted.append(text)
            return {"job_id": "job-1"}

        def wait(job_id, wait_ms):
            bridge.leases["%0"].update({"state": "REVOKED", "event_seq": 4})
            return {
                "state": "INTERRUPTED_BY_HUMAN",
                "completion_confidence": "authoritative",
                "output_excerpt": {"content": "partial"},
            }

        bridge.terminal_submit = submit
        bridge.terminal_wait_job = wait
        result = bridge.terminal_task_block_execute(
            "%0", 1, [{"text": "df -h"}, {"text": "uname -m"}]
        )

        self.assertEqual(result["state"], "INTERRUPTED")
        self.assertEqual(submitted, ["df -h"])

    def test_remote_transport_disconnect_wakes_job(self):
        bridge = bridge_fixture()
        bridge.tmux.current_command = "ssh"
        submitted = bridge.terminal_submit("%0", 1, "du /remote", 60_000, "normal")
        bridge.tmux.content = "prompt$ du /remote\nclient_loop: send disconnect: Broken pipe\nlocal$ "
        bridge.tmux.current_command = "zsh"

        result = bridge.terminal_job_status(submitted["job_id"])

        self.assertEqual(result["state"], "NEEDS_ATTENTION")
        self.assertEqual(result["attention_reason"], "session_context_changed")

    def test_long_run_budgets_are_derived_when_omitted(self):
        bridge = bridge_fixture()
        request = bridge.terminal_long_run_request(
            "%0", 1, "du /", 300_000, "high_io"
        )
        self.assertEqual(request["idle_budget_ms"], 150_000)
        self.assertEqual(request["total_budget_ms"], 600_000)

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
