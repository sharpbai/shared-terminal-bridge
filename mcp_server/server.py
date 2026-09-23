#!/usr/bin/env python3
"""Dependency-free MCP stdio adapter for the local Bridge Unix socket."""

import argparse
import datetime
import json
import os
import pathlib
import socket
import sys
import threading
import time
import uuid


SERVER_INFO = {
    "name": "shared-terminal-bridge",
    "version": "0.14.0",
    "description": "Local, human-first tmux observation and leased actions",
}
MODERN_VERSION = "2026-07-28"
LEGACY_VERSION = "2025-11-25"
SUPPORTED_VERSIONS = [MODERN_VERSION, LEGACY_VERSION]
SERVER_INFO_META = "io.modelcontextprotocol/serverInfo"
PROTOCOL_VERSION_META = "io.modelcontextprotocol/protocolVersion"
CLIENT_CAPABILITIES_META = "io.modelcontextprotocol/clientCapabilities"
REQUIRES_BRIDGE_V2 = {
    "terminal_read_delta",
    "terminal_task_block",
    "terminal_task_observe",
}
REQUIRES_BRIDGE_V3 = {
    "terminal_wait_delta",
    "terminal_long_run_approve",
    "terminal_session_read_delta",
    "terminal_session_wait_delta",
    "terminal_session_state",
}
REQUIRES_BRIDGE_V4 = {
    "terminal_long_run_request",
}
REQUIRES_BRIDGE_V5 = {
    "terminal_job_list",
    "terminal_job_status",
}
REQUIRES_BRIDGE_V6 = {
    "terminal_wait_job",
}
REQUIRES_BRIDGE_V7 = {
    "terminal_history",
}
REQUIRES_BRIDGE_V8 = {
    "terminal_task_block_execute",
}
REQUIRES_BRIDGE_V9 = {
    "terminal_program_profile",
}


