"""Only an in-flight STB command turns physical C-c into lease revocation."""
import unittest
import threading
from unittest import mock
from tests.context_support import bridge_fixture


class HumanInterruptScopeTest(unittest.TestCase):
    def check_event(self, job, screen, revoked):
        bridge = bridge_fixture()
        bridge.event_sequence = 0
        if job is not None:
            bridge.jobs['test'] = dict(pane='%0', generation=1,
                                       baseline_prompt='host:old $', **job)
        event = dict(type='human_interrupt', pane='%0')
        if screen is not None:
            event['pre_interrupt_content'] = screen
        bridge.handle_human_event(event)
        self.assertEqual(bridge.leases['%0']['state'], 'REVOKED' if revoked else 'ACTIVE')
        self.assertEqual(bool(bridge.interrupt_sources), revoked)

    def test_idle_lease_does_not_revoke(self):
        self.check_event(None, 'host:old $', False)

    def test_running_command_revokes(self):
        self.check_event({'state': 'RUNNING'}, 'sleep 60\n', True)

    def test_returned_prompt_does_not_revoke_stale_running_job(self):
        self.check_event({'state': 'RUNNING'}, 'done\nhost:new $', False)

    def test_completed_job_and_manual_command_do_not_revoke(self):
        self.check_event({'state': 'COMPLETED'}, 'manual command output', False)

    def test_interactive_command_still_revokes(self):
        self.check_event({'state': 'NEEDS_ATTENTION'}, 'Password:', True)

    def test_event_without_execution_evidence_does_not_revoke(self):
        self.check_event({'state': 'RUNNING'}, None, False)

    def test_old_generation_does_not_revoke(self):
        bridge = bridge_fixture()
        bridge.event_sequence = 0
        bridge.jobs['old'] = dict(pane='%0', generation=0, state='RUNNING')
        bridge.handle_human_event(dict(type='human_interrupt', pane='%0', pre_interrupt_content='busy'))
        self.assertEqual(bridge.leases['%0']['state'], 'ACTIVE')

    def test_finished_execution_does_not_revoke_even_with_running_wait_state(self):
        self.check_event({'state': 'RUNNING', 'execution_phase': 'FINISHED'}, 'busy', False)

    def test_human_decision_checkpoint_is_still_executing(self):
        self.check_event({'state': 'HUMAN_DECISION_REQUIRED',
                          'execution_phase': 'EXECUTING'}, 'busy', True)

    def test_interrupt_transitions_task_before_any_model_or_poll(self):
        bridge = bridge_fixture()
        bridge.event_sequence = 0
        result = bridge.terminal_submit('%0', 1, 'sleep 60', 60000)
        job = bridge.jobs[result['job_id']]
        wake = threading.Event()
        bridge.wait_handles['test'] = dict(job_id=result['job_id'], event=wake)
        self.assertEqual(job['execution_phase'], 'EXECUTING')
        bridge.handle_human_event(dict(type='human_interrupt', pane='%0',
                                      pre_interrupt_content='sleep 60'))
        self.assertEqual(job['execution_phase'], 'INTERRUPTED')
        self.assertEqual(job['state'], 'INTERRUPTED_BY_HUMAN')
        self.assertTrue(wake.is_set())

    def test_failed_submission_does_not_leave_executing_task(self):
        bridge = bridge_fixture()
        bridge.tmux.send_key = mock.Mock(side_effect=RuntimeError('submission failed'))
        with self.assertRaises(RuntimeError):
            bridge.terminal_submit('%0', 1, 'sleep 60', 60000)
        self.assertEqual(next(iter(bridge.jobs.values()))['execution_phase'], 'FINISHED')
