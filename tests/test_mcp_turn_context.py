#!/usr/bin/env python3
"""Focused tests for mcp turn context."""

from tests.mcp_support import *  # noqa: F401,F403

class MinimalMCPServerTest(unittest.TestCase):
    def test_turn_resolver_uses_latest_verified_user_message(self):
        with tempfile.TemporaryDirectory() as directory:
            session_dir = pathlib.Path(directory) / "sessions" / "2026" / "09" / "20"
            session_dir.mkdir(parents=True)
            path = session_dir / "rollout-thread-1.jsonl"
            records = [
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "item_completed",
                        "thread_id": "thread-1",
                        "turn_id": "turn-1",
                        "item": {"type": "UserMessage"},
                        "started_at_ms": 1000,
                    },
                },
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "item_completed",
                        "thread_id": "other-thread",
                        "turn_id": "untrusted-turn",
                        "item": {"type": "UserMessage"},
                        "started_at_ms": 9999,
                    },
                },
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "item_completed",
                        "thread_id": "thread-1",
                        "turn_id": "turn-2",
                        "item": {"type": "UserMessage"},
                        "started_at_ms": 2000,
                    },
                },
            ]
            path.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            resolved = CodexTurnResolver(
                thread_id="thread-1",
                codex_root=directory,
            ).current()
            self.assertEqual(
                resolved,
                {
                    "thread_id": "thread-1",
                    "turn_id": "turn-2",
                    "turn_started_at_ms": 2000,
                },
            )

    def test_turn_resolver_binds_process_to_nearest_session_meta(self):
        with tempfile.TemporaryDirectory() as directory:
            session_dir = pathlib.Path(directory) / "sessions" / "2026" / "09" / "20"
            session_dir.mkdir(parents=True)
            candidates = [
                ("thread-old", "2026-09-20T08:31:20.000Z", 1000),
                ("thread-near", "2026-09-20T08:31:59.900Z", 2000),
            ]
            for thread_id, timestamp, user_ms in candidates:
                records = [
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": thread_id,
                            "timestamp": timestamp,
                        },
                    },
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "item_completed",
                            "thread_id": thread_id,
                            "turn_id": f"turn-{thread_id}",
                            "item": {"type": "UserMessage"},
                            "started_at_ms": user_ms,
                        },
                    },
                ]
                (session_dir / f"rollout-{thread_id}.jsonl").write_text(
                    "".join(json.dumps(record) + "\n" for record in records),
                    encoding="utf-8",
                )
            process_ms = int(
                datetime.datetime.fromisoformat(
                    "2026-09-20T08:32:00+00:00"
                ).timestamp()
                * 1000
            )
            resolver = CodexTurnResolver(
                codex_root=directory,
                process_started_at_ms=process_ms,
            )
            self.assertEqual(resolver.infer_thread_id(), "thread-near")
            self.assertEqual(resolver.current()["turn_id"], "turn-thread-near")


if __name__ == "__main__":
    unittest.main()
