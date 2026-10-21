"""Model-facing tasks: authority bookkeeping is private to Core."""
from mcp_server.tools.common import PANE, object_schema

ID = {"type": "string", "minLength": 1, "maxLength": 128}
JOB = {"type": "string", "minLength": 1}


def tool(name, description, fields, required):
    return {"name": name, "title": name, "description": description,
            "inputSchema": object_schema(fields, required),
            "annotations": {"readOnlyHint": False, "destructiveHint": True,
                            "openWorldHint": True}}


TOOLS = [
    tool("terminal_run", "Execute one visible command and wait. Core handles authority. "
         "Use a unique request_id; retry the same ID only to observe the original job. "
         "Human Ctrl+C cancels this chain; a new call may continue. High risk still needs approval.",
         {"pane": PANE, "request_id": ID, "text": {"type": "string", "minLength": 1},
          "expected_duration_ms": {"type": "integer", "minimum": 1},
          "resource_class": {"type": "string", "enum": ["normal", "high_io", "full_scan"]},
          "wait_ms": {"type": "integer", "minimum": 1, "maximum": 600000},
          "long_run_approval_id": ID}, ["pane", "request_id", "text"]),
    tool("terminal_input_job", "Send text OR one key to an executing job. Old/interrupted "
         "jobs cannot target a newer task. Use a unique request_id for input retry protection.",
         {"job_id": JOB, "request_id": ID, "text": {"type": "string"},
          "key": {"type": "string", "minLength": 1}}, ["job_id", "request_id"]),
    tool("terminal_interrupt_job", "Send Agent Ctrl+C to this job and wait for prompt return "
         "in the same call (default 600000ms, optional wait_ms). "
         "Never impersonates a Human Event or targets a newer task. accepted means the key "
         "was requested, not process exit. Check termination_confirmed and job status; "
         "if false, keep observing and do not submit another command.",
         {"job_id": JOB, "wait_ms": {"type": "integer", "minimum": 1, "maximum": 600000}}, ["job_id"]),
    tool("terminal_approve_request", "Only after explicit human approval of the exact "
         "displayed resource request, approve its request_id. Does not execute it. "
         "Core resolves authority; then use a new run ID with the returned approval_id.",
         {"request_id": ID}, ["request_id"]),
]
