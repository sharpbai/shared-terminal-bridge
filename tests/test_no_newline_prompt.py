import unittest

from bridge.prompt_detection import returned_prompt
from tests import test_terminal_event_order as ordered


class NoNewlinePromptTest(unittest.TestCase):
    setUp = ordered.TerminalEventOrderTest.setUp
    emit = ordered.TerminalEventOrderTest.emit

    def test_ordered_boundary_completes_without_newline(self):
        self.emit('terminal_output', content='wait_woken\x1b[?2004hprompt$ ')
        self.assertEqual(self.job['state'], 'COMPLETED')
        self.assertEqual(self.job['returned_prompt'], 'prompt$')

    def test_textual_suffix_and_partial_prompt_do_not_complete(self):
        for content in ('wait_wokenprompt$ ', 'wait_woken\x1b[?2004hpro',
                        'wait_woken\x1b[?2004hprompt$ extra',
                        'wait_woken\x1b[?2004hother$ '):
            self.assertIsNone(returned_prompt('prompt$', content), repr(content))

    def test_empty_history_recovers_contaminated_baseline_at_boundary(self):
        prompt = 'root@host:/work#'
        self.job['baseline_prompt'] = 'wait_woken' + prompt
        self.emit('terminal_output', content='data\r\n\x1b[?2004h' + prompt + ' ')
        self.assertEqual(self.job['state'], 'COMPLETED')
        self.assertEqual(self.bridge.pane_prompts['%0']['prompt'], prompt)
        self.bridge.jobs.clear()
        result = self.bridge._create_job('%0', 1, 'next', 1000, 'normal',
            'wait_woken' + prompt, self.job.get('baseline_pane_command'))
        self.assertEqual(result['baseline_prompt'], prompt)

    def test_contaminated_recovery_requires_boundary_and_full_identity(self):
        prompt = 'root@host:/work#'
        self.assertIsNone(returned_prompt('noise' + prompt, 'output' + prompt))
        self.assertIsNone(returned_prompt('noiseprompt$', '\x1b[?2004hprompt$'))
        self.assertIsNone(returned_prompt('noise' + prompt, '\x1b[?2004hroot@other:/work#'))
