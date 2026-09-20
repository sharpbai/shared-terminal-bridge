#!/usr/bin/env python3
"""Regression baseline for MCP-created and stb-managed sessions."""

import pathlib
import shutil
import subprocess
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
POC_PATH = PROJECT_ROOT / "poc" / "managed_session_end_to_end.py"


class ManagedSessionBaselineTest(unittest.TestCase):
    def test_managed_session(self):
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
            "PASS: MCP created an authorized managed tmux session.",
            completed.stdout,
        )
        self.assertIn(
            "PASS: stb managed it without touching an ordinary session.",
            completed.stdout,
        )


if __name__ == "__main__":
    unittest.main()
