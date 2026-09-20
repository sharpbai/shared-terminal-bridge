"""Deterministic admission control for terminal observations.

Raw tmux output remains the source of truth.  This module produces a bounded,
incremental view suitable for model context without using an LLM summarizer.
"""

from __future__ import annotations

import hashlib
import re


ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
class AIContextPolicy:
    """Build cursor-based observations with deterministic size limits."""

    DEFAULT_MAX_BYTES = 16_384
    DEFAULT_MAX_LINES = 200
    MAX_BYTES = 65_536
    MAX_LINES = 1_000

    @staticmethod
    def normalize(content: str) -> list[str]:
        content = ANSI_RE.sub("", content).replace("\r\n", "\n").replace("\r", "\n")
        return [CONTROL_RE.sub("", line).rstrip() for line in content.splitlines()]

    @staticmethod
    def fingerprint(lines: list[str]) -> str:
        payload = "\n".join(lines).encode("utf-8", errors="replace")
        return hashlib.sha256(payload).hexdigest()[:16]

    @staticmethod
    def delta(previous: list[str], current: list[str]) -> list[str]:
        """Return lines not present in the prior snapshot using suffix overlap."""
        maximum = min(len(previous), len(current))
        for overlap in range(maximum, -1, -1):
            if previous[len(previous) - overlap :] == current[:overlap]:
                return current[overlap:]
        return current

    @staticmethod
    def collapse_repeats(lines: list[str]):
        output = []
        repeated = []
        index = 0
        while index < len(lines):
            end = index + 1
            while end < len(lines) and lines[end] == lines[index]:
                end += 1
            count = end - index
            if count >= 3 and lines[index]:
                output.append(lines[index])
                output.append(f"[repeated {count - 1} more times]")
                repeated.append({"line": lines[index], "count": count})
            else:
                output.extend(lines[index:end])
            index = end
        return output, repeated

    @classmethod
    def apply(
        cls,
        previous_content: str,
        current_content: str,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_lines: int = DEFAULT_MAX_LINES,
        command_echo: str | None = None,
    ):
        if not 1 <= max_bytes <= cls.MAX_BYTES:
            raise ValueError("max_bytes outside policy range")
        if not 1 <= max_lines <= cls.MAX_LINES:
            raise ValueError("max_lines outside policy range")

        previous = cls.normalize(previous_content)
        current = cls.normalize(current_content)
        delta = cls.delta(previous, current)
        filtered = []
        # Kept in the result schema for compatibility with v0.5 clients.
        # The transparent transport has no private protocol markers to hide.
        dropped_markers = 0
        dropped_echoes = 0
        for line in delta:
            if command_echo and line.strip().endswith(command_echo.strip()):
                dropped_echoes += 1
                continue
            filtered.append(line)

        collapsed, repeated = cls.collapse_repeats(filtered)
        original_lines = len(collapsed)
        if len(collapsed) > max_lines:
            # Preserve both the beginning and the most recent output.
            head = max_lines // 3
            tail = max_lines - head
            omitted = len(collapsed) - max_lines
            collapsed = collapsed[:head] + [f"[... {omitted} lines omitted ...]"] + collapsed[-tail:]

        encoded = "\n".join(collapsed).encode("utf-8", errors="replace")
        truncated_bytes = 0
        if len(encoded) > max_bytes:
            truncated_bytes = len(encoded) - max_bytes
            suffix = encoded[-max_bytes:].decode("utf-8", errors="ignore")
            content = f"[... {truncated_bytes} bytes omitted ...]\n{suffix}"
        else:
            content = encoded.decode("utf-8")

        return {
            "content": content,
            "no_change": not bool(delta),
            "raw_delta_lines": len(delta),
            "returned_lines": len(content.splitlines()) if content else 0,
            "omitted_lines": max(0, original_lines - max_lines),
            "omitted_bytes": truncated_bytes,
            "dropped_markers": dropped_markers,
            "dropped_echoes": dropped_echoes,
            "repeated_groups": repeated,
            "snapshot_fingerprint": cls.fingerprint(current),
        }
