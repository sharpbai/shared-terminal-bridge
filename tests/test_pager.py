import subprocess
import unittest
from unittest.mock import patch
from bridge.tmux.pager import at_pager_end, update_cycle


class PagerTest(unittest.TestCase):
    def test_cycle_requires_exit_before_reentry_and_handles_split_bytes(self):
        job = {}
        self.assertEqual(update_cycle(job, '\x1b[?104'), 0)
        self.assertEqual(update_cycle(job, '9h(END)'), 1)
        self.assertEqual(update_cycle(job, '(END)\x1b[?1049h'), 1)
        self.assertEqual(update_cycle(job, '\x1b[?1049l\x1b[?1049h(END)'), 2)
    @patch('bridge.tmux.pager.subprocess.run')
    def test_requires_foreground_pager_and_end(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, '12 12 /usr/bin/less\n')
        self.assertTrue(at_pager_end(['(END)'], '/dev/ttys001'))
        self.assertFalse(at_pager_end(['text'], '/dev/ttys001'))
        for processes in ('12 13 less\n', '12 12 vim\n', '12 12 ssh\n',
                          '12 12 less\n12 12 ssh\n'):
            run.return_value.stdout = processes
            self.assertFalse(at_pager_end(['(END)'], '/dev/ttys001'))

    @patch('bridge.tmux.pager.subprocess.run', side_effect=PermissionError)
    def test_missing_process_evidence_does_not_send_keys(self, run):
        self.assertFalse(at_pager_end(['(END)'], '/dev/ttys001'))

    @patch('bridge.tmux.pager.subprocess.run')
    def test_remote_requires_all_screen_and_command_evidence(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, '12 12 ssh\n')
        raw = '\x1b[?1049hdata\r\n\x1b[7m(END)\x1b[m'
        self.assertTrue(at_pager_end(['data', '(END)'], 'tty', raw, 'git diff --check'))
        raw_status = '\x1b[?1h\x1b=\rdata\r\n\x1b[7mlines 1-13/13 (END)\x1b[27m\x1b[K'
        self.assertTrue(at_pager_end(['lines 1-13/13 (END)'], 'tty', raw_status,
                                    'systemctl cat gw-stat-collect.service'))
        self.assertFalse(at_pager_end(['log says (END)'], 'tty', raw_status,
                                     'systemctl cat gw-stat-collect.service'))
        for command, screen in [('echo hello', raw), ('git diff', '(END)'),
                                ('git diff', raw + '\x1b[?1049l'),
                                ('PAGER=vim git diff', raw)]:
            self.assertFalse(at_pager_end(['(END)'], 'tty', screen, command))
