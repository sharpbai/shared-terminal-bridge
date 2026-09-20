#!/usr/bin/env python3
"""Regression baseline for MCP observation and leased actions."""

import pathlib
import shutil
import subprocess
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
POC_PATH = PROJECT_ROOT / "poc" / "mcp_end_to_end.py"


class MCPEndToEndBaselineTest(unittest.TestCase):
    def test_mcp_end_to_end(self):
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
            "PASS: MCP stdio reached the authorized tmux pane read-only.",
            completed.stdout,
        )
        self.assertIn(
            "PASS: Action tools were absent and rejected by default.",
            completed.stdout,
        )
        self.assertIn(
            "PASS: explicitly enabled MCP actions honored the lease.",
            completed.stdout,
        )
        self.assertIn(
            "PASS: Human Override revoked and blocked stale MCP writes.",
            completed.stdout,
        )


if __name__ == "__main__":
    unittest.main()
