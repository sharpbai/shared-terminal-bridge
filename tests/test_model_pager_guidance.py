"""Pager avoidance must be visible in initial MCP discovery."""
import unittest

from mcp_server.runtime.protocol import INSTRUCTIONS


class ModelPagerGuidanceTest(unittest.TestCase):
    def test_initial_discovery_disables_pagers_without_global_changes(self):
        for hint in ('git --no-pager', 'GIT_PAGER=cat', 'systemctl --no-pager',
                     '(END)', 'do not change global'):
            self.assertIn(hint, INSTRUCTIONS)
