import shutil
import time
import unittest
import uuid
from bridge.tmux.backend import TmuxBackend
from tests.context_support import bridge_fixture


class ZshArrowHostTest(unittest.TestCase):
    def test_real_zsh_directory_and_git_decoration(self):
        if not shutil.which('zsh') or not shutil.which('tmux'):
            self.skipTest('host zsh/tmux required')
        backend = TmuxBackend('stb-zsh-' + uuid.uuid4().hex[:10])
        bridge = bridge_fixture()
        bridge.tmux = backend
        try:
            backend.run('new-session', '-d', '-s', 'arrow', '-x', '100',
                        "env PS1='(kev-qwen35) ➜ %~ ' zsh -f")
            end = time.monotonic() + 5
            while '(kev-qwen35) ➜' not in backend.read('%0', 30):
                self.assertLess(time.monotonic(), end)
                time.sleep(.01)
            result = bridge.dispatch('terminal_run', dict(pane='%0', request_id='arrow',
                text="cd /tmp; PS1='(kev-qwen35) ➜ %~ git:(main) ✗ '; printf 'BUILD_EXIT=0\\n'",
                wait_ms=3000))
            self.assertEqual(result['state'], 'COMPLETED', result)
            result = bridge.dispatch('terminal_run', dict(pane='%0', request_id='next',
                text="printf 'NEXT\\n'", wait_ms=3000))
            self.assertEqual(result['state'], 'COMPLETED', result)
        finally:
            bridge.close_terminal_streams()
            backend.run('kill-server', check=False)
