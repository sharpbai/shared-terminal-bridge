"""Execution lifecycle, separate from wait/checkpoint delivery states.

NEEDS_ATTENTION and HUMAN_DECISION_REQUIRED stop a wait, not the command.
Only EXECUTING jobs can be interrupted by a human to revoke their lease.
"""

EXECUTING = "EXECUTING"
FINISHED = "FINISHED"
INTERRUPTED = "INTERRUPTED"


def execution_phase(job):
    """Interpret saved jobs from before the explicit lifecycle was introduced."""
    if "execution_phase" in job:
        return job["execution_phase"]
    return (EXECUTING if job.get("state") in {
        "RUNNING", "NEEDS_ATTENTION", "HUMAN_DECISION_REQUIRED",
    } else FINISHED)


def sync_execution_phase(job):
    if job["state"] == "INTERRUPTED_BY_HUMAN":
        job["execution_phase"] = INTERRUPTED
    elif job["state"] in {"COMPLETED", "FAILED"}:
        job["execution_phase"] = FINISHED

