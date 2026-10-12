"""Host identity inspection must never disclose model arguments or secrets."""

import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from mcp_server.identity_diagnostics import IdentityDiagnostics, metadata_shape


class IdentityDiagnosticsTest(unittest.TestCase):
    def test_shapes_redact_non_identity_values(self):
        shape = metadata_shape({"token": "secret", "threadId": "01a123fd-cd1a-7fa2-a8f0-ce7f9a4facfc"})
        self.assertNotIn("secret", json.dumps(shape))
        self.assertEqual(shape["threadId"]["uuid"], "01a123fd-cd1a-7fa2-a8f0-ce7f9a4facfc")

    def test_disabled_does_not_create_file(self):
        with mock.patch.dict(os.environ, {"STB_MCP_IDENTITY_DIAGNOSTICS": ""}):
            diagnostic = IdentityDiagnostics()
            diagnostic.record({"method": "initialize"})
            self.assertIsNone(diagnostic.path)

    def test_private_records_exclude_arguments_and_are_bounded(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(
            os.environ, {"STB_MCP_IDENTITY_DIAGNOSTICS": "1"}
        ), mock.patch("mcp_server.identity_diagnostics.tempfile.mkdtemp", return_value=folder):
            diagnostic = IdentityDiagnostics()
            request = {"method": "tools/call", "params": {
                "name": "terminal_session_acquire", "arguments": {"secret": "password"},
                "_meta": {"authorization": "sensitive-token"},
            }}
            for _ in range(40):
                diagnostic.record(request)
            data = diagnostic.path.read_text()
            self.assertNotIn("password", data)
            self.assertNotIn("sensitive-token", data)
            self.assertEqual(len(data.splitlines()), 32)
            self.assertEqual(diagnostic.path.stat().st_mode & 0o777, 0o600)