class MCPError(Exception):
    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class BridgeClient:
    def __init__(self, socket_path):
        self.socket_path = pathlib.Path(socket_path)

    def call(self, method, params):
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            client.connect(str(self.socket_path))
            with client:
                writer = client.makefile("w", encoding="utf-8")
                reader = client.makefile("r", encoding="utf-8")
                writer.write(
                    json.dumps(
                        {"method": method, "params": params},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                writer.flush()
                line = reader.readline()
        except OSError as error:
            return {
                "ok": False,
                "error": {
                    "code": "BRIDGE_UNAVAILABLE",
                    "message": str(error),
                },
            }
        if not line:
            return {
                "ok": False,
                "error": {"code": "BRIDGE_EMPTY_RESPONSE"},
            }
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return {
                "ok": False,
                "error": {"code": "BRIDGE_INVALID_RESPONSE"},
            }


class CodexTurnResolver:
    """Resolve the latest real user turn from Codex-owned local records."""

    def __init__(
        self,
        thread_id=None,
        codex_root=None,
        process_started_at_ms=None,
    ):
        self.thread_id = thread_id or os.environ.get("CODEX_THREAD_ID")
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
        best = None
        sessions_root = self.codex_root / "sessions"
        for path in sessions_root.glob("**/rollout-*.jsonl"):
            session_meta = None
            discovered_thread = None
            try:
                lines = path.open("r", encoding="utf-8")
            except OSError:
                continue
            with lines:
                for index, line in enumerate(lines):
                    if index >= 100:
                        break
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    payload = entry.get("payload") or {}
                    if entry.get("type") == "session_meta":
                        session_meta = payload
                    if entry.get("type") == "event_msg":
                        if payload.get("thread_id"):
                            discovered_thread = payload["thread_id"]
                        item = payload.get("item") or {}
                        if (
                            payload.get("type") == "item_completed"
                            and item.get("type") == "UserMessage"
                            and payload.get("thread_id")
                        ):
                            discovered_thread = payload["thread_id"]
                            break
            if not session_meta:
                continue
            started_at_ms = self.parse_timestamp_ms(session_meta.get("timestamp"))
            thread_id = discovered_thread or session_meta.get("id")
            if started_at_ms is None or not thread_id:
                continue
            distance = abs(started_at_ms - self.process_started_at_ms)
            if distance > 60_000:
                continue
            candidate = (distance, started_at_ms, thread_id)
            if best is None or candidate < best:
                best = candidate
        if best is not None:
            self.thread_id = best[2]
        return self.thread_id

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


def object_schema(properties=None, required=None):
    schema = {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


PANE = {"type": "string", "pattern": r"^%[0-9]+$"}
GENERATION = {"type": "integer", "minimum": 1}

OBSERVATION_TOOLS = [
    {
        "name": "terminal_list",
        "title": "List tmux panes",
        "description": (
            "List pane identity and authorization metadata. This never returns "
            "terminal contents for unauthorized panes."
        ),
        "inputSchema": object_schema(),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "get_active_pane",
        "title": "Resolve a tmux client's active pane",
        "description": (
            "Resolve the active pane for one explicit tmux client. Unknown "
            "clients fail closed and no global-current-pane fallback is used."
        ),
        "inputSchema": object_schema(
            {"client": {"type": "string", "minLength": 1}},
            ["client"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "terminal_history",
        "title": "Read persistent tmux/STB interaction history",
        "description": (
            "Read the local 0600 JSONL audit history for managed tmux/STB "
            "interactions. Filter by session, pane, or action. Password input "
            "content is never recorded."
        ),
        "inputSchema": object_schema(
            {
                "session": {"type": "string", "minLength": 1},
                "pane": PANE,
                "action": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 100},
            }
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "terminal_read",
        "title": "Read bounded pane history",
        "description": (
            "Read bounded history from an explicitly authorized pane. The "
            "Bridge enforces the pane ACL before capture-pane."
        ),
        "inputSchema": object_schema(
            {
                "pane": PANE,
                "lines": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5000,
                    "default": 100,
                },
            },
            ["pane"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "terminal_read_delta",
        "title": "Read context-budgeted pane delta",
        "description": (
            "Preferred observation tool. Returns only output added after an "
            "opaque Bridge cursor, removes terminal noise, folds repeats, and "
            "enforces byte and line budgets. Pass the returned cursor on the "
            "next call; never reconstruct or reuse an older cursor."
        ),
        "inputSchema": object_schema(
            {
                "pane": PANE,
                "cursor": {"type": "string", "minLength": 1},
                "max_bytes": {"type": "integer", "minimum": 1, "maximum": 65536, "default": 16384},
                "max_lines": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
                "command_echo": {"type": "string"},
            },
            ["pane"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "terminal_state",
        "title": "Read pane state",
        "description": (
            "Read bounded tmux state for an explicitly authorized pane, "
            "including cwd and current command."
        ),
        "inputSchema": object_schema({"pane": PANE}, ["pane"]),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "terminal_wait_delta",
        "title": "Wait locally for pane output",
        "description": (
            "Wait up to 30 seconds in the local Bridge for pane output. Writes "
            "nothing and returns CHANGED, QUIET, BUDGET_EXHAUSTED, or "
            "INTERRUPTED. Stop model polling after BUDGET_EXHAUSTED."
        ),
        "inputSchema": object_schema(
            {
                "pane": PANE,
                "cursor": {"type": "string", "minLength": 1},
                "wait_ms": {"type": "integer", "minimum": 1, "maximum": 30000, "default": 10000},
                "idle_budget_ms": {"type": "integer", "minimum": 1, "maximum": 600000, "default": 30000},
                "total_budget_ms": {"type": "integer", "minimum": 1, "maximum": 600000, "default": 60000},
                "max_bytes": {"type": "integer", "minimum": 1, "maximum": 65536, "default": 16384},
                "max_lines": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
                "command_echo": {"type": "string"},
            },
            ["pane", "cursor"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]

ACTION_TOOLS = [
    {
        "name": "terminal_long_run_request",
        "title": "Request user approval for one long command",
        "description": (
            "Create a non-executing approval request before a command expected "
            "over 120 seconds or marked high_io/full_scan. This returns "
            "input_required with a request ID and the exact command. Show the "
            "full command, duration, resource impact, and budgets to the user, "
            "then end the turn. A later explicit approval message may approve "
            "the request; the user never needs to retype the command."
        ),
        "inputSchema": object_schema(
            {
                "pane": PANE,
                "generation": GENERATION,
                "text": {"type": "string", "minLength": 1},
                "expected_duration_ms": {"type": "integer", "minimum": 1},
                "resource_class": {"type": "string", "enum": ["normal", "high_io", "full_scan"]},
                "idle_budget_ms": {"type": "integer", "minimum": 1, "maximum": 600000},
                "total_budget_ms": {"type": "integer", "minimum": 1, "maximum": 600000},
            },
            ["pane", "generation", "text", "expected_duration_ms", "resource_class"],
        ),
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "terminal_long_run_approve",
        "title": "Record explicit approval for one long command",
        "description": (
            "Call only after the user explicitly approves a previously shown "
            "long-run request in a later message. Pass its request ID; the user "
            "does not need to retype the command. The Bridge verifies task and "
            "turn ordering and returns a one-use approval for terminal_submit."
        ),
        "inputSchema": object_schema(
            {
                "pane": PANE,
                "generation": GENERATION,
                "request_id": {"type": "string", "minLength": 1},
            },
            ["pane", "generation", "request_id"],
        ),
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "terminal_task_block",
        "title": "Create a local terminal task scope",
        "description": (
            "Create local planning and observation metadata for 1-32 intended "
            "commands. This tool writes no bytes to the pane and makes no "
            "assumption about its execution environment. Submit each actual "
            "command explicitly with terminal_submit, observing between "
            "steps. Human Ctrl+C revokes the generation and ends the turn."
        ),
        "inputSchema": object_schema(
            {
                "pane": PANE,
                "generation": GENERATION,
                "commands": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 32,
                    "items": {"type": "string", "minLength": 1},
                },
                "stop_on_error": {"type": "boolean", "default": True},
            },
            ["pane", "generation", "commands"],
        ),
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "terminal_task_observe",
        "title": "Observe a terminal task block",
        "description": (
            "Return a compact pane delta since the preceding observation in "
            "this local task scope. It does not infer shell completion or exit "
            "codes. Repeated observations do not resend prior output."
        ),
        "inputSchema": object_schema(
            {
                "block_id": {"type": "string", "minLength": 1},
                "max_bytes": {"type": "integer", "minimum": 1, "maximum": 65536, "default": 16384},
                "max_lines": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
            },
            ["block_id"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "terminal_task_block_execute",
        "title": "Execute a bounded read-only terminal task block",
        "description": (
            "Execute 1-8 conservative read-only commands sequentially in the "
            "local Bridge. Each command remains visible, creates its own job, "
            "and is checked against the same pane lease and Human Ctrl+C "
            "override before it is sent. The Runner rejects shell control "
            "operators, redirection, expansion, unknown executables, and "
            "mutating subcommands. Use only when the next step does not need "
            "semantic model judgment. The existing terminal_task_block remains "
            "non-executing planning metadata."
        ),
        "inputSchema": object_schema(
            {
                "pane": PANE,
                "generation": GENERATION,
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 8,
                    "items": object_schema(
                        {
                            "step_id": {"type": "string", "minLength": 1},
                            "text": {"type": "string", "minLength": 1},
                            "expected_duration_ms": {
                                "type": "integer", "minimum": 1, "maximum": 120000,
                            },
                            "assert": {
                                "type": "object",
                                "minProperties": 1,
                                "maxProperties": 1,
                                "properties": {
                                    "contains": {"type": "string"},
                                    "not_contains": {"type": "string"},
                                    "regex": {"type": "string"},
                                },
                                "additionalProperties": False,
                            },
                        },
                        ["text"],
                    ),
                },
                "max_duration_ms": {
                    "type": "integer", "minimum": 1, "maximum": 120000,
                    "default": 120000,
                },
                "stop_on_error": {"type": "boolean", "default": True},
            },
            ["pane", "generation", "steps"],
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    },
    {
        "name": "terminal_program_profile",
        "title": "Inspect a terminal program capability profile",
        "description": (
            "Return local, read-only guidance about a known terminal program's "
            "CLI/CMD/batch interface and TUI fallback policy. Call this before "
            "driving a known full-screen program. This does not inspect or write "
            "the target terminal; installed-version support must still be verified "
            "with the profile's safe probe. If TUI is required, prefer a human "
            "checkpoint over agent key-by-key operation. Omit program to list profiles."
        ),
        "inputSchema": object_schema(
            {"program": {"type": "string", "minLength": 1}},
            [],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "terminal_session_acquire",
        "title": "Acquire this task's execution lease",
        "description": (
            "Acquire a fresh execution lease for one managed session only "
            "when new terminal input is required. Reading history/state never "
            "requires this tool. A new Codex task must acquire its own "
            "generation before its first "
            "write. After a human Ctrl+C, do not call this tool again in the "
            "same user turn: read once and return immediately. It may be called "
            "again only after the user sends a later message requesting more "
            "terminal work."
        ),
        "inputSchema": object_schema(
            {"name": {"type": "string", "minLength": 1}},
            ["name"],
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": False,
        },
    },
    {
        "name": "terminal_execution_status",
        "title": "Check execution lease and Human Override status",
        "description": (
            "Read the current lease state for an authorized pane. REVOKED with "
            "an event_seq means the human pressed Ctrl+C. In that case collect "
            "available output once and immediately finish the current user turn."
        ),
        "inputSchema": object_schema({"pane": PANE}, ["pane"]),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "terminal_submit",
        "title": "Submit one terminal command",
        "description": (
            "Type one complete command literally and press Enter atomically. "
            "Prefer this over separate terminal_type and terminal_key calls. "
            "Declare expected duration and resource class. Tell the user before "
            "a 30-120 second command; over 120 seconds or high_io/full_scan "
            "requires a matching one-use long-run approval. A physical human "
            "Ctrl+C revokes the generation before any later submit."
        ),
        "inputSchema": object_schema(
            {
                "pane": PANE,
                "generation": GENERATION,
                "text": {"type": "string", "minLength": 1},
                "expected_duration_ms": {"type": "integer", "minimum": 1},
                "resource_class": {"type": "string", "enum": ["normal", "high_io", "full_scan"]},
                "long_run_approval_id": {"type": "string", "minLength": 1},
            },
            ["pane", "generation", "text", "expected_duration_ms", "resource_class"],
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "openWorldHint": True,
        },
    },
    {
        "name": "terminal_type",
        "title": "Type text under an execution lease",
        "description": (
            "Type literal text into an authorized pane. Requires a generation "
            "created out-of-band by explicit authorization; this MCP server "
            "cannot acquire a lease."
        ),
        "inputSchema": object_schema(
            {"pane": PANE, "generation": GENERATION, "text": {"type": "string"}},
            ["pane", "generation", "text"],
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "openWorldHint": True,
        },
    },
    {
        "name": "terminal_key",
        "title": "Send one key under an execution lease",
        "description": (
            "Send one tmux key name to an authorized pane using a valid "
            "out-of-band execution lease generation."
        ),
        "inputSchema": object_schema(
            {
                "pane": PANE,
                "generation": GENERATION,
                "key": {"type": "string", "minLength": 1},
            },
            ["pane", "generation", "key"],
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "openWorldHint": True,
        },
    },
    {
        "name": "terminal_interrupt",
        "title": "Send Agent Ctrl+C under an execution lease",
        "description": (
            "Send Agent-originated Ctrl+C to an authorized pane. Requires a "
            "valid generation and does not impersonate a Human Event."
        ),
        "inputSchema": object_schema(
            {"pane": PANE, "generation": GENERATION},
            ["pane", "generation"],
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "openWorldHint": True,
        },
    },
]

JOB_TOOLS = [
    {
        "name": "terminal_job_list",
        "title": "List locally monitored terminal jobs",
        "description": (
            "List Bridge-owned terminal jobs without writing to any pane. "
            "Use this for recovery or manual inspection, not repeated polling."
        ),
        "inputSchema": object_schema(
            {
                "state": {
                    "type": "string",
                    "enum": ["RUNNING", "COMPLETED", "INTERRUPTED_BY_HUMAN", "NEEDS_ATTENTION", "HUMAN_DECISION_REQUIRED"],
                }
            }
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "terminal_job_status",
        "title": "Read one terminal job status",
        "description": (
            "Read compact status and recent evidence for one job. Set "
            "include_output only for an explicit diagnostic read; ordinary "
            "status checks should keep it false. This never writes to the pane."
        ),
        "inputSchema": object_schema(
            {
                "job_id": {"type": "string", "minLength": 1},
                "include_output": {"type": "boolean", "default": False},
            },
            ["job_id"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "terminal_wait_job",
        "title": "Wait locally for a terminal job event",
        "description": (
            "Block locally in one call for up to 10 minutes without model polling. "
            "Use the default 600000 ms instead of repeated short waits. Return "
            "immediately on completion, Human Ctrl+C, an interactive prompt, or "
            "the human decision deadline. At 10 minutes return "
            "STRATEGY_REVIEW_REQUIRED: compare alternatives using only meaningful "
            "output evidence, then wait again only when justified. Never "
            "auto-interrupt at a deadline."
        ),
        "inputSchema": object_schema(
            {
                "job_id": {"type": "string", "minLength": 1},
                "wait_ms": {"type": "integer", "minimum": 1, "maximum": 600000, "default": 600000},
            },
            ["job_id"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]

SESSION_TOOLS = [
    {
        "name": "terminal_session_list",
        "title": "List managed tmux sessions",
        "description": (
            "List only tmux sessions carrying the Shared Terminal managed "
            "marker. Ordinary user sessions are excluded."
        ),
        "inputSchema": object_schema(),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "terminal_session_read_delta",
        "title": "Read a managed session delta by name",
        "description": "Observe a named managed session without listing sessions or acquiring a lease.",
        "inputSchema": object_schema(
            {
                "name": {"type": "string", "minLength": 1},
                "cursor": {"type": "string", "minLength": 1},
                "max_bytes": {"type": "integer", "minimum": 1, "maximum": 65536, "default": 16384},
                "max_lines": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
                "command_echo": {"type": "string"},
            },
            ["name"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "terminal_session_wait_delta",
        "title": "Wait for a managed session delta by name",
        "description": "Wait locally for output from an exact managed session name; no lease or prior list call is required.",
        "inputSchema": object_schema(
            {
                "name": {"type": "string", "minLength": 1},
                "cursor": {"type": "string", "minLength": 1},
                "wait_ms": {"type": "integer", "minimum": 1, "maximum": 30000, "default": 10000},
                "idle_budget_ms": {"type": "integer", "minimum": 1, "maximum": 600000, "default": 30000},
                "total_budget_ms": {"type": "integer", "minimum": 1, "maximum": 600000, "default": 60000},
                "max_bytes": {"type": "integer", "minimum": 1, "maximum": 65536, "default": 16384},
                "max_lines": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
                "command_echo": {"type": "string"},
            },
            ["name", "cursor"],
        ),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "terminal_session_state",
        "title": "Read managed session state by name",
        "description": "Read state for one exact managed session without listing sessions or acquiring a lease.",
        "inputSchema": object_schema({"name": {"type": "string", "minLength": 1}}, ["name"]),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "terminal_session_create",
        "title": "Create a managed interactive tmux session",
        "description": (
            "Create a marked managed tmux session and authorize its initial "
            "pane in the Bridge ACL. Returns the session name and pane ID for "
            "the user-facing stb enter command."
        ),
        "inputSchema": object_schema(
            {
                "name": {
                    "type": "string",
                    "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$",
                },
                "cwd": {"type": "string", "minLength": 1},
            },
            ["name", "cwd"],
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    },
    {
        "name": "terminal_session_stop",
        "title": "Stop a managed tmux session",
        "description": (
            "Stop only a session carrying the managed marker, remove its pane "
            "from the dynamic ACL, and revoke any active lease."
        ),
        "inputSchema": object_schema(
            {"name": {"type": "string", "minLength": 1}},
            ["name"],
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "openWorldHint": False,
        },
    },
]


class MinimalMCPServer:
    def __init__(
        self,
        bridge,
        enable_actions=False,
        enable_session_management=False,
        turn_resolver=None,
    ):
        self.bridge = bridge
        self.enable_actions = enable_actions
        self.acquired_panes = {}
        self.turn_resolver = turn_resolver or CodexTurnResolver()
        self.legacy_initialized = False
        self.tools = list(OBSERVATION_TOOLS)
        if enable_actions:
            self.tools.extend(ACTION_TOOLS)
            self.tools.extend(JOB_TOOLS)
        if enable_session_management:
            self.tools.extend(SESSION_TOOLS)
        self.declared_tools = list(self.tools)
        self.declared_tool_by_name = {
            tool["name"]: tool for tool in self.declared_tools
        }
        self.tool_by_name = dict(self.declared_tool_by_name)
        self.bridge_compatibility = None
        self.request_wait_ids = {}
        self.cancelled_requests = set()
        self.request_lock = threading.RLock()

    def refresh_bridge_compatibility(self):
        """Publish only tools supported by the currently running daemon."""
        if self.bridge_compatibility is not None:
            return self.bridge_compatibility
        response = self.bridge.call("bridge_info", {})
        if response.get("ok", False):
            info = response.get("result", {})
            api_version = info.get("api_version")
            if isinstance(api_version, int):
                self.bridge_compatibility = {
                    "status": "compatible" if api_version >= 3 else (
                        "upgrade_available" if api_version == 2 else "legacy"
                    ),
                    "api_version": api_version,
                    "version": info.get("version"),
                }
        elif response.get("error", {}).get("code") == "METHOD_NOT_FOUND":
            self.bridge_compatibility = {
                "status": "restart_required",
                "api_version": 1,
                "message": (
                    "The running Bridge daemon predates this MCP server. "
                    "Restart it with: stb daemon stop && stb daemon start"
                ),
            }
        if self.bridge_compatibility is None:
            # Unknown/fake/unavailable bridges retain discovery compatibility;
            # the actual call will still fail closed.
            self.bridge_compatibility = {"status": "unknown"}
        api_version = self.bridge_compatibility.get("api_version")
        if isinstance(api_version, int):
            self.tools = [
                tool
                for tool in self.declared_tools
                if not (
                    (api_version < 2 and tool["name"] in REQUIRES_BRIDGE_V2)
                    or (api_version < 3 and tool["name"] in REQUIRES_BRIDGE_V3)
                    or (api_version < 4 and tool["name"] in REQUIRES_BRIDGE_V4)
                    or (api_version < 5 and tool["name"] in REQUIRES_BRIDGE_V5)
                    or (api_version < 6 and tool["name"] in REQUIRES_BRIDGE_V6)
                    or (api_version < 7 and tool["name"] in REQUIRES_BRIDGE_V7)
                    or (api_version < 8 and tool["name"] in REQUIRES_BRIDGE_V8)
                    or (api_version < 9 and tool["name"] in REQUIRES_BRIDGE_V9)
                )
            ]
        else:
            self.tools = list(self.declared_tools)
        self.tool_by_name = {tool["name"]: tool for tool in self.tools}
        return self.bridge_compatibility

    @staticmethod
    def response_meta():
        return {SERVER_INFO_META: SERVER_INFO}

    def validate_modern_request(self, request):
        params = request.get("params") or {}
        meta = params.get("_meta") or {}
        requested = meta.get(PROTOCOL_VERSION_META)
        if requested is None:
            return False
        if requested != MODERN_VERSION:
            raise MCPError(
                -32022,
                "Unsupported protocol version",
                {"supported": SUPPORTED_VERSIONS, "requested": requested},
            )
        if not isinstance(meta.get(CLIENT_CAPABILITIES_META), dict):
            raise MCPError(-32602, "Missing modern client capabilities metadata")
        return True

    def discover(self):
        compatibility = self.refresh_bridge_compatibility()
        return {
            "supportedVersions": SUPPORTED_VERSIONS,
            "capabilities": {"tools": {"listChanged": False}},
            "instructions": (
                "For an exact managed session name, use the name-based tools "
                "directly; do not list sessions first. Observation tools "
                "are pane-ACL constrained and never require an execution lease. "
                "For requests that only inspect existing history or state, use "
                "terminal_read_delta/terminal_read/terminal_state without "
                "terminal_session_acquire. Only when new terminal input is "
                "required, call terminal_session_acquire once for the selected "
                "managed session, then submit every command visibly and "
                "separately with terminal_submit. For its returned job_id, "
                "prefer terminal_wait_job: it waits locally up to 10 minutes "
                "in one call without repeated short model waits. On completion "
                "it returns bounded output for that command, so do not add a "
                "terminal_job_status call unless explicit diagnostics are needed. Its default "
                "600000 ms should normally be left unchanged. On "
                "STRATEGY_REVIEW_REQUIRED "
                "compare alternative approaches and wait again only if justified. "
                "HUMAN_DECISION_REQUIRED never authorizes "
                "automatic interruption. "
                "Commands expected to exceed 120 seconds or marked high_io/"
                "full_scan must first call terminal_long_run_request, show its "
                "exact command and impact, and end the turn. A later explicit "
                "user approval can call terminal_long_run_approve with the "
                "request ID, but must acquire the new user turn's lease before "
                "calling approve; never require the user to retype the command. "
                "terminal_task_block is optional local "
                "planning metadata only and never executes its command list. "
                "For 2-8 independent, simple read-only commands whose next "
                "steps do not require semantic judgment, prefer "
                "terminal_task_block_execute. It is intentionally conservative "
                "and stops on Human Ctrl+C, interaction, assertion failure, or "
                "lease change. "
                "Before operating a known full-screen terminal program, call "
                "terminal_program_profile and prefer its CLI/CMD/batch interface. "
                "If no adequate non-interactive path exists, tell the human the "
                "target checkpoint, end the turn, and observe once after they reach it. "
                "Agent-driven TUI keys are a last resort; avoid one-key/one-read loops. "
                "Batch independent lightweight read-only probes into one visible "
                "shell command line to reduce model round trips; keep mutations, "
                "dependent steps, and verification boundaries separate. "
                "Prefer terminal_read_delta over terminal_read and always pass "
                "its latest cursor. Never guess "
                "or reuse a generation from terminal history. If terminal_read "
                "reports human_override=true, or an action reports a revoked "
                "lease, read available output at most once and immediately "
                "finish the current user turn. Never reacquire in that turn. "
                "A later user message requesting more work authorizes a fresh "
                "terminal_session_acquire, including in the same Codex task."
            ),
            "ttlMs": 300000,
            "cacheScope": "private",
            "bridgeCompatibility": compatibility,
            "_meta": self.response_meta(),
        }

    def initialize(self, params):
        requested = params.get("protocolVersion")
        if requested not in SUPPORTED_VERSIONS:
            selected = LEGACY_VERSION
        else:
            selected = requested
        if selected == MODERN_VERSION:
            raise MCPError(
                -32022,
                "Modern MCP uses server/discover, not initialize",
                {"supported": SUPPORTED_VERSIONS, "requested": requested},
            )
        self.legacy_initialized = True
        return {
            "protocolVersion": selected,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": (
                "Use exact managed session names directly; list only when the "
                "name is missing or ambiguous. Observation does not require a "
                "lease. Before the first actual write call "
                "terminal_session_acquire; never guess a generation. If a "
                "human override is reported, read once and immediately return "
                "to the user without more writes or reacquisition. A later user "
                "message may acquire a fresh generation."
            ),
        }

    def list_tools(self, modern):
        compatibility = self.refresh_bridge_compatibility()
        result = {"tools": self.tools}
        if modern:
            result.update(
                {
                    "resultType": "complete",
                    "ttlMs": 300000,
                    "cacheScope": "private",
                    "_meta": self.response_meta(),
                    "bridgeCompatibility": compatibility,
                }
            )
        return result

    @staticmethod
    def validate_arguments(tool, arguments):
        if not isinstance(arguments, dict):
            raise MCPError(-32602, "Tool arguments must be an object")
        schema = tool["inputSchema"]
        properties = schema["properties"]
        unknown = sorted(set(arguments) - set(properties))
        missing = sorted(set(schema.get("required", [])) - set(arguments))
        if unknown or missing:
            raise MCPError(
                -32602,
                "Invalid tool arguments",
                {"unknown": unknown, "missing": missing},
            )
        for name, value in arguments.items():
            expected = properties[name].get("type")
            if expected == "string" and not isinstance(value, str):
                raise MCPError(-32602, f"{name} must be a string")
            if expected == "integer" and (
                not isinstance(value, int) or isinstance(value, bool)
            ):
                raise MCPError(-32602, f"{name} must be an integer")
            if expected == "boolean" and not isinstance(value, bool):
                raise MCPError(-32602, f"{name} must be a boolean")
            if expected == "array" and not isinstance(value, list):
                raise MCPError(-32602, f"{name} must be an array")
        pane = arguments.get("pane")
        if pane is not None and (
            not pane.startswith("%") or not pane[1:].isdigit()
        ):
            raise MCPError(-32602, "pane must be a stable tmux pane ID")
        lines = arguments.get("lines")
        if lines is not None and not 1 <= lines <= 5000:
            raise MCPError(-32602, "lines must be between 1 and 5000")
        max_bytes = arguments.get("max_bytes")
        if max_bytes is not None and not 1 <= max_bytes <= 65536:
            raise MCPError(-32602, "max_bytes must be between 1 and 65536")
        max_lines = arguments.get("max_lines")
        if max_lines is not None and not 1 <= max_lines <= 1000:
            raise MCPError(-32602, "max_lines must be between 1 and 1000")
        commands = arguments.get("commands")
        if commands is not None and (
            not 1 <= len(commands) <= 32
            or any(not isinstance(command, str) or not command for command in commands)
        ):
            raise MCPError(-32602, "commands must contain 1 to 32 non-empty strings")
        steps = arguments.get("steps")
        if steps is not None and (
            not isinstance(steps, list)
            or not 1 <= len(steps) <= 8
            or any(
                not isinstance(step, dict)
                or not isinstance(step.get("text"), str)
                or not step.get("text")
                for step in steps
            )
        ):
            raise MCPError(-32602, "steps must contain 1 to 8 objects with non-empty text")
        generation = arguments.get("generation")
        if generation is not None and generation < 1:
            raise MCPError(-32602, "generation must be positive")
        for name in ("client", "key", "name", "cwd", "cursor", "block_id"):
            if name in arguments and not arguments[name]:
                raise MCPError(-32602, f"{name} must not be empty")

    def call_tool(self, params, modern, request_id=None):
        name = params.get("name")
        compatibility = self.refresh_bridge_compatibility()
        tool = self.tool_by_name.get(name)
        if tool is None:
            if (
                name in (REQUIRES_BRIDGE_V2 | REQUIRES_BRIDGE_V3 | REQUIRES_BRIDGE_V4 | REQUIRES_BRIDGE_V5 | REQUIRES_BRIDGE_V6 | REQUIRES_BRIDGE_V7 | REQUIRES_BRIDGE_V8 | REQUIRES_BRIDGE_V9)
                and compatibility.get("status") in ("legacy", "restart_required")
            ):
                bridge_response = {
                    "ok": False,
                    "error": {
                        "code": "BRIDGE_RESTART_REQUIRED",
                        "method": name,
                        "message": compatibility.get("message", "Running Bridge API is too old."),
                    },
                }
                return self.tool_result(bridge_response, modern)
            raise MCPError(-32602, f"Unknown or disabled tool: {name}")
        arguments = params.get("arguments") or {}
        self.validate_arguments(tool, arguments)
        if name == "terminal_session_acquire":
            bridge_response = self.acquire_session(arguments["name"])
        elif name == "terminal_wait_job":
            wait_id = f"wait_{uuid.uuid4().hex[:12]}"
            with self.request_lock:
                self.request_wait_ids[request_id] = wait_id
                cancelled_early = request_id in self.cancelled_requests
                self.cancelled_requests.discard(request_id)
            if cancelled_early:
                self.bridge.call("terminal_cancel_wait", {"wait_id": wait_id})
            try:
                bridge_response = self.bridge.call(
                    "terminal_wait_job", {**arguments, "wait_id": wait_id}
                )
            finally:
                with self.request_lock:
                    self.request_wait_ids.pop(request_id, None)
        else:
            bridge_method = (
                "execution_status"
                if name == "terminal_execution_status"
                else name
            )
            bridge_response = self.bridge.call(bridge_method, arguments)
        if (
            name in (REQUIRES_BRIDGE_V2 | REQUIRES_BRIDGE_V3 | REQUIRES_BRIDGE_V4 | REQUIRES_BRIDGE_V5 | REQUIRES_BRIDGE_V6 | REQUIRES_BRIDGE_V7 | REQUIRES_BRIDGE_V8 | REQUIRES_BRIDGE_V9)
            and bridge_response.get("error", {}).get("code") == "METHOD_NOT_FOUND"
        ):
            bridge_response = {
                "ok": False,
                "error": {
                    "code": "BRIDGE_RESTART_REQUIRED",
                    "method": name,
                    "message": "Restart the local daemon: stb daemon stop && stb daemon start",
                },
            }
        return self.tool_result(bridge_response, modern)

    def tool_result(self, bridge_response, modern):
        is_error = not bridge_response.get("ok", False)
        result = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(bridge_response, ensure_ascii=False),
                }
            ],
            "structuredContent": bridge_response,
            "isError": is_error,
        }
        if modern:
            interaction = bridge_response.get("result", {}).get("interaction")
            result["resultType"] = (
                "inputRequired" if interaction == "input_required" else "complete"
            )
            result["_meta"] = self.response_meta()
        return result

    def acquire_session(self, name):
        turn = self.turn_resolver.current()
        if turn is None:
            return {
                "ok": False,
                "error": {
                    "code": "CODEX_TURN_ID_UNAVAILABLE",
                    "message": (
                        "No verified Codex user turn is available; lease was not issued."
                    ),
                },
            }
        compatibility = self.refresh_bridge_compatibility()
        if compatibility.get("api_version", 3) >= 3:
            resolved = self.bridge.call("terminal_session_resolve", {"name": name})
            if not resolved.get("ok", False):
                return resolved
            session = resolved.get("result", {})
        else:
            sessions_response = self.bridge.call("terminal_session_list", {})
            if not sessions_response.get("ok", False):
                return sessions_response
            session = next(
                (
                    item
                    for item in sessions_response.get("result", {}).get("sessions", [])
                    if item.get("name") == name
                ),
                None,
            )
            if session is None:
                return {
                    "ok": False,
                    "error": {"code": "SESSION_NOT_MANAGED", "session": name},
                }
        pane = session.get("pane")
        if pane in self.acquired_panes:
            status = self.bridge.call("execution_status", {"pane": pane})
            if not status.get("ok", False):
                return status
            lease = status.get("result", {}).get("lease")
            if lease and lease.get("state") == "ACTIVE":
                authorization = lease.get("authorization") or {}
                if authorization.get("turn_id") == turn.get("turn_id"):
                    return {
                        "ok": False,
                        "error": {
                            "code": "EXECUTION_LEASE_ALREADY_ACTIVE",
                            "session": name,
                            "pane": pane,
                            "generation": lease.get("generation"),
                        },
                    }
        response = self.bridge.call(
            "acquire_execution",
            {"pane": pane, **turn},
        )
        if response.get("ok", False):
            self.acquired_panes[pane] = response.get("result", {}).get(
                "generation"
            )
            response.setdefault("result", {})["session"] = name
        return response

    def cancel_request(self, request_id):
        with self.request_lock:
            wait_id = self.request_wait_ids.get(request_id)
        if wait_id is None:
            with self.request_lock:
                self.cancelled_requests.add(request_id)
            return False
        self.bridge.call("terminal_cancel_wait", {"wait_id": wait_id})
        return True

    def dispatch(self, request):
        if request.get("jsonrpc") != "2.0" or not isinstance(
            request.get("method"), str
        ):
            raise MCPError(-32600, "Invalid Request")
        method = request["method"]
        params = request.get("params") or {}
        if not isinstance(params, dict):
            raise MCPError(-32602, "params must be an object")
        if method == "server/discover":
            self.validate_modern_request(request)
            return self.discover()
        if method == "initialize":
            return self.initialize(params)
        if method == "notifications/cancelled":
            target = params.get("requestId", params.get("request_id"))
            self.cancel_request(target)
            return None
        if method == "notifications/initialized":
            return None
        modern = self.validate_modern_request(request)
        if not modern and not self.legacy_initialized:
            raise MCPError(-32002, "Server is not initialized")
        if method == "ping":
            return {}
        if method == "tools/list":
            return self.list_tools(modern)
        if method == "tools/call":
            return self.call_tool(params, modern, request_id=request.get("id"))
        raise MCPError(-32601, "Method not found", {"method": method})

    def handle(self, request):
        request_id = request.get("id") if isinstance(request, dict) else None
        try:
            result = self.dispatch(request)
            if request_id is None or result is None:
                return None
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except MCPError as error:
            if request_id is None:
                return None
            payload = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": error.code, "message": error.message},
            }
            if error.data is not None:
                payload["error"]["data"] = error.data
            return payload

    def run_stdio(self, input_stream=sys.stdin, output_stream=sys.stdout):
        output_lock = threading.Lock()
        workers = []

        def write_response(response):
            if response is None:
                return
            with output_lock:
                output_stream.write(json.dumps(response, ensure_ascii=False) + "\n")
                output_stream.flush()

        def process(request):
            write_response(self.handle(request))

        for line in input_stream:
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("request must be an object")
                method = request.get("method")
                if method == "tools/call" and request.get("id") is not None:
                    worker = threading.Thread(
                        target=process,
                        args=(request,),
                        daemon=True,
                    )
                    workers.append(worker)
                    worker.start()
                    continue
                response = self.handle(request)
            except (json.JSONDecodeError, ValueError) as error:
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": str(error)},
                }
            write_response(response)
        for worker in workers:
            worker.join(timeout=1)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bridge-socket",
        type=pathlib.Path,
        default=pathlib.Path("/tmp/shared-terminal-bridge.sock"),
    )
    parser.add_argument(
        "--enable-actions",
        action="store_true",
        help="register leased action tools; lease acquisition stays out-of-band",
    )
    parser.add_argument(
        "--enable-session-management",
        action="store_true",
        help="register managed tmux session create/list/stop tools",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    server = MinimalMCPServer(
        BridgeClient(args.bridge_socket),
        enable_actions=args.enable_actions,
        enable_session_management=args.enable_session_management,
    )
    server.run_stdio()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
