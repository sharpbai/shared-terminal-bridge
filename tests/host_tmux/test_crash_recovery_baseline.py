#!/usr/bin/env python3
"""Regression baseline for fail-closed daemon crash recovery."""

import pathlib
import shutil
import subprocess
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
POC_PATH = PROJECT_ROOT / "poc" / "crash_recovery.py"


class CrashRecoveryBaselineTest(unittest.TestCase):
    def test_crash_recovery(self):
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
            "PASS: daemon crash did not revive an ACTIVE lease.",
            "PASS: stale generation was denied after restart.",
            "PASS: original binding snapshot survived and restored.",
            "PASS: generation remained monotonic and state stayed 0600.",
        ):
            self.assertIn(message, completed.stdout)


if __name__ == "__main__":
    unittest.main()
