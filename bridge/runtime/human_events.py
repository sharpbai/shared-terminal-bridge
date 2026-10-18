"""Human interrupt handling and authority revocation."""

from bridge.common import now, unix_ms
from bridge.prompt_detection import same_prompt_family
from bridge.execution.lifecycle import EXECUTING, FINISHED, INTERRUPTED, execution_phase
from bridge.runtime.admission import Receipt, receive

class HumanEventService:
    def __init__(self, bridge):
        self.bridge = bridge

    @staticmethod
    def _command_in_flight(job, event):
        if execution_phase(job) != EXECUTING:
            return False
        if event.get('ordered'):
            scope = event.get('scope') or {}
            return (job.get('job_id') == scope.get('job_id')
                    and job.get('stream_epoch') == event.get('stream_epoch')
                    and not job.get('event_stream_lost'))
        if job.get('stream_epoch') or job.get('event_stream_pending'):
            return False  # A legacy socket must not overtake the ordered lane.
        # Use the snapshot taken BEFORE delivering C-c, never the screen after
        # it has stopped the process. Legacy events have no timing evidence.
        content = event.get("pre_interrupt_content")
        if content is None:
            return False
        last_line = next((line.strip() for line in reversed(content.splitlines())
                          if line.strip()), "")
        prompt = job.get("baseline_prompt", "")
        if prompt and same_prompt_family(prompt, last_line):
            job["execution_phase"] = FINISHED
            job["state"] = "COMPLETED"
            job["completion_confidence"] = "pre_interrupt_prompt"
            job["completed_at"] = now()
            return False
        return True

    def handle_human_event(self, event):
        pane = event.get("pane")
        if event.get("type") != "human_interrupt" or not pane:
            return
        receipt = event.get('_received')
        if not isinstance(receipt, Receipt):
            receipt = receive()
        with self.bridge.lock:
            self.bridge.event_sequence += 1
            event["seq"] = self.bridge.event_sequence
            lease = self.bridge.leases.get(pane)
            previous_phases = {key: execution_phase(job) for key, job in self.bridge.jobs.items()}
            active_jobs = [job for job in self.bridge.jobs.values()
                           if lease and job.get("pane") == pane
                           and job.get("generation") == lease.get("generation")
                           and self._command_in_flight(job, event)]
            if lease and lease["state"] == "ACTIVE" and active_jobs:
                for job in active_jobs:
                    job["execution_phase"] = INTERRUPTED
                    job["state"] = "INTERRUPTED_BY_HUMAN"
                    job["completion_confidence"] = "authoritative"
                self.bridge.interrupt_sources[pane] = {
                    "source": "human", "event_seq": event["seq"],
                    "timestamp": event.get("timestamp") or now(),
                }
                lease["state"] = "REVOKED"
                lease["revoked_at"] = now()
                lease["revoked_at_ms"] = unix_ms()
                lease["event_seq"] = event["seq"]
                lease['revoked_receipt'] = receipt.as_dict()
                generation = lease["generation"]
                self.bridge.persist_state()
            else:
                generation = None
            changed_jobs = [(key, job) for key, job in self.bridge.jobs.items()
                            if previous_phases[key] != execution_phase(job)]
            if changed_jobs:
                self.bridge.persist_state()
        for job_id, job in changed_jobs:
            self.bridge._signal_job_waits(job_id, job['state'])
        self.bridge.record(
            "HUMAN_INTERRUPT",
            pane=pane,
            client=event.get("client", ""),
            event_seq=event["seq"],
            revoked=generation is not None,
        )
        if generation is not None:
            self.bridge.record(
                "LEASE_REVOKE",
                pane=pane,
                generation=generation,
                event_seq=event["seq"],
            )
