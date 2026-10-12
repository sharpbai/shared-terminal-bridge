"""Request-local Codex identity survives old-thread resumes without guessing."""

import json
import pathlib
import tempfile
import unittest
from unittest import mock

from mcp_server.turn_context import CodexTurnResolver
from mcp_server.server import MinimalMCPServer
from tests.mcp_support import FakeBridgeV3


THREAD = "01a123fd-cd1a-7fa2-a8f0-ce7f9a4facfc"
TURN = "01a12f1a-2a5e-7053-87f4-cab21c75922a"
OTHER = "01a0bcb7-1e03-79c1-a483-e75ffa369cb9"


class RequestIdentityTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = pathlib.Path(self.folder.name) / "sessions"
        root.mkdir()
        self.path = root / ("rollout-" + THREAD + ".jsonl")
        self.path.write_text(json.dumps({"type": "event_msg", "payload": {
            "type": "item_completed", "thread_id": THREAD, "turn_id": TURN,
            "started_at_ms": 1234, "item": {"type": "UserMessage"},
        }}) + "\n")
        self.resolver = CodexTurnResolver(thread_id=OTHER, codex_root=self.folder.name)
        self.meta = {"threadId": THREAD, "x-codex-turn-metadata": {
            "thread_id": THREAD, "turn_id": TURN, "turn_started_at_unix_ms": 1200,
        }}

    def test_resumed_thread_uses_request_not_connection_identity(self):
        result = self.resolver.from_request(self.meta)
        self.assertEqual(result, {"thread_id": THREAD, "turn_id": TURN, "turn_started_at_ms": 1234})
        self.assertEqual(self.resolver.thread_id, OTHER)

    def test_invalid_metadata_never_falls_back(self):
        for meta in (None, {}, {"x-codex-turn-metadata": "invalid"}):
            self.assertIsNone(self.resolver.from_request(meta))
        for key, value in (("thread_id", "../../other"), ("turn_id", OTHER),
                           ("turn_started_at_unix_ms", True), ("turn_started_at_unix_ms", -1)):
            changed = {**self.meta, "x-codex-turn-metadata": {**self.meta["x-codex-turn-metadata"], key: value}}
            self.assertIsNone(self.resolver.from_request(changed))

    def test_conflicting_thread_alias_rejected(self):
        self.assertIsNone(self.resolver.from_request({**self.meta, "threadId": OTHER}))

    def test_older_turn_cannot_borrow_newer_message(self):
        with self.path.open("a") as stream:
            stream.write(json.dumps({"type": "event_msg", "payload": {
                "type": "item_completed", "thread_id": THREAD, "turn_id": OTHER,
                "started_at_ms": 2000, "item": {"type": "UserMessage"},
            }}) + "\n")
        self.assertIsNone(self.resolver.from_request(self.meta))

    def test_tool_dispatch_passes_envelope_not_arguments(self):
        server = MinimalMCPServer(FakeBridgeV3(), enable_actions=True, enable_session_management=True)
        with mock.patch.object(server, "acquire_session", return_value={"ok": False}) as acquire:
            server.call_tool({"name": "terminal_session_acquire", "arguments": {"name": "local-mac"}, "_meta": self.meta}, False)
            acquire.assert_called_once_with("local-mac", request_meta=self.meta)

    def test_failure_does_not_reach_bridge(self):
        bridge = FakeBridgeV3()
        server = MinimalMCPServer(bridge, enable_session_management=True, turn_resolver=self.resolver)
        result = server.acquire_session("local-mac", request_meta={})
        self.assertEqual(result["error"]["code"], "CODEX_TURN_ID_UNAVAILABLE")
        self.assertEqual(bridge.calls, [])
