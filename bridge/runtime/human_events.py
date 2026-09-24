"""Human interrupt handling and authority revocation."""

from bridge.common import now, unix_ms

class HumanEventService:
    def __init__(self, bridge):
        self.bridge = bridge

    def handle_human_event(self, event):
        pane = event.get("pane")
        if event.get("type") != "human_interrupt" or not pane:
            return
        with self.bridge.lock:
            self.bridge.event_sequence += 1
            event["seq"] = self.bridge.event_sequence
            self.bridge.interrupt_sources[pane] = {
                "source": "human",
                "event_seq": event["seq"],
                "timestamp": event.get("timestamp") or now(),
            }
            lease = self.bridge.leases.get(pane)
            if lease and lease["state"] == "ACTIVE":
                lease["state"] = "REVOKED"
                lease["revoked_at"] = now()
                lease["revoked_at_ms"] = unix_ms()
                lease["event_seq"] = event["seq"]
                generation = lease["generation"]
                self.bridge.persist_state()
            else:
                generation = None
        self.bridge.record(
            "HUMAN_INTERRUPT",
            pane=pane,
            client=event.get("client", ""),
            event_seq=event["seq"],
        )
        if generation is not None:
            self.bridge.record(
                "LEASE_REVOKE",
                pane=pane,
                generation=generation,
                event_seq=event["seq"],
            )
