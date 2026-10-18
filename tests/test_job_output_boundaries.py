"""Job excerpts exclude earlier history and commands after a returned prompt."""

import unittest
from bridge.context_policy import AIContextPolicy


class JobOutputTest(unittest.TestCase):
    def test_wrapped_echo_and_dynamic_prompt_boundaries(self):
        baseline = "old history\nPassword:\nSharpbaiPro:Downloads #\n\n"
        current = "old history\nPassword:\nSharpbaiPro:Downloads # cd /project && pri\nntf done\ndone\nSharpbaiPro:IT网管 (master*) #\nSharpbaiPro:IT网管 (master*) # next command\nnext output"
        result = AIContextPolicy.job_output(baseline, current, "cd /project && printf done")
        self.assertEqual(result["content"], "done\nSharpbaiPro:IT网管 (master*) #")

    def test_changed_last_row_without_echo_excludes_stable_history(self):
        result = AIContextPolicy.job_output("old\nprompt$\n\n", "old\noutput\nprompt$", "not echoed")
        self.assertNotIn("old", result["content"])

