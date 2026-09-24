"""MCP tool declarations for the execution domain."""

from mcp_server.tools.common import GENERATION, PANE, object_schema

TOOLS = [
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
        }
,
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
        }
,
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
