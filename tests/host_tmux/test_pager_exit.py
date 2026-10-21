"""End-to-end automatic local pager exit, no model key operations."""
import shutil
import time
import unittest
import uuid
import subprocess
from unittest.mock import patch

from bridge.tmux.backend import TmuxBackend
from tests.context_support import bridge_fixture


class PagerExitHostTest(unittest.TestCase):
    def test_less_exit_and_next_command(self):
        if not shutil.which('tmux') or not shutil.which('less'):
            self.skipTest('host tmux/less required')
        backend = TmuxBackend('stb-pager-' + uuid.uuid4().hex[:10])
        bridge = bridge_fixture()
        bridge.tmux = backend
        try:
            backend.run('new-session', '-d', '-s', 'pager', '-x', '100', '-y', '24',
                        "env PS1='PAGER> ' /bin/bash --noprofile --norc -i")
            deadline = time.monotonic() + 5
            while not backend.read('%0', 30).rstrip().endswith('PAGER>'):
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.01)
            result = bridge.dispatch('terminal_run', dict(pane='%0', request_id='pager',
                text="printf 'PAGER_DATA\\n' | env LESS= less -+F -+X", wait_ms=5000))
            self.assertEqual(result['state'], 'COMPLETED', result)
            # Real tmux/less output with SSH process evidence replayed locally:
            # no dependency on external hosts, credentials or network probes.
            actual_run = subprocess.run
            def remote_process_evidence(args, **kwargs):
                if args[0] == 'ps':
                    return subprocess.CompletedProcess(args, 0, '12 12 ssh\n', '')
                return actual_run(args, **kwargs)
            with patch('bridge.tmux.pager.subprocess.run', side_effect=remote_process_evidence):
                result = bridge.dispatch('terminal_run', dict(pane='%0', request_id='remote',
                    text="git() { printf 'REMOTE_DATA\\n' | env LESS= less -+F -+X; }; git diff", wait_ms=5000))
            self.assertEqual(result['state'], 'COMPLETED', result)
            self.assertTrue(bridge.jobs[result['job_id']].get('pager_exit_requested'))
            with patch('bridge.tmux.pager.subprocess.run', side_effect=remote_process_evidence):
                result = bridge.dispatch('terminal_run', dict(pane='%0', request_id='remote-status',
                    text="systemctl() { printf 'UNIT_DATA\\n' | env LESS= less -+F -X -P 'lines 1-1/1 (END)'; }; systemctl cat test.service", wait_ms=5000))
            self.assertEqual(result['state'], 'COMPLETED', result)
            self.assertTrue(bridge.jobs[result['job_id']].get('pager_exit_requested'))
            job = bridge.jobs[result['job_id']]
            self.assertTrue(job.get('pager_exit_requested'))
            self.assertFalse(job['event_stream_pending'])
            result = bridge.dispatch('terminal_run', dict(pane='%0', request_id='two-pagers',
                text="printf 'ONE\\n' | env LESS= less -+F -+X; printf 'TWO\\n' | env LESS= less -+F -+X", wait_ms=5000))
            self.assertEqual(result['state'], 'COMPLETED', result)
            self.assertEqual(bridge.jobs[result['job_id']]['pager_exit_count'], 2)
            self.assertEqual(bridge.leases['%0']['state'], 'ACTIVE')
            result = bridge.dispatch('terminal_run', dict(pane='%0', request_id='next',
                text="printf 'NEXT\\n'", wait_ms=3000))
            self.assertEqual(result['state'], 'COMPLETED', result)
        finally:
            bridge.close_terminal_streams()
            backend.run('kill-server', check=False)
