"""Composite execution keeps one admission receipt and never replays input."""
import json
import threading
import unittest
from unittest.mock import patch

from bridge.common import BridgeError
from bridge.runtime.admission import receive, request_scope
from tests.context_support import bridge_fixture


class TerminalRunTest(unittest.TestCase):
    def test_routine_run_does_not_depend_on_previous_thread_identity(self):
        self.bridge.leases["%0"].update(state="REVOKED", revoke_reason="daemon_restart",
            authorization={"thread_id": "older-thread"})
        self.assertEqual(self.run_command()["generation"], 2)

    def test_new_call_after_restart_gets_internal_authority(self):
        self.bridge.leases["%0"].update(state="REVOKED", revoke_reason="daemon_restart")
        result = self.run_command()
        self.assertEqual(result["generation"], 2)
        self.assertEqual(len(self.bridge.tmux.typed), 1)

    def setUp(self):
        self.bridge = bridge_fixture()
        self.bridge.generations = {"%0": 1}
        self.bridge.event_sequence = 0
        self.args = dict(pane="%0", request_id="run-1", text="sleep 60", wait_ms=1)

    def run_command(self, **changes):
        return self.bridge.dispatch("terminal_run", dict(self.args, **changes))

    def interrupt(self):
        self.bridge.handle_human_event(dict(type="human_interrupt", pane="%0",
                                           pre_interrupt_content="busy"))

    def test_no_lease_acquires_once_submits_once_and_waits(self):
        self.bridge.leases = {}
        self.assertEqual(self.run_command()["state"], "WAIT_TIMEOUT")
        generation = self.bridge.generations["%0"]
        repeated = self.run_command(wait_ms=2)
        self.assertEqual(repeated["generation"], generation)
        self.assertEqual(len(self.bridge.tmux.typed), 1)
        self.assertEqual(self.bridge.generations["%0"], generation)

    def test_active_lease_is_reused_including_authorization(self):
        self.bridge.leases["%0"]["authorization"] = {"thread_id": "trusted"}
        result = self.run_command()
        self.assertEqual(result["generation"], 1)
        self.assertEqual(self.bridge.leases["%0"]["authorization"], {"thread_id": "trusted"})

    def test_interrupted_replay_only_observes_new_id_may_renew(self):
        result = self.run_command()
        self.interrupt()
        repeated = self.run_command()
        self.assertEqual(repeated["job_id"], result["job_id"])
        self.assertEqual(repeated["state"], "INTERRUPTED_BY_HUMAN")
        self.assertEqual(self.bridge.generations["%0"], 1)
        self.assertEqual(len(self.bridge.tmux.typed), 1)
        new = self.run_command(request_id="run-2")
        self.assertEqual(new["generation"], 2)
        self.assertEqual(len(self.bridge.tmux.typed), 2)

    def test_old_receipt_cannot_acquire_after_interrupt(self):
        self.run_command()
        earlier = receive()
        self.interrupt()
        with request_scope(earlier), self.assertRaises(BridgeError):
            self.run_command(request_id="late-old-call")
        self.assertEqual(len(self.bridge.tmux.typed), 1)

    def test_revocation_between_admission_and_submit_is_not_renewed(self):
        self.run_command()
        strict_submit = self.bridge.terminal_submit
        def interrupt_then_submit(**params):
            self.interrupt()
            return strict_submit(**params)
        with patch.object(self.bridge, "terminal_submit", side_effect=interrupt_then_submit):
            with self.assertRaises(BridgeError) as raised:
                self.run_command(request_id="run-2")
        self.assertEqual(raised.exception.code, "EXECUTION_LEASE_INVALID")
        self.assertEqual(self.bridge.generations["%0"], 1)
        self.assertEqual(len(self.bridge.tmux.typed), 1)

    def test_approval_is_still_required_and_can_be_consumed_once(self):
        with self.assertRaises(BridgeError) as raised:
            self.run_command(resource_class="high_io", expected_duration_ms=1000)
        self.assertEqual(raised.exception.code, "LONG_RUN_APPROVAL_REQUIRED")
        self.assertEqual(self.bridge.tmux.typed, [])
        with self.assertRaises(BridgeError):
            self.bridge.terminal_long_run_approve("%0", 1,
                request_id=raised.exception.details["request_id"])
        self.bridge.terminal_long_run_decide(raised.exception.details["request_id"], "approve")
        approval = self.bridge.terminal_long_run_approve("%0", 1,
            request_id=raised.exception.details["request_id"])
        result = self.run_command(request_id="approved", resource_class="high_io",
                                  expected_duration_ms=1000,
                                  long_run_approval_id=approval["approval_id"])
        self.assertEqual(result["generation"], 1)
        self.run_command(request_id="approved", resource_class="high_io",
                         expected_duration_ms=1000,
                         long_run_approval_id=approval["approval_id"])
        self.assertEqual(len(self.bridge.tmux.typed), 1)

    def test_conflict_reserved_restart_and_access_checks(self):
        self.run_command()
        with self.assertRaises(BridgeError) as raised:
            self.run_command(text="echo changed")
        self.assertEqual(raised.exception.code, "COMMAND_REQUEST_CONFLICT")
        self.bridge.command_requests = json.loads(json.dumps(self.bridge.command_requests))
        self.bridge.command_requests["run-1"]["state"] = "RESERVED"
        with self.assertRaises(BridgeError) as raised:
            self.run_command()
        self.assertEqual(raised.exception.code, "COMMAND_REQUEST_AMBIGUOUS")
        with self.assertRaises(BridgeError):
            self.run_command(pane="%99", request_id="denied")
        self.assertEqual(len(self.bridge.tmux.typed), 1)

    def test_invalid_wait_and_multiline_do_not_execute(self):
        for wait in [0, 600001, True, "10"]:
            with self.assertRaises(BridgeError):
                self.run_command(wait_ms=wait)
        with self.assertRaises(BridgeError):
            self.run_command(text="echo one\necho two")
        self.assertEqual(self.bridge.tmux.typed, [])

    def test_human_event_wakes_combined_wait(self):
        waiting = threading.Event()
        original_wait = self.bridge.terminal_wait_job
        def wait(*args, **kwargs):
            waiting.set()
            return original_wait(*args, **kwargs)
        results = []
        with patch.object(self.bridge, "terminal_wait_job", side_effect=wait):
            task = threading.Thread(target=lambda: results.append(self.run_command(wait_ms=5000)))
            task.start()
            self.assertTrue(waiting.wait(1))
            self.interrupt()
            task.join(2)
        self.assertFalse(task.is_alive())
        self.assertEqual(results[0]["state"], "INTERRUPTED_BY_HUMAN")

    def test_cancel_wait_does_not_interrupt_or_reexecute(self):
        self.bridge.terminal_cancel_wait("cancel-before-register")
        result = self.run_command(wait_ms=5000, wait_id="cancel-before-register")
        self.assertEqual(result["state"], "WAIT_CANCELLED")
        self.assertEqual(self.bridge.leases["%0"]["state"], "ACTIVE")
        self.assertEqual(self.bridge.jobs[result["job_id"]]["state"], "RUNNING")
        self.run_command(wait_ms=1, wait_id="new-observation")
        self.assertEqual(len(self.bridge.tmux.typed), 1)
        self.assertEqual(self.bridge.tmux.keys, [("%0", "Enter")])
