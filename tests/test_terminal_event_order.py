"""Replay exactly ordered pane events without a terminal or model."""

import threading
import unittest

from bridge.tmux.control_stream import ControlStream, decode_output
from tests.context_support import bridge_fixture


class TerminalEventOrderTest(unittest.TestCase):
    def setUp(self):
        self.bridge = bridge_fixture()
        self.bridge.event_sequence = 0
        result = self.bridge.terminal_submit('%0', 1, 'sleep 60', 60000)
        self.job = self.bridge.jobs[result['job_id']]
        self.seq = 0
        self.emit('command_started')

    def emit(self, kind, **values):
        self.seq += 1
        event = dict(type=kind, pane='%0', stream_epoch='epoch1', stream_seq=self.seq,
                     scope=dict(job_id=self.job['job_id'], generation=1), **values)
        self.bridge.handle_terminal_event(event)
        return event

    def test_prompt_before_ctrl_c_does_not_revoke(self):
        self.emit('terminal_output', content='done\nprompt$ ')
        self.emit('human_interrupt')
        self.assertEqual(self.job['execution_phase'], 'FINISHED')
        self.assertEqual(self.bridge.leases['%0']['state'], 'ACTIVE')

    def test_ctrl_c_before_prompt_revokes_and_cannot_be_undone(self):
        self.emit('terminal_output', content='sleep 60\n')
        self.emit('human_interrupt')
        self.emit('terminal_output', content='^C\nprompt$ ')
        self.assertEqual(self.job['execution_phase'], 'INTERRUPTED')
        self.assertEqual(self.bridge.leases['%0']['state'], 'REVOKED')

    def test_duplicate_interrupt_is_idempotent(self):
        event = self.emit('human_interrupt')
        self.bridge.handle_terminal_event(event)
        self.assertEqual(self.bridge.event_sequence, 1)

    def test_gap_does_not_guess_interruption_order(self):
        self.seq += 1
        self.emit('human_interrupt')
        self.assertTrue(self.job['event_stream_lost'])
        self.assertEqual(self.bridge.leases['%0']['state'], 'ACTIVE')

    def test_poll_does_not_overtake_queued_interrupt(self):
        self.bridge.tmux.content = 'done\nprompt$ '
        self.bridge.terminal_job_status(self.job['job_id'])
        self.assertEqual(self.job['execution_phase'], 'EXECUTING')
        self.emit('human_interrupt')
        self.assertEqual(self.job['execution_phase'], 'INTERRUPTED')

    def test_disconnect_wakes_wait_without_claiming_human_override(self):
        wake = threading.Event()
        self.bridge.wait_handles['test'] = dict(job_id=self.job['job_id'], event=wake)
        self.emit('stream_lost')
        self.assertTrue(wake.is_set())
        self.assertEqual(self.bridge.leases['%0']['state'], 'ACTIVE')
        self.assertEqual(self.job['attention_reason'], 'terminal_event_stream_lost')

    def test_legacy_socket_cannot_overtake_ordered_output(self):
        self.bridge.handle_human_event(dict(type='human_interrupt', pane='%0',
                                           pre_interrupt_content='busy'))
        self.assertEqual(self.bridge.leases['%0']['state'], 'ACTIVE')
        self.emit('terminal_output', content='done\nprompt$ ')
        self.emit('human_interrupt')
        self.assertEqual(self.bridge.leases['%0']['state'], 'ACTIVE')

    def test_new_submit_cannot_replace_executing_scope(self):
        from unittest import mock
        from bridge.common import BridgeError
        self.bridge.ensure_terminal_stream = mock.Mock(return_value=mock.Mock())
        with self.assertRaises(BridgeError) as error:
            self.bridge.terminal_submit('%0', 1, 'echo NEXT', 1000)
        self.assertEqual(error.exception.code, 'TERMINAL_JOB_ALREADY_RUNNING')

    def test_control_parser_joins_split_unicode_prompt(self):
        self.assertEqual(decode_output(br'\003\134u0003'), b'\x03\\u0003')
        events = []
        stream = ControlStream.__new__(ControlStream)
        import codecs
        stream.pane, stream.epoch, stream.sequence = '%0', 'test', 0
        stream.scope, stream.tail = None, ''
        stream.decoder = codecs.getincrementaldecoder('utf-8')('replace')
        stream.callback = events.append
        stream._line(b'%message STB_START %0 job_test 1\n')
        stream._line(b'%output %0 done\\015\\012pro\n')
        stream._line(b'%output %0 mpt$ \n')
        stream._line(b'%message STB_INTERRUPT %0 client\n')
        self.assertEqual([e['stream_seq'] for e in events], [1, 2, 3, 4])
        self.assertEqual(events[2]['content'], 'done\r\nprompt$ ')

