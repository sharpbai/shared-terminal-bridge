"""Control-mode quoting reaches an isolated target shell without expansion."""

import shutil
import time
import unittest
import uuid

from bridge.tmux.backend import TmuxBackend
from tests.context_support import bridge_fixture


class CommandQuotingHostTest(unittest.TestCase):
    def test_special_characters_survive_control_stream(self):
        if not shutil.which("tmux"):
            self.skipTest("host tmux required")
        backend = TmuxBackend("stb-quote-" + uuid.uuid4().hex[:12])
        core = bridge_fixture()
        core.tmux = backend
        try:
            backend.run("new-session", "-d", "-s", "quote", "-x", "200",
                        "env PS1='STB:quote # ' /bin/bash --noprofile --norc -i")
            deadline = time.monotonic() + 5
            while not backend.read("%0", 200).rstrip().endswith("#"):
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.05)
            text = '''printf '%s\\n' '中文 $1 $2 $(false) `false` C:\\temp\\x' "double ' quote"'''
            result = core.dispatch("terminal_submit", dict(
                pane="%0", generation=1, text=text, request_id="quote-1"))
            waited = core.terminal_wait_job(result["job_id"], wait_ms=8000)
            self.assertEqual(waited["state"], "COMPLETED", waited)
            output = waited["output_excerpt"]["content"]
            self.assertIn("中文 $1 $2 $(false) `false` C:\\temp\\x", output.splitlines())
            self.assertIn("double ' quote", output.splitlines())
            self.assertEqual(core.dispatch("terminal_submit", dict(
                pane="%0", generation=1, text=text, request_id="quote-1")), result)
        finally:
            core.close_terminal_streams()
            backend.run("kill-server", check=False)
