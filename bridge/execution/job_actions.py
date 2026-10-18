"""Resolve interactive input/approval authority inside Core, never in models."""
from bridge.common import BridgeError
from bridge.execution.lifecycle import EXECUTING, execution_phase


class JobActionService:
    def __init__(self, bridge):
        self.bridge = bridge

    def terminal_input_job(self, job_id, request_id, text=None, key=None):
        if (text is None) == (key is None):
            raise BridgeError("INVALID_JOB_INPUT", reason="provide text OR key")
        if text is not None and (not isinstance(text, str) or any(
                ord(character) < 32 or ord(character) == 127 for character in text)):
            raise BridgeError("INVALID_JOB_INPUT", reason="text must be literal printable input; use key for controls")
        if key is not None and (not isinstance(key, str) or not key):
            raise BridgeError("INVALID_JOB_INPUT", reason="key must be a nonempty string")
        with self.bridge.lock:
            job = self.bridge.jobs.get(job_id)
            if job is None:
                raise BridgeError("TERMINAL_JOB_NOT_FOUND", job_id=job_id)
            pane = job["pane"]
            self.bridge.authorize(pane)
        def execute():
            with self.bridge.lock:
                if execution_phase(job) != EXECUTING:
                    raise BridgeError("TERMINAL_JOB_NOT_EXECUTING", job_id=job_id)
                self.bridge.require_lease(pane, job["generation"])
                # Strict methods only: never revive an interrupted interaction.
                if text is not None:
                    result = self.bridge.terminal_type(pane, job["generation"], text)
                else:
                    result = self.bridge.terminal_key(pane, job["generation"], key)
                return dict(result, job_id=job_id)
        return self.bridge._submit_once(dict(operation="terminal_input_job", pane=pane,
            request_id=request_id, job_id=job_id, text=text, key=key), execute)

    def terminal_approve_request(self, request_id, _authorization=None):
        # The original approval implementation still checks later trusted user
        # intent or an explicit local CLI decision. No new approval shortcut.
        request = self.bridge._long_run_request(request_id)
        pane = request["pane"]
        self.bridge.authorize(pane)
        with self.bridge.lock:
            lease = self.bridge.leases.get(pane)
            if _authorization:
                lease = self.bridge.acquire_execution(pane, **_authorization)
            elif not lease or lease["state"] != "ACTIVE":
                authorization = dict((lease or {}).get("authorization") or {})
                lease = self.bridge.acquire_execution(pane, **authorization)
            return self.bridge.terminal_long_run_approve(
                pane, lease["generation"], request_id=request_id)
