#!/usr/bin/env python3
import pathlib
import sys
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from mcp_server.server import MinimalMCPServer  # noqa: E402


class FakeBridge:
    def call(self, method, params):
        if method == "bridge_info":
            return {"ok": True, "result": {"api_version": 9, "version": "0.15.0"}}
        return {"ok": True, "result": {}}


class ExclusiveModeContractTest(unittest.TestCase):
    def test_modern_discovery_declares_rdc_exclusive_mode(self):
        instructions = MinimalMCPServer(FakeBridge()).discover()["instructions"]
        self.assertIn("STB-RDC exclusive-mode contract", instructions)
        self.assertIn("transport/bootstrap only", instructions)
        self.assertIn("one-shot bypass", instructions)
        self.assertIn("never bypass Human Override", instructions)

    def test_legacy_initialize_declares_rdc_exclusive_mode(self):
        server = MinimalMCPServer(FakeBridge())
        result = server.initialize({"protocolVersion": "2025-11-25"})
        instructions = result["instructions"]
        self.assertIn("transport/bootstrap only", instructions)
        self.assertIn("human bypass approval", instructions)


if __name__ == "__main__":
    unittest.main()
