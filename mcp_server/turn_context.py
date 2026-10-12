"""Resolve a Codex user turn from local session records."""

import datetime
import json
import os
import pathlib
import time
import uuid

class CodexTurnResolver:
    """Resolve the latest real user turn from Codex-owned local records."""

    def __init__(
        self,
        thread_id=None,
        codex_root=None,
        process_started_at_ms=None,
    ):
        self.thread_id = thread_id or os.environ.get("CODEX_THREAD_ID") or None
        self.codex_root = pathlib.Path(
            codex_root or os.environ.get("CODEX_HOME") or pathlib.Path.home() / ".codex"
        )
        self.process_started_at_ms = (
            process_started_at_ms
            if process_started_at_ms is not None
            else time.time_ns() // 1_000_000
        )

    @staticmethod
    def parse_timestamp_ms(value):
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return int(parsed.timestamp() * 1000)

    def infer_thread_id(self):
        candidates = set()
        sessions_root = self.codex_root / "sessions"
        for path in sessions_root.glob("**/rollout-*.jsonl"):
            session_meta = None
            try:
                lines = path.open("r", encoding="utf-8")
            except OSError:
                continue
            with lines:
                for line in lines:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    payload = entry.get("payload") or {}
                    if entry.get("type") == "session_meta":
                        session_meta = payload
                        started_at_ms = self.parse_timestamp_ms(payload.get("timestamp"))
                        if (
                            started_at_ms is None
                            or abs(started_at_ms - self.process_started_at_ms) > 60_000
                        ):
                            break
                    if entry.get("type") == "event_msg":
                        item = payload.get("item") or {}
                        if (
                            session_meta
                            and payload.get("thread_id") == session_meta.get("id")
                            and payload.get("turn_id")
                            and isinstance(payload.get("started_at_ms"), int)
                            and not isinstance(payload.get("started_at_ms"), bool)
                            and payload.get("type") == "item_completed"
                            and item.get("type") == "UserMessage"
                            and payload.get("thread_id")
                        ):
                            candidates.add(payload["thread_id"])
                            break
        # Desktop startup can create an empty rollout next to the real task.
        # Never bind to it, or choose between concurrent verified tasks by time.
        if len(candidates) == 1:
            self.thread_id = candidates.pop()
        return self.thread_id

    def from_request(self, meta):
        """Verify host envelope identity without changing connection state.

        Never accept tool arguments as identity or select the globally newest
        task. Request-local resolution also avoids concurrent-call cross-talk.
        """
        if not isinstance(meta, dict):
            return None
        host = meta.get("x-codex-turn-metadata")
        if not isinstance(host, dict):
            return None
        thread_id = host.get("thread_id")
        turn_id = host.get("turn_id")
        for value in (thread_id, turn_id):
            if not isinstance(value, str):
                return None
            try:
                if str(uuid.UUID(value)) != value:
                    return None
            except ValueError:
                return None
        started = host.get("turn_started_at_unix_ms")
        if not isinstance(started, int) or isinstance(started, bool) or started <= 0:
            return None
        if meta.get("threadId", thread_id) != thread_id:
            return None
        # Read only this thread's latest genuine user turn. A stale request
        # cannot borrow the authorization of a newer message.
        verified = CodexTurnResolver(
            thread_id=thread_id, codex_root=self.codex_root
        ).current()
        if verified is None or verified["turn_id"] != turn_id:
            return None
        # Use the user event's recorded time, not a model parameter or a guess.
        return verified

    def current(self):
        if not self.thread_id and not self.infer_thread_id():
            return None
        candidates = self.codex_root.glob(
            f"sessions/**/rollout-*{self.thread_id}*.jsonl"
        )
        latest = None
        for path in candidates:
            try:
                lines = path.open("r", encoding="utf-8")
            except OSError:
                continue
            with lines:
                for line in lines:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("type") != "event_msg":
                        continue
                    payload = entry.get("payload") or {}
                    item = payload.get("item") or {}
                    if (
                        payload.get("type") != "item_completed"
                        or payload.get("thread_id") != self.thread_id
                        or item.get("type") != "UserMessage"
                    ):
                        continue
                    started_at_ms = payload.get("started_at_ms")
                    turn_id = payload.get("turn_id")
                    if not isinstance(started_at_ms, int) or not turn_id:
                        continue
                    candidate = {
                        "thread_id": self.thread_id,
                        "turn_id": turn_id,
                        "turn_started_at_ms": started_at_ms,
                    }
                    if latest is None or started_at_ms > latest["turn_started_at_ms"]:
                        latest = candidate
        return latest
