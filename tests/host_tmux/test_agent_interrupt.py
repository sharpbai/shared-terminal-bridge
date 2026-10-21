"""Real SIGINT success and ignored SIGINT must have distinct job results."""
import shutil
import time
import unittest
import uuid

from bridge.common import BridgeError
from bridge.tmux.backend import TmuxBackend
from tests.context_support import bridge_fixture


class AgentInterruptHostTest(unittest.TestCase):
    def test_interrupt_confirmation_and_ignored_signal_guard(self):
        if not shutil.which('tmux'):
            self.skipTest('host tmux required')
        backend = TmuxBackend('stb-agent-test-' + uuid.uuid4().hex[:12])
        bridge = bridge_fixture()
        bridge.tmux = backend
        bridge.generations = {'%0': 1}
        bridge.event_sequence = 0

        def until(check):
            deadline = time.monotonic() + 5
            while not check():
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.01)
        try:
            backend.run('new-session', '-d', '-s', 'agent', '-x', '130',
                        "env PS1='AGENT> ' /bin/bash --noprofile --norc -i")
            until(lambda: backend.read('%0', 100).rstrip().endswith('AGENT>'))
            backend.run('copy-mode', '-t', '%0')
            def assert_scrolling():
                self.assertEqual(backend.run('display-message', '-p', '-t', '%0',
                    '#{pane_in_mode}').stdout.strip(), '1')
            assert_scrolling()
            first = bridge.dispatch('terminal_run', dict(pane='%0', request_id='sleep',
                text="bash -c 'trap \"sleep 1.2; exit 0\" INT; echo READY; while :; do sleep 0.1; done'", wait_ms=1))
            until(lambda: 'READY' in backend.read('%0', 100).splitlines())
            started = time.monotonic()
            result = bridge.terminal_interrupt_job(first['job_id'])
            self.assertGreaterEqual(time.monotonic() - started, 1)
            self.assertTrue(result['termination_confirmed'], result)
            self.assertEqual(result['state'], 'INTERRUPTED_BY_AGENT')
            self.assertEqual(bridge.leases['%0']['state'], 'ACTIVE')
            assert_scrolling()
            fresh = bridge.dispatch('terminal_run', dict(pane='%0', request_id='next',
                text="printf 'NEXT_OK\\n'", wait_ms=3000))
            self.assertEqual(fresh['state'], 'COMPLETED', fresh)
            assert_scrolling()
            with self.assertRaises(BridgeError):
                bridge.terminal_interrupt_job(first['job_id'])

            ignored = bridge.dispatch('terminal_run', dict(pane='%0', request_id='ignore',
                text="trap '' INT; sleep 30", wait_ms=1))
            until(lambda: backend.state('%0')['current_command'] == 'sleep')
            pending = bridge.terminal_interrupt_job(ignored['job_id'], wait_ms=100)
            self.assertFalse(pending['termination_confirmed'], pending)
            self.assertEqual(pending['execution_phase'], 'EXECUTING')
            with self.assertRaises(BridgeError) as error:
                bridge.dispatch('terminal_run', dict(pane='%0', request_id='blocked',
                    text='printf MUST_NOT_RUN', wait_ms=1))
            self.assertEqual(error.exception.code, 'TERMINAL_JOB_ALREADY_RUNNING')
            self.assertEqual(bridge.event_sequence, 0)
        finally:
            bridge.close_terminal_streams()
            backend.run('kill-server', check=False)
