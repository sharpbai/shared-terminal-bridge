"""Keep code and current documentation on one release/API baseline."""

import pathlib
import re
import unittest

from bridge.config import BRIDGE_API_VERSION, BRIDGE_VERSION
from mcp_server import config as mcp_config


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]


class VersionConsistencyTest(unittest.TestCase):
    def _read(self, relative_path):
        return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")

    def test_mcp_server_uses_bridge_release_version(self):
        self.assertEqual(mcp_config.SERVER_INFO["version"], BRIDGE_VERSION)

    def test_latest_changelog_heading_matches_release_version(self):
        changelog = self._read("CHANGELOG.md")
        first_heading = re.search(r"^## v([^ ]+)", changelog, re.MULTILINE)
        self.assertIsNotNone(first_heading)
        self.assertEqual(first_heading.group(1), BRIDGE_VERSION)

    def test_current_documents_publish_release_and_api_versions(self):
        expected_pairs = {
            "README.md": f"v{BRIDGE_VERSION} / Bridge API v{BRIDGE_API_VERSION}",
            "docs/roadmap.md": f"STB v{BRIDGE_VERSION}",
            "docs/reference/stb-rdc-exclusive-mode.md": (
                f"STB v{BRIDGE_VERSION} / Bridge API v{BRIDGE_API_VERSION}"
            ),
        }
        for path, expected in expected_pairs.items():
            with self.subTest(path=path):
                self.assertIn(expected, self._read(path))

    def test_highest_feature_gate_matches_bridge_api(self):
        gates = [
            int(name.removeprefix("REQUIRES_BRIDGE_V"))
            for name in vars(mcp_config)
            if name.startswith("REQUIRES_BRIDGE_V")
        ]
        self.assertEqual(max(gates), BRIDGE_API_VERSION)


if __name__ == "__main__":
    unittest.main()
