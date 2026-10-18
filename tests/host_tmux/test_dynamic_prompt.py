"""Real tmux prompt changes must complete without target-shell instrumentation."""

import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid

from bridge.tmux.backend import TmuxBackend
from tests.context_support import bridge_fixture


class DynamicPromptHostTest(unittest.TestCase):
    def test_cd_returns_changed_prompt_and_wakes_wait(self):
        if shutil.which("tmux") is None:
            self.skipTest("tmux is not installed")
        socket = "stb-prompt-test-" + uuid.uuid4().hex[:12]
        backend = TmuxBackend(socket)
        try:
            with tempfile.TemporaryDirectory(prefix="stb-prompt-") as folder:
                destination = pathlib.Path(folder) / "中文目录"
                destination.mkdir()
                # Test fixture only: a clean shell with a known dynamic cwd
                # prompt. Production code never sets PS1 or injects markers.
                backend.run("new-session", "-d", "-s", "prompt-test", "-x", "45", "-y", "24",
                            "env PS1='STB:\\W # ' /bin/bash --noprofile --norc -i")
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    content = backend.read("%0", 200)
                    if [line for line in content.splitlines() if line.strip()] and content.rstrip().endswith("#"):
                        break
                    time.sleep(0.05)
                else:
                    self.fail("test shell prompt not ready")
                bridge = bridge_fixture()
                bridge.tmux = backend
                command = "cd '" + str(destination) + "' && printf 'COMMAND_DONE\\n'"
                submitted = bridge.terminal_submit("%0", 1, command, 1000, "normal")
                job_id = submitted["job_id"]
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    result = bridge.terminal_job_status(job_id)
                    if result["state"] == "COMPLETED":
                        break
                    time.sleep(0.1)
                self.assertEqual(result["state"], "COMPLETED", result)
                waited = bridge.terminal_wait_job(job_id, wait_ms=100)
                self.assertEqual(waited["state"], "COMPLETED")
                self.assertIn("COMMAND_DONE", waited["output_excerpt"]["content"])
                self.assertIn("STB:中文目录 #", waited["output_excerpt"]["content"])
                self.assertNotIn(command, waited["output_excerpt"]["content"])
        finally:
            if 'bridge' in locals():
                bridge.close_terminal_streams()
            backend.run("kill-server", check=False)
