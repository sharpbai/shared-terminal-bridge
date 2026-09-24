"""MCP tool declarations for the sessions domain."""

from mcp_server.tools.common import GENERATION, PANE, object_schema

TOOLS = [
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
        }
,
    {
            "name": "terminal_session_list",
            "title": "List managed tmux sessions",
            "description": (
                "List only tmux sessions carrying the Shared Terminal managed "
                "marker. Ordinary user sessions are excluded."
            ),
            "inputSchema": object_schema(),
            "annotations": {"readOnlyHint": True, "openWorldHint": False},
        }
,
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
        }
,
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
        }
,
    {
            "name": "terminal_session_state",
            "title": "Read managed session state by name",
            "description": "Read state for one exact managed session without listing sessions or acquiring a lease.",
            "inputSchema": object_schema({"name": {"type": "string", "minLength": 1}}, ["name"]),
            "annotations": {"readOnlyHint": True, "openWorldHint": False},
        }
,
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
        }
,
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
        }
,
]
