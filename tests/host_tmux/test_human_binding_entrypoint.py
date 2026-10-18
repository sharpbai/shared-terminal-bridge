"""Execute the command actually stored in a tmux binding and receive its event."""

import json
import pathlib
import shlex
import shutil
import socket
import tempfile
import unittest
import uuid
import time

from bridge.tmux.backend import TmuxBackend
from tests.context_support import bridge_fixture


class HumanBindingEntrypointHostTest(unittest.TestCase):
    def test_installed_emitter_sends_event_and_revokes_lease(self):
        if shutil.which('tmux') is None:
            self.skipTest('tmux is not installed')
        backend = TmuxBackend('stb-binding-entry-' + uuid.uuid4().hex[:10])
        try:
            backend.run('new-session', '-d', '-s', 'binding-test')
            with tempfile.TemporaryDirectory(prefix='stb-event-', dir='/tmp') as folder:
                with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as listener:
                    path = pathlib.Path(folder) / 'event.sock'
                    listener.bind(str(path))
                    listener.settimeout(5)
                    bridge = bridge_fixture()
                    bridge.tmux = backend
                    bridge.event_socket = path
                    bridge.event_sequence = 0
                    bridge.human_binding_installed = False
                    bridge.binding_snapshot_taken = False
                    bridge.install_human_binding()
                    binding = backend.get_root_ctrl_c_binding()
                    self.assertIn('bridge/local_bridge.py', binding)
                    self.assertNotIn('sessions/service.py', binding)
                    # Invoke the stored emitter only on this isolated server.
                    # send-keys intentionally bypasses physical client bindings.
                    backend.submit('%0', 'sleep 60')
                    deadline = time.monotonic() + 5
                    while backend.state('%0')['current_command'] != 'sleep':
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(.05)
                    bridge.jobs['test'] = dict(pane='%0', generation=1,
                                               state='RUNNING', baseline_prompt='unlikely prompt$')
                    arguments = shlex.split(binding)
                    backend.run(*arguments[arguments.index('C-c') + 1:])
                    event = json.loads(listener.recv(65535))
                    self.assertEqual(event['type'], 'human_interrupt')
                    self.assertEqual(event['pane'], '%0')
                    self.assertIn('pre_interrupt_content', event)
                    bridge.handle_human_event(event)
                    self.assertEqual(bridge.leases['%0']['state'], 'REVOKED')
                    self.assertEqual(bridge.leases['%0']['event_seq'], 1)
                    self.assertEqual(bridge.jobs['test']['execution_phase'], 'INTERRUPTED')
                    bridge.leases['%0']['state'] = 'ACTIVE'
                    bridge.jobs.clear()
                    backend.run(*arguments[arguments.index('C-c') + 1:])
                    bridge.handle_human_event(json.loads(listener.recv(65535)))
                    self.assertEqual(bridge.leases['%0']['state'], 'ACTIVE')
        finally:
            backend.run('kill-server', check=False)
