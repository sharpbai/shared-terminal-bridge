#!/usr/bin/env python3
"""Regression baseline for daemon singleton and tmux server identity."""

import pathlib
import shutil
import subprocess
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
POC_PATH = PROJECT_ROOT / "poc" / "instance_identity.py"


class InstanceIdentityBaselineTest(unittest.TestCase):
    def test_instance_and_server_identity(self):
        if shutil.which("tmux") is None:
            self.skipTest("tmux is not installed")
        completed = subprocess.run(
            [sys.executable, str(POC_PATH)],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stderr={completed.stderr}\nstdout={completed.stdout}",
        )
        for message in (
            "PASS: a second daemon could not acquire the same state.",
            "PASS: rebuilt tmux server was rejected despite pane ID reuse.",
            "PASS: old lease state was not applied to the new server.",
        ):
            self.assertIn(message, completed.stdout)


if __name__ == "__main__":
    unittest.main()
