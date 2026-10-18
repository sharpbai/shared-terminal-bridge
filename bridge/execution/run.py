"""One receipt: admit a command once, then observe its existing job.

Only the submission is durable-deduplicated. Retrying run observes that same
job; it never reacquires a lease or repeats terminal input. Wait cancellation
and deadlines retain the existing job/wait semantics.
"""

from bridge.common import BridgeError
from bridge.config import DEFAULT_TOTAL_BUDGET_MS, MAX_JOB_WAIT_MS
from bridge.runtime.admission import received_after_revocation
from bridge.execution.lifecycle import EXECUTING, execution_phase


class RunService:
    def __init__(self, bridge):
        self.bridge = bridge

    def terminal_run(self, pane, request_id, text,
                     expected_duration_ms=DEFAULT_TOTAL_BUDGET_MS,
                     resource_class="normal", wait_ms=MAX_JOB_WAIT_MS,
                     long_run_approval_id=None, wait_id=None, _authorization=None):
        # Validate the observation window BEFORE any execution side effect.
        if type(wait_ms) is not int or not 1 <= wait_ms <= MAX_JOB_WAIT_MS:
            raise BridgeError("INVALID_JOB_WAIT", wait_ms=wait_ms)
        command = dict(pane=pane, text=text, expected_duration_ms=expected_duration_ms,
                       resource_class=resource_class,
                       long_run_approval_id=long_run_approval_id)
        # The operation discriminator prevents cross-method ID collisions.
        # wait_ms/wait_id are observation parameters, not a new command.
        submitted = self.bridge._submit_once(
            dict(command, request_id=request_id, operation="terminal_run"),
            lambda: self._admit_and_submit(command, _authorization))
        waited = self.bridge.terminal_wait_job(
            submitted["job_id"], wait_ms=wait_ms, wait_id=wait_id)
        return dict(waited, request_id=request_id,
                    generation=submitted["generation"])

    def terminal_interrupt_job(self, job_id):
        """Resolve authority from the original job, never from a newer lease."""
        with self.bridge.lock:
            job = self.bridge.jobs.get(job_id)
            if job is None:
                raise BridgeError("TERMINAL_JOB_NOT_FOUND", job_id=job_id)
            self.bridge.authorize(job["pane"])
            if execution_phase(job) != EXECUTING:
                raise BridgeError("TERMINAL_JOB_NOT_EXECUTING", job_id=job_id)
            self.bridge.require_lease(job["pane"], job["generation"])
            result = self.bridge.terminal_interrupt(job["pane"], job["generation"])
            return dict(result, job_id=job_id)

    def _admit_and_submit(self, command, authorization=None):
        pane = command["pane"]
        self.bridge.authorize(pane)
        with self.bridge.lock:
            lease = self.bridge.leases.get(pane)
            if lease and lease["state"] == "REVOKED" and not received_after_revocation(lease):
                raise BridgeError("EXECUTION_LEASE_INVALID", pane=pane,
                                  generation=lease["generation"])
            if lease and lease["state"] == "ACTIVE":
                generation = lease["generation"]
            else:
                generation = self.bridge.acquire_execution(pane)["generation"]
            # Host user-turn metadata is approval evidence, not a prerequisite
            # for routine execution authority. Local receipt order owns that.
            if authorization:
                self.bridge.leases[pane]["authorization"] = dict(authorization)
                self.bridge.persist_state()
        # Deliberately call the strict method, NOT dispatch/auto-renew here.
        # A Human Event between admission and submit must cancel this chain.
        result = self.bridge.terminal_submit(generation=generation, **command)
        return dict(result, generation=generation)
