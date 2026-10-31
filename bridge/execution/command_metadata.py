"""Command fingerprints and audit redaction; no approval policy."""
import hashlib
import re

class CommandMetadataService:
    def __init__(self, bridge):
        self.bridge = bridge

    @staticmethod
    def _command_fingerprint(text: str):
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _history_command(text: str):
        sensitive = re.compile(
            r"(password|passwd|api[_-]?key|access[_-]?token|secret)\s*(=|:)|"
            r"\b(export|setenv)\b.*(token|secret|password|key)",
            re.IGNORECASE,
        )
        return "[REDACTED_SENSITIVE_COMMAND]" if sensitive.search(text) else text
