import shutil
import time
import unittest
import uuid
from bridge.tmux.backend import TmuxBackend
from tests.context_support import bridge_fixture


class WrappedBaselineTest(unittest.TestCase):
    def test_soft_wrap_and_no_newline_output_preserve_full_identity(self):
        if not shutil.which('tmux'):
            self.skipTest('host tmux required')
        backend = TmuxBackend('stb-wrap-' + uuid.uuid4().hex[:10])
        bridge = bridge_fixture()
        bridge.tmux = backend
        try:
            shell = shutil.which('bash') or '/bin/bash'
            backend.run('new-session', '-d', '-s', 'wrap', '-x', '35', '-y', '24',
                "env PS1='root@evoxt-us-east-9019:~# ' " + shell + ' --noprofile --norc -i')
            def until(check):
                end = time.monotonic() + 5
                while not check():
                    self.assertLess(time.monotonic(), end)
                    time.sleep(.01)
            until(lambda: backend.read('%0', 30).rstrip().endswith('#'))
            backend.submit('%0', "printf '012345678901234567890123456789'")
            until(lambda: '012345678901234567890123456789root@evoxt-us-east-9019:~#'
                  in backend.read_logical_lines('%0', 30))
            # Simulate a truncated baseline cached by an older release.
            bridge.pane_prompts['%0'] = dict(prompt='-9019:~#', pane_command='bash')
            result = bridge.dispatch('terminal_run', dict(pane='%0', request_id='wrapped',
                text="printf 'DONE\\n'", wait_ms=3000))
            self.assertEqual(result['state'], 'COMPLETED', result)
            self.assertEqual(bridge.jobs[result['job_id']]['returned_prompt'],
                             'root@evoxt-us-east-9019:~#')
            backend.submit('%0', "printf 'REAL_LINE_1\\nREAL_LINE_2\\n'")
            until(lambda: 'REAL_LINE_1\nREAL_LINE_2' in backend.read_logical_lines('%0', 30))
        finally:
            bridge.close_terminal_streams()
            backend.run('kill-server', check=False)
