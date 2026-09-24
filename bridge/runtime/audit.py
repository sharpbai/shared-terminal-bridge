"""Persistent interaction history and in-memory audit records."""

import json
import os

from bridge.common import BridgeError, now

class AuditService:
    def __init__(self, bridge):
        self.bridge = bridge

    def record(self, action: str, **fields):
        pane = fields.get("pane")
        if pane and "session" not in fields:
            session = next(
                (
                    item.get("name")
                    for item in self.bridge.managed_sessions.values()
                    if item.get("pane") == pane
                ),
                None,
            )
            if session:
                fields["session"] = session
        entry = {
            "timestamp": now(),
            "action": action,
            **fields,
        }
        with self.bridge.lock:
            self.bridge.audit.append(entry)
            history_file = getattr(self.bridge, "history_file", None)
            if history_file is not None:
                history_file.parent.mkdir(parents=True, exist_ok=True)
                with history_file.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
                os.chmod(history_file, 0o600)

    def terminal_history(
        self, session: str = None, pane: str = None, action: str = None, limit: int = 100
    ):
        try:
            limit = int(limit)
            if not 1 <= limit <= 1000:
                raise ValueError
        except (TypeError, ValueError) as error:
            raise BridgeError("INVALID_HISTORY_LIMIT", limit=limit) from error
        history_file = getattr(self.bridge, "history_file", None)
        if history_file is None or not history_file.exists():
            return {"entries": [], "history_file": str(history_file or "")}
        entries = []
        for line in reversed(history_file.read_text(encoding="utf-8", errors="replace").splitlines()):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if session is not None and entry.get("session") != session:
                continue
            if pane is not None and entry.get("pane") != pane:
                continue
            if action is not None and entry.get("action") != action:
                continue
            entries.append(entry)
            if len(entries) >= limit:
                break
        entries.reverse()
        return {"entries": entries, "history_file": str(history_file)}

    def audit_log(self):
        with self.bridge.lock:
            return {"entries": list(self.bridge.audit)}
