"""MCP tool declarations for the long run domain."""

from mcp_server.tools.common import GENERATION, PANE, object_schema

TOOLS = [
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
        }
,
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
        }
,
]
