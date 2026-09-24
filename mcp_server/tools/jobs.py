"""MCP tool declarations for the jobs domain."""

from mcp_server.tools.common import GENERATION, PANE, object_schema

TOOLS = [
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
        }
,
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
        }
,
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
        }
,
]
