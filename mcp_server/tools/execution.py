"""MCP tool declarations for the execution domain."""

from mcp_server.tools.common import GENERATION, PANE, object_schema

TOOLS = [
    {
            "name": "terminal_execution_status",
            "title": "Check execution lease and Human Override status",
            "description": (
                "Read the current lease state for an authorized pane. REVOKED with "
                "an event_seq means the human interrupted an executing command. "
                "Stop its queued chain. A later new call may automatically renew "
                "authorization; a new user message is not required."
            ),
            "inputSchema": object_schema({"pane": PANE}, ["pane"]),
            "annotations": {"readOnlyHint": True, "openWorldHint": False},
        }
,
    {
            "name": "terminal_submit",
            "title": "Submit one terminal command",
            "description": (
                "Type one complete command literally and press Enter atomically. "
                "Prefer this over separate terminal_type and terminal_key calls. "
                "Declare expected duration and resource class. Tell the user before "
                "a long command; high_io/full_scan "
                "requires a matching one-use long-run approval. A physical human "
                "Ctrl+C cancels the current chain. New calls received afterward "
                "automatically obtain a fresh generation; use the returned generation. "
                "Duration alone does not require approval."
            ),
            "inputSchema": object_schema(
                {
                    "pane": PANE,
                    "generation": GENERATION,
                    "text": {"type": "string", "minLength": 1},
                    "request_id": {"type": "string", "minLength": 1, "maxLength": 128,
                                   "description": "Stable unique logical command ID. Reuse unchanged on transport retry; never reuse for a new command."},
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
        }
,
    {
            "name": "terminal_type",
            "title": "Type text under an execution lease",
            "description": (
                "Type literal text into an authorized pane. Requires a generation "
                "from an acquired lease. A new call after human interruption may "
                "renew it automatically; use the generation returned by Bridge."
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
        }
,
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
        }
,
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
        }
,
]
