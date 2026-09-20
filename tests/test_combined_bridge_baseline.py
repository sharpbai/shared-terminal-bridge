#!/usr/bin/env python3
"""Regression baseline for the combined local Bridge."""

import json
import pathlib
import shutil
import subprocess
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE_PATH = (
    PROJECT_ROOT / "tests" / "baselines" / "combined_bridge_v1.json"
)
POC_PATH = PROJECT_ROOT / "poc" / "combined_bridge.py"


class CombinedBridgeBaselineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("tmux") is None:
            raise unittest.SkipTest("tmux is not installed")
        cls.baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

    def test_combined_bridge_matches_v1_baseline(self):
        completed = subprocess.run(
            [sys.executable, str(POC_PATH), "--json"],
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
        result = json.loads(completed.stdout)

        self.assertEqual(
            result["schema_version"],
            self.baseline["schema_version"],
        )
        self.assertEqual(result["suite"], self.baseline["suite"])
        self.assertTrue(result["passed"])

        expected_checks = set(self.baseline["required_checks"])
        self.assertEqual(set(result["checks"]), expected_checks)
        for check in expected_checks:
            self.assertTrue(result["checks"][check], msg=check)

        self.assertEqual(
            result["lease_state"],
            self.baseline["expected_lease_state"],
        )
        self.assertEqual(
            result["stale_error"],
            self.baseline["expected_stale_error"],
        )
        self.assertTrue(
            set(self.baseline["required_audit_actions"]).issubset(
                result["audit_actions"]
            )
        )


if __name__ == "__main__":
    unittest.main()
