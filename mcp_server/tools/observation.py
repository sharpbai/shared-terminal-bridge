"""MCP tool declarations for the observation domain."""

from mcp_server.tools.common import GENERATION, PANE, object_schema

TOOLS = [
    {
            "name": "terminal_list",
            "title": "List tmux panes",
            "description": (
                "List pane identity and authorization metadata. This never returns "
                "terminal contents for unauthorized panes."
            ),
            "inputSchema": object_schema(),
            "annotations": {"readOnlyHint": True, "openWorldHint": False},
        }
,
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
        }
,
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
        }
,
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
        }
,
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
        }
,
    {
            "name": "terminal_state",
            "title": "Read pane state",
            "description": (
                "Read bounded tmux state for an explicitly authorized pane, "
                "including cwd and current command."
            ),
            "inputSchema": object_schema({"pane": PANE}, ["pane"]),
            "annotations": {"readOnlyHint": True, "openWorldHint": False},
        }
,
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
        }
,
]
