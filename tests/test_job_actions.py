"""Job handles hide counters but never bypass their original authority."""
import unittest
from tests.context_support import bridge_fixture
from bridge.common import BridgeError


class JobActionTest(unittest.TestCase):
    def setUp(self):
        self.core = bridge_fixture()
        self.core.generations = {"%0": 1}
        self.core.event_sequence = 0
        self.job = self.core.dispatch("terminal_run", dict(
            pane="%0", request_id="run", text="sleep 60", wait_ms=1))["job_id"]

    def test_input_is_deduplicated_without_caller_generation(self):
        args = dict(job_id=self.job, request_id="answer", text="yes")
        self.core.dispatch("terminal_input_job", args)
        self.core.dispatch("terminal_input_job", args)
        self.assertEqual(self.core.tmux.typed.count(("%0", "yes")), 1)

    def test_old_job_cannot_control_new_authority(self):
        self.core.acquire_execution("%0")
        with self.assertRaises(BridgeError):
            self.core.dispatch("terminal_input_job", dict(job_id=self.job, request_id="old", key="Enter"))
        with self.assertRaises(BridgeError):
            self.core.dispatch("terminal_interrupt_job", dict(job_id=self.job))
        self.assertEqual(self.core.tmux.keys, [("%0", "Enter")])

    def test_human_interrupt_blocks_further_job_input(self):
        self.core.handle_human_event(dict(type="human_interrupt", pane="%0", pre_interrupt_content="busy"))
        with self.assertRaises(BridgeError):
            self.core.dispatch("terminal_input_job", dict(job_id=self.job, request_id="old", text="yes"))
        self.assertEqual(self.core.leases["%0"]["state"], "REVOKED")

    def test_approval_without_human_decision_still_fails(self):
        with self.assertRaises(BridgeError) as error:
            self.core.dispatch("terminal_run", dict(pane="%0", request_id="risk",
                text="du /", resource_class="high_io", expected_duration_ms=1000, wait_ms=1))
        request_id = error.exception.details["request_id"]
        with self.assertRaises(BridgeError):
            self.core.dispatch("terminal_approve_request", dict(request_id=request_id))
        self.core.terminal_long_run_decide(request_id, "approve")
        approved = self.core.dispatch("terminal_approve_request", dict(request_id=request_id))
        self.assertIn("approval_id", approved)
