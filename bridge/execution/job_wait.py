"""Job lookup plus cancellable, event-driven wait operations."""

import threading
import uuid

from bridge.common import BridgeError, now, unix_ms
from bridge.config import JOB_TERMINAL_STATES, MAX_JOB_WAIT_MS


class JobWaitService:
    def __init__(self, bridge):
        self.bridge = bridge

    def _signal_job_waits(self, job_id: str, reason: str):
        with self.bridge.lock:
            handles = [
                handle for handle in self.bridge.wait_handles.values()
                if handle["job_id"] == job_id
            ]
            for handle in handles:
                handle["wake_reason"] = reason
                handle["event"].set()

    def terminal_job_list(self, state: str = None):
        with self.bridge.lock:
            ids = list(self.bridge.jobs)
        jobs = [self.bridge._job_result(self.bridge._refresh_job(job_id), include_output=False) for job_id in ids]
        if state is not None:
            jobs = [job for job in jobs if job["state"] == state]
        jobs.sort(key=lambda item: item["submitted_at"], reverse=True)
        return {"jobs": jobs}

    def terminal_job_status(self, job_id: str, include_output: bool = False):
        return self.bridge._job_result(
            self.bridge._refresh_job(job_id), include_output=bool(include_output)
        )

    def terminal_wait_list(self):
        with self.bridge.lock:
            waits = [
                {
                    "wait_id": wait_id,
                    "job_id": handle["job_id"],
                    "created_at": handle["created_at"],
                    "cancelled": handle["cancelled"],
                    "wake_reason": handle.get("wake_reason"),
                }
                for wait_id, handle in self.bridge.wait_handles.items()
            ]
        return {"waits": waits}

    def terminal_cancel_wait(self, wait_id: str):
        with self.bridge.lock:
            handle = self.bridge.wait_handles.get(wait_id)
            if handle is None:
                self.bridge.cancelled_wait_ids.add(wait_id)
                while len(self.bridge.cancelled_wait_ids) > 256:
                    self.bridge.cancelled_wait_ids.pop()
                return {"wait_id": wait_id, "cancelled": True, "pending_registration": True}
            handle["cancelled"] = True
            handle["wake_reason"] = "WAIT_CANCELLED"
            handle["event"].set()
        self.bridge.record("WAIT_CANCEL", wait_id=wait_id, job_id=handle["job_id"])
        return {"wait_id": wait_id, "job_id": handle["job_id"], "cancelled": True}

    def terminal_wait_job(
        self,
        job_id: str,
        wait_ms: int = MAX_JOB_WAIT_MS,
        wait_id: str = None,
    ):
        try:
            wait_ms = int(wait_ms)
            if not 1 <= wait_ms <= MAX_JOB_WAIT_MS:
                raise ValueError
        except (TypeError, ValueError) as error:
            raise BridgeError("INVALID_JOB_WAIT", wait_ms=wait_ms) from error
        wait_id = wait_id or f"wait_{uuid.uuid4().hex[:12]}"
        event = threading.Event()
        handle = {
            "job_id": job_id,
            "event": event,
            "created_at": now(),
            "cancelled": False,
            "wake_reason": None,
        }
        with self.bridge.lock:
            if wait_id in self.bridge.wait_handles:
                raise BridgeError("WAIT_ID_ALREADY_EXISTS", wait_id=wait_id)
            self.bridge.wait_handles[wait_id] = handle
            if wait_id in self.bridge.cancelled_wait_ids:
                self.bridge.cancelled_wait_ids.discard(wait_id)
                handle["cancelled"] = True
                handle["wake_reason"] = "WAIT_CANCELLED"
                event.set()
        try:
            job = self.bridge._refresh_job(job_id)
            if job["state"] in JOB_TERMINAL_STATES:
                result = self.bridge._job_result(job, include_output=False)
                result["wait_id"] = wait_id
                return result
            event.wait(wait_ms / 1000)
            job = self.bridge._refresh_job(job_id)
            result = self.bridge._job_result(job, include_output=False)
            result["wait_id"] = wait_id
            if job["state"] in JOB_TERMINAL_STATES:
                return result
            if handle["cancelled"]:
                result["state"] = "WAIT_CANCELLED"
                result["guidance"] = "Only the model wait was cancelled; the terminal job is still running."
            elif unix_ms() >= job["strategy_review_at_ms"]:
                result["state"] = "STRATEGY_REVIEW_REQUIRED"
                result["guidance"] = (
                    "Compare continued waiting with alternative approaches. Do not infer "
                    "progress from arbitrary percentages and do not interrupt automatically."
                )
            else:
                result["state"] = "WAIT_TIMEOUT"
            return result
        finally:
            with self.bridge.lock:
                self.bridge.wait_handles.pop(wait_id, None)
