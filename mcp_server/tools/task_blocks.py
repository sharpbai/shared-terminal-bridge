"""MCP tool declarations for the task blocks domain."""

from mcp_server.tools.common import GENERATION, PANE, object_schema

TOOLS = [
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
        }
,
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
        }
,
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
        }
,
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
