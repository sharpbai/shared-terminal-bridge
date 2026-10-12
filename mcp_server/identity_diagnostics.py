"""Opt-in, redacted inspection of host-provided MCP identity metadata.

Diagnostic records are evidence only, never an authorization source.
"""

import json
import os
import pathlib
import tempfile
import threading
import uuid


IDENTITY_KEYS = {
    "thread_id", "threadId", "turn_id", "turnId",
    "codex/thread_id", "codex/threadId", "openai/thread_id",
}


def metadata_shape(value, depth=0):
    """Keep bounded key structure; redact every non-identity scalar."""
    if not isinstance(value, dict) or depth >= 4:
        return {"type": type(value).__name__}
    result = {}
    for key, item in list(value.items())[:64]:
        if key in IDENTITY_KEYS and isinstance(item, str):
            try:
                result[key] = {"uuid": str(uuid.UUID(item))}
                continue
            except ValueError:
                pass
        result[key] = metadata_shape(item, depth + 1)
    return result


class IdentityDiagnostics:
    """One private file per MCP connection, explicitly enabled by environment."""

    def __init__(self):
        self.path = None
        self.lock = threading.Lock()
        self.records = 0

    def record(self, request):
        if os.environ.get("STB_MCP_IDENTITY_DIAGNOSTICS") != "1":
            return
        method = request.get("method")
        params = request.get("params") or {}
        if not isinstance(params, dict):
            return
        if method not in ("initialize", "server/discover") and not (
            method == "tools/call"
            and params.get("name") == "terminal_session_acquire"
        ):
            return
        record = {
            "pid": os.getpid(), "method": method,
            "request_keys": list(request)[:64],
            "params_keys": list(params)[:64],
            "request_meta": metadata_shape(request.get("_meta")),
            "params_meta": metadata_shape(params.get("_meta")),
            "client_info": metadata_shape(params.get("clientInfo")),
            "capabilities": metadata_shape(params.get("capabilities")),
        }
        # Never inspect arguments: a model-supplied ID is not host identity.
        try:
            with self.lock:
                if self.records >= 32:
                    return
                if self.path is None:
                    folder = pathlib.Path(tempfile.mkdtemp(prefix="stb-mcp-identity-"))
                    self.path = folder / "metadata.jsonl"
                    fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                else:
                    fd = os.open(str(self.path), os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(json.dumps(record) + "\n")
                self.records += 1
        except OSError:
            # Diagnostics cannot change tool success, lease rules, or stdout.
            return
