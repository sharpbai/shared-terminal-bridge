import unittest
from bridge.prompt_detection import returned_prompt
from tests import test_terminal_event_order as ordered


class ZshArrowPromptTest(unittest.TestCase):
    setUp = ordered.TerminalEventOrderTest.setUp
    emit = ordered.TerminalEventOrderTest.emit

    def test_cwd_and_git_change_finishes_ordered_job(self):
        self.job['baseline_prompt'] = '(kev-qwen35) ➜  ~'
        self.emit('terminal_output', content='BUILD_EXIT=0\r\n'
            '(kev-qwen35) ➜  causal-conv1d-sm75 git:(v1.5.3.post2) ✗\x1b[?2004h')
        self.assertEqual(self.job['state'], 'COMPLETED')

    def test_reject_output_environment_change_and_unsubmitted_input(self):
        baseline = '(kev-qwen35) ➜ ~'
        for raw in ('(kev-qwen35) ➜ repo',
                    '(other) ➜ repo\x1b[?2004h',
                    '(kev-qwen35) ➜ repo ls -la\x1b[?2004h',
                    '(kev-qwen35) ➜ repo\x1b[?2004h\x1b[?2004l',
                    'log ➜ repo\x1b[?2004h'):
            self.assertIsNone(returned_prompt(baseline, raw), raw)

    def test_newline_and_branch_redraw(self):
        baseline = '(kev-qwen35) ➜ ~'
        raw = ('(kev-qwen35) ➜ repo\x1b[?2004h\r\r'
               '(kev-qwen35) ➜ repo git:(main) ✗')
        self.assertEqual(returned_prompt(baseline, raw), '(kev-qwen35) ➜ repo git:(main) ✗')
