"""Ordered control-mode output and physical-key binding on an isolated server."""

import pathlib
import shlex
import shutil
import time
import unittest
import uuid

from bridge.tmux.backend import TmuxBackend
from tests.context_support import bridge_fixture


class OrderedEventsHostTest(unittest.TestCase):
    def test_returned_prompt_then_key_and_running_then_key(self):
        if not shutil.which('tmux'):
            self.skipTest('tmux not installed')
        backend = TmuxBackend('stb-event-order-' + uuid.uuid4().hex[:10])
        bridge = bridge_fixture()
        bridge.event_sequence = 0
        bridge.generations = {'%0': 1}
        bridge.tmux = backend
        def until(check):
            deadline = time.monotonic() + 5
            while not check():
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.01)
        try:
            backend.run('new-session', '-d', '-s', 'ordered', '-x', '100', '-y', '24',
                        "env PS1='ORDER> ' /bin/bash --noprofile --norc -i")
            until(lambda: 'ORDER>' in backend.read('%0', 20))
            backend.install_human_binding(pathlib.Path('/tmp/unused-stb-test.sock'),
                                         pathlib.Path(__file__).resolve().parents[2] / 'bridge/local_bridge.py')
            args = shlex.split(backend.get_root_ctrl_c_binding())
            key_command = args[args.index('C-c') + 1:]
            # Delay state processing while tmux queues BOTH output and key.
            # This is the old race, not just a key after a refreshed job.
            with bridge.lock:
                first = bridge.terminal_submit('%0', 1, "printf 'DONE\\n'", 1000)
                job = bridge.jobs[first['job_id']]
                until(lambda: 'DONE' in backend.read('%0', 20)
                      and backend.read('%0', 20).rstrip().endswith('ORDER>'))
                backend.run(*key_command)
                self.assertEqual(job['execution_phase'], 'EXECUTING')
            until(lambda: bridge.event_sequence == 1)
            self.assertEqual(bridge.leases['%0']['state'], 'ACTIVE')
            self.assertEqual(job['completion_confidence'], 'ordered_prompt_returned')
            second = bridge.terminal_submit('%0', 1, 'sleep 60', 60000)
            until(lambda: backend.state('%0')['current_command'] == 'sleep')
            with bridge.lock:
                backend.run(*key_command)
                until(lambda: backend.state('%0')['current_command'] == 'bash')
            until(lambda: bridge.leases['%0']['state'] == 'REVOKED')
            self.assertEqual(bridge.jobs[second['job_id']]['execution_phase'], 'INTERRUPTED')
            until(lambda: backend.state('%0')['current_command'] == 'bash')
            renewed = bridge.dispatch('terminal_submit', dict(
                pane='%0', generation=1, text='sleep 60', expected_duration_ms=60000))
            self.assertEqual(renewed['generation'], 2)
            until(lambda: backend.state('%0')['current_command'] == 'sleep')
            backend.run(*key_command)
            until(lambda: bridge.leases['%0']['state'] == 'REVOKED')
            self.assertEqual(bridge.leases['%0']['generation'], 2)
            until(lambda: backend.state('%0')['current_command'] == 'bash')
            # A dead observer must never prevent the physical key reaching
            # an unrelated human command, even if its client option is stale.
            stream = bridge.ensure_terminal_stream('%0')
            stream.process.terminate()
            stream.process.wait(timeout=2)
            until(lambda: stream.closed.is_set())
            backend.submit('%0', 'sleep 60')
            until(lambda: backend.state('%0')['current_command'] == 'sleep')
            backend.run(*key_command)
            until(lambda: backend.state('%0')['current_command'] == 'bash')
        finally:
            bridge.close_terminal_streams()
            backend.run('kill-server', check=False)
