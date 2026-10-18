"""Receipt order, not new user turns or caller timestamps, renews authority."""

import unittest

from bridge.common import BridgeError
from bridge.runtime.admission import receive, request_scope
from tests.context_support import bridge_fixture


class LocalReauthorizationTest(unittest.TestCase):
    def setUp(self):
        self.bridge = bridge_fixture()
        self.bridge.generations = {'%0': 1}
        self.bridge.event_sequence = 0
        self.arguments = dict(pane='%0', generation=1, text='sleep 60', expected_duration_ms=60000)
        self.bridge.dispatch('terminal_submit', self.arguments)
        self.old_receipt = receive()
        self.bridge.handle_human_event(dict(type='human_interrupt', pane='%0',
                                           pre_interrupt_content='busy'))

    def test_new_call_automatically_renews_and_returns_effective_generation(self):
        result = self.bridge.dispatch('terminal_submit', self.arguments)
        self.assertEqual(result['generation'], 2)
        self.assertEqual(self.bridge.jobs[result['job_id']]['generation'], 2)
        self.assertEqual(self.bridge.leases['%0']['state'], 'ACTIVE')

    def test_earlier_call_cannot_be_renewed_when_it_runs_late(self):
        with request_scope(self.old_receipt), self.assertRaises(BridgeError) as raised:
            self.bridge.dispatch('terminal_submit', self.arguments)
        self.assertEqual(raised.exception.code, 'EXECUTION_LEASE_INVALID')
        self.assertEqual(self.bridge.generations['%0'], 1)

    def test_old_block_keeps_its_original_receipt_for_later_steps(self):
        with request_scope(self.old_receipt), self.assertRaises(BridgeError):
            self.bridge.prepare_command_lease('%0', 1)

    def test_auto_renew_does_not_bypass_resource_approval(self):
        with self.assertRaises(BridgeError) as raised:
            self.bridge.dispatch('terminal_submit', dict(self.arguments, resource_class='full_scan'))
        self.assertEqual(raised.exception.code, 'LONG_RUN_APPROVAL_REQUIRED')
        self.assertEqual(len(self.bridge.jobs), 1)

    def test_released_and_unknown_generations_are_not_auto_renewed(self):
        self.bridge.leases['%0']['state'] = 'RELEASED'
        with self.assertRaises(BridgeError):
            self.bridge.dispatch('terminal_submit', self.arguments)
        self.bridge.leases['%0']['state'] = 'REVOKED'
        with self.assertRaises(BridgeError):
            self.bridge.dispatch('terminal_submit', dict(self.arguments, generation=999))

    def test_same_user_turn_can_acquire_after_interrupt(self):
        auth = dict(thread_id='thread-1', turn_id='turn-1', turn_started_at_ms=1)
        self.bridge.leases['%0']['authorization'] = auth
        result = self.bridge.dispatch('acquire_execution', dict(pane='%0', **auth))
        self.assertEqual(result['generation'], 2)
        self.assertEqual(result['authorization'], auth)

    def test_normal_long_duration_alone_does_not_request_approval(self):
        result = self.bridge.dispatch('terminal_submit', dict(self.arguments, expected_duration_ms=300000))
        self.assertTrue(result['accepted'])

    def test_repeated_ctrl_c_revokes_each_new_generation(self):
        result = self.bridge.dispatch('terminal_submit', self.arguments)
        self.bridge.handle_human_event(dict(type='human_interrupt', pane='%0',
                                           pre_interrupt_content='busy'))
        self.assertEqual(self.bridge.leases['%0']['state'], 'REVOKED')
        next_result = self.bridge.dispatch('terminal_submit', dict(self.arguments, generation=result['generation']))
        self.assertEqual(next_result['generation'], 3)

