"""History viewing must not consume application text, Enter or Ctrl+C."""
import shutil
import pathlib
import time
import unittest
import uuid

from bridge.tmux.backend import TmuxBackend


class ScrollbackInputTest(unittest.TestCase):
    def test_literal_input_preserves_view_and_user_buffer(self):
        if not shutil.which('tmux'):
            self.skipTest('host tmux required')
        backend = TmuxBackend('stb-scroll-' + uuid.uuid4().hex[:12])

        def until(check):
            deadline = time.monotonic() + 5
            while not check():
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.01)
        try:
            backend.run('new-session', '-d', '-s', 'scroll', '-x', '130',
                        "env PS1='SCROLL> ' /bin/bash --noprofile --norc -i")
            until(lambda: backend.read('%0', 100).rstrip().endswith('SCROLL>'))
            backend.run('set-buffer', '-b', 'user-history', 'KEEP_USER_BUFFER')
            backend.run('copy-mode', '-t', '%0')
            before = backend.run('display-message', '-p', '-t', '%0',
                                 '#{scroll_position}').stdout
            backend.send_text('%0', "printf '%s\\n' 'literal \"quotes\" $HOME \\ path'")
            backend.send_key('%0', 'Enter')
            until(lambda: 'literal "quotes" $HOME \\ path' in
                  backend.read('%0', 100).splitlines())
            self.assertEqual(backend.run('display-message', '-p', '-t', '%0',
                                        '#{pane_in_mode}').stdout.strip(), '1')
            self.assertEqual(backend.run('display-message', '-p', '-t', '%0',
                                        '#{scroll_position}').stdout, before)
            self.assertEqual(backend.run('show-buffer', '-b', 'user-history').stdout,
                             'KEEP_USER_BUFFER')
            buffers = backend.run('list-buffers', '-F', '#{buffer_name}').stdout
            self.assertNotIn('stb-input-', buffers)
            backend.send_text('%0', '')  # Empty interaction is a valid no-op.
            original = backend.get_root_ctrl_c_binding()
            copies = {table: backend.run('list-keys', '-T', table, 'C-c',
                        check=False).stdout for table in ('copy-mode', 'copy-mode-vi')}
            backend.install_human_binding(pathlib.Path('/tmp/unused-scroll-event.sock'),
                pathlib.Path(__file__).resolve().parents[2] / 'bridge/local_bridge.py')
            # Reinstallation must not replace the original snapshots.
            backend.install_human_binding(pathlib.Path('/tmp/unused-scroll-event.sock'),
                pathlib.Path(__file__).resolve().parents[2] / 'bridge/local_bridge.py')
            backend.restore_root_ctrl_c_binding(original)
            for table, binding in copies.items():
                self.assertEqual(backend.run('list-keys', '-T', table, 'C-c',
                                            check=False).stdout, binding)
        finally:
            backend.run('kill-server', check=False)
