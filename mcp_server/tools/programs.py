"""Read-only terminal program capability guidance."""

from mcp_server.tools.common import PANE, object_schema

TOOLS = [
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
        }
,
]
