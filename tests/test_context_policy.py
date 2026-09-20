#!/usr/bin/env python3
"""Regression tests for deterministic AI Context Policy admission control."""

import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from bridge.context_policy import AIContextPolicy  # noqa: E402


class AIContextPolicyTest(unittest.TestCase):
    def test_delta_does_not_repeat_previous_output(self):
        first = "prompt$ cmd\nline one\nline two"
        second = first + "\nline three"
        result = AIContextPolicy.apply(first, second)
        self.assertEqual(result["content"], "line three")
        self.assertEqual(result["raw_delta_lines"], 1)

    def test_noise_repeat_and_line_budget_are_deterministic(self):
        current = "\n".join(
            [
                "\x1b[31mred\x1b[0m",
                "same",
                "same",
                "same",
                "__STB_STEP_START__block:1",
                "tail-1",
                "tail-2",
                "tail-3",
            ]
        )
        result = AIContextPolicy.apply("", current, max_lines=7)
        self.assertNotIn("\x1b", result["content"])
        self.assertIn("__STB_STEP_START__block:1", result["content"])
        self.assertIn("[repeated 2 more times]", result["content"])
        self.assertEqual(result["dropped_markers"], 0)

    def test_byte_budget_preserves_recent_output(self):
        result = AIContextPolicy.apply("", "old\n" + "x" * 200 + "\nLATEST", max_bytes=32)
        self.assertIn("LATEST", result["content"])
        self.assertGreater(result["omitted_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
