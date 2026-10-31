"""Resolve interactive input authority inside Core, never in models."""
from bridge.common import BridgeError
from uuid import uuid4
from bridge.execution.lifecycle import EXECUTING, execution_phase


class JobActionService:
    def __init__(self, bridge):
        self.bridge = bridge

    def terminal_input_job(self, job_id, request_id=None, text=None, key=None):
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
        if request_id is None:
            request_id = "input_" + uuid4().hex
        return self.bridge._submit_once(dict(operation="terminal_input_job", pane=pane,
            request_id=request_id, job_id=job_id, text=text, key=key), execute)
