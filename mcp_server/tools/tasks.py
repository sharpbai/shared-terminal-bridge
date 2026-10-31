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
         "Core generates request_id when omitted; follow the returned job_id. Do not resubmit on timeout. "
         "Human Ctrl+C cancels this chain; a new call may continue. High risk still needs approval.",
         {"pane": PANE, "request_id": ID, "text": {"type": "string", "minLength": 1},
          "expected_duration_ms": {"type": "integer", "minimum": 1},
          "resource_class": {"type": "string", "enum": ["normal", "high_io", "full_scan"]},
          "wait_ms": {"type": "integer", "minimum": 1, "maximum": 600000}}, ["pane", "text"]),
    tool("terminal_interrupt_job", "Send Agent Ctrl+C to this job and wait for prompt return "
         "in the same call (default 600000ms, optional wait_ms). "
         "Never impersonates a Human Event or targets a newer task. accepted means the key "
         "was requested, not process exit. Check termination_confirmed and job status; "
         "if false, keep observing and do not submit another command.",
         {"job_id": JOB, "wait_ms": {"type": "integer", "minimum": 1, "maximum": 600000}}, ["job_id"]),

]
