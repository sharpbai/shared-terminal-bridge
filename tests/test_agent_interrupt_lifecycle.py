"""Agent key requests are ordered provenance, not proof of process exit."""
import unittest
import threading
import time
from unittest import mock
from tests import test_terminal_event_order as ordered
from bridge.execution.lifecycle import execution_phase


class AgentInterruptLifecycleTest(unittest.TestCase):
    setUp = ordered.TerminalEventOrderTest.setUp
    emit = ordered.TerminalEventOrderTest.emit

    def wait_registered(self, wait_id):
        deadline = time.monotonic() + 1
        while wait_id not in self.bridge.wait_handles:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.005)

    def test_interrupt_waits_past_old_attention_until_ordered_prompt(self):
        self.job.update(state='NEEDS_ATTENTION', attention_reason='password:')
        results = []
        worker = threading.Thread(target=lambda: results.append(
            self.bridge.terminal_interrupt_job(self.job['job_id'], wait_ms=1000, wait_id='prompt')))
        worker.start()
        try:
            self.wait_registered('prompt')
            self.assertTrue(worker.is_alive())
            self.emit('terminal_output', content='^Cprompt$ ')
        finally:
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertTrue(results[0]['termination_confirmed'])
        self.assertEqual(results[0]['state'], 'INTERRUPTED_BY_AGENT')

    def test_cancel_only_stops_observation_without_another_key(self):
        results = []
        worker = threading.Thread(target=lambda: results.append(
            self.bridge.terminal_interrupt_job(self.job['job_id'], wait_ms=5000, wait_id='cancel')))
        worker.start()
        try:
            self.wait_registered('cancel')
            self.bridge.terminal_cancel_wait('cancel')
        finally:
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0]['state'], 'WAIT_CANCELLED')
        self.assertFalse(results[0]['termination_confirmed'])
        self.assertEqual(self.bridge.tmux.keys.count(('%0', 'C-c')), 1)
        self.assertEqual(execution_phase(self.job), 'EXECUTING')

    def test_pre_cancel_or_bad_budget_does_not_send_key(self):
        from bridge.common import BridgeError
        with self.assertRaises(BridgeError):
            self.bridge.terminal_interrupt_job(self.job['job_id'], wait_ms=0)
        self.bridge.terminal_cancel_wait('early')
        result = self.bridge.terminal_interrupt_job(self.job['job_id'], wait_id='early')
        self.assertFalse(result['accepted'])
        self.assertNotIn(('%0', 'C-c'), self.bridge.tmux.keys)

    def test_job_interrupt_reports_pending_without_freeing_the_pane(self):
        with mock.patch.object(self.bridge, 'terminal_wait_job', return_value={
                'state': 'WAIT_TIMEOUT', 'execution_phase': 'EXECUTING'}):
            result = self.bridge.terminal_interrupt_job(self.job['job_id'])
        self.assertTrue(result['accepted'])
        self.assertFalse(result['termination_confirmed'])
        self.assertEqual(execution_phase(self.job), 'EXECUTING')
        self.assertIn('do not submit', result['guidance'])

    def test_input_ctrl_c_uses_the_same_interrupt_provenance(self):
        self.bridge.terminal_input_job(self.job['job_id'], 'key-interrupt', key='C-c')
        self.assertIn('agent_interrupt_requested_at', self.job)
        self.assertEqual(self.bridge.interrupt_sources['%0']['source'], 'agent')
        self.assertEqual(execution_phase(self.job), 'EXECUTING')

    def test_request_keeps_guard_until_prompt_then_finishes_as_agent(self):
        self.emit('agent_interrupt_requested', interrupt_id='agent-one')
        self.assertEqual(execution_phase(self.job), 'EXECUTING')
        self.emit('terminal_output', content='still running\r\n')
        self.assertEqual(execution_phase(self.job), 'EXECUTING')
        # Remote shells can redraw after ^C without a newline and switch
        # keypad modes using ESC= / ESC> after the prompt.
        self.emit('terminal_output', content='^Cprompt$ \x1b[?1h\x1b=')
        self.assertEqual(self.job['state'], 'INTERRUPTED_BY_AGENT')
        self.assertEqual(execution_phase(self.job), 'FINISHED')
        self.assertEqual(self.bridge.leases['%0']['state'], 'ACTIVE')
        self.assertEqual(self.bridge.event_sequence, 0)

    def test_completed_before_agent_request_stays_completed(self):
        self.emit('terminal_output', content='done\nprompt$ ')
        self.emit('agent_interrupt_requested', interrupt_id='late')
        self.assertEqual(self.job['state'], 'COMPLETED')
        self.assertNotIn('agent_interrupt_requested_at', self.job)

    def test_echoed_ctrl_c_does_not_poison_the_next_jobs_baseline(self):
        self.emit('agent_interrupt_requested', interrupt_id='agent-one')
        self.emit('terminal_output', content='^Cprompt$ ')
        self.bridge.tmux.content = '^Cprompt$ '
        next_job = self.bridge.terminal_submit('%0', 1, 'echo NEXT', 1000)
        self.job = self.bridge.jobs[next_job['job_id']]
        self.emit('command_started')
        self.emit('terminal_output', content='NEXT\nprompt$ ')
        self.assertEqual(self.job['state'], 'COMPLETED')

    def test_human_after_agent_request_retains_authoritative_revoke(self):
        self.emit('agent_interrupt_requested', interrupt_id='agent-one')
        self.emit('human_interrupt')
        self.emit('terminal_output', content='^Cprompt$ ')
        self.assertEqual(self.job['state'], 'INTERRUPTED_BY_HUMAN')
        self.assertEqual(self.bridge.leases['%0']['state'], 'REVOKED')

