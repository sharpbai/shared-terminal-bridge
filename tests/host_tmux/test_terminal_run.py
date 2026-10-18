"""Composite run completes/wakes on a real ordered Human Event, no replay."""
import pathlib
import shlex
import shutil
import threading
import time
import unittest
import uuid

from bridge.tmux.backend import TmuxBackend
from tests.context_support import bridge_fixture


class TerminalRunHostTest(unittest.TestCase):
    def test_run_completion_interrupt_replay_and_new_call(self):
        if not shutil.which("tmux"):
            self.skipTest("host tmux required")
        backend = TmuxBackend("stb-run-test-" + uuid.uuid4().hex[:12])
        bridge = bridge_fixture()
        bridge.tmux = backend
        bridge.leases = {}
        bridge.generations = {}
        bridge.event_sequence = 0
        task = None
        def until(check):
            deadline = time.monotonic() + 5
            while not check():
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.01)
        try:
            backend.run("new-session", "-d", "-s", "run", "-x", "150",
                        "env PS1='STBRUN> ' /bin/bash --noprofile --norc -i")
            until(lambda: backend.read("%0", 100).rstrip().endswith("STBRUN>"))
            backend.install_human_binding(pathlib.Path("/tmp/unused-stb-run-test.sock"),
                pathlib.Path(__file__).resolve().parents[2] / "bridge/local_bridge.py")
            args = dict(pane="%0", request_id="quick", text="printf 'RUN_OK\\n'", wait_ms=5000)
            result = bridge.dispatch("terminal_run", args)
            self.assertEqual(result["state"], "COMPLETED", result)
            self.assertIn("RUN_OK", result["output_excerpt"]["content"].splitlines())
            slow = dict(args, request_id="slow", text="sleep 60")
            results, errors = [], []
            def call():
                try:
                    results.append(bridge.dispatch("terminal_run", slow))
                except Exception as error:
                    errors.append(error)
            task = threading.Thread(target=call)
            task.start()
            until(lambda: backend.state("%0")["current_command"] == "sleep")
            binding = shlex.split(backend.get_root_ctrl_c_binding())
            backend.run(*binding[binding.index("C-c") + 1:])
            task.join(3)
            self.assertFalse(task.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(results[0]["state"], "INTERRUPTED_BY_HUMAN")
            generation = bridge.generations["%0"]
            replay = bridge.dispatch("terminal_run", slow)
            self.assertEqual(replay["job_id"], results[0]["job_id"])
            self.assertEqual(replay["state"], "INTERRUPTED_BY_HUMAN")
            self.assertEqual(bridge.generations["%0"], generation)
            until(lambda: backend.state("%0")["current_command"] == "bash")
            fresh = bridge.dispatch("terminal_run", dict(args, request_id="fresh"))
            self.assertEqual(fresh["state"], "COMPLETED", fresh)
            self.assertEqual(fresh["generation"], generation + 1)
        finally:
            bridge.close_terminal_streams()
            backend.run("kill-server", check=False)
            if task:
                task.join(6)
