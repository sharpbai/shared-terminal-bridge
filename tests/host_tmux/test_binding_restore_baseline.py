#!/usr/bin/env python3
"""Regression baseline for tmux C-c binding restoration."""

import pathlib
import shutil
import subprocess
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
POC_PATH = PROJECT_ROOT / "poc" / "binding_restore.py"


class BindingRestoreBaselineTest(unittest.TestCase):
    def test_binding_lifecycle(self):
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
        self.assertIn(
            "PASS: custom C-c binding was restored exactly.",
            completed.stdout,
        )
        self.assertIn(
            "PASS: an originally absent binding was restored as absent.",
            completed.stdout,
        )
        self.assertIn(
            "PASS: restore without a snapshot failed closed.",
            completed.stdout,
        )


if __name__ == "__main__":
    unittest.main()
