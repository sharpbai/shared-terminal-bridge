"""Execution leases and explicit long-run approval lifecycle."""

import hashlib
import re
import uuid

try:
    from bridge.common import BridgeError, now, unix_ms
    from bridge.config import (
        DEFAULT_IDLE_BUDGET_MS,
        LONG_RUN_REQUEST_TTL_MS,
        MAX_TOTAL_BUDGET_MS,
    )
except ModuleNotFoundError:
    from common import BridgeError, now, unix_ms
    from config import (
        DEFAULT_IDLE_BUDGET_MS,
        LONG_RUN_REQUEST_TTL_MS,
        MAX_TOTAL_BUDGET_MS,
    )


class AuthorityService:
    def __init__(self, bridge):
        self.bridge = bridge

    def authorize(self, pane: str):
        if pane not in self.bridge.allowed_panes:
            self.bridge.record("ACCESS_DENY", pane=pane)
            raise BridgeError("PANE_ACCESS_DENIED", pane=pane)

    def require_lease(self, pane: str, generation: int):
        self.bridge.authorize(pane)
        with self.bridge.lock:
            lease = self.bridge.leases.get(pane)
            if (
                lease is None
                or lease["state"] != "ACTIVE"
                or lease["generation"] != generation
            ):
                self.bridge.record(
                    "ACTION_DENY",
                    pane=pane,
                    generation=generation,
                    lease=lease,
                )
                raise BridgeError(
                    "EXECUTION_LEASE_INVALID",
                    pane=pane,
                    generation=generation,
                    lease=lease,
                )
            return dict(lease)

    def acquire_execution(
        self,
        pane: str,
        thread_id: str = None,
        turn_id: str = None,
        turn_started_at_ms: int = None,
    ):
        self.bridge.authorize(pane)
        turn_values = (thread_id, turn_id, turn_started_at_ms)
        if any(value is not None for value in turn_values) and not all(
            value is not None for value in turn_values
        ):
            raise BridgeError("INCOMPLETE_TURN_IDENTITY")
        with self.bridge.lock:
            previous = self.bridge.leases.get(pane)
            if previous and previous.get("state") == "ACTIVE" and thread_id:
                previous_auth = previous.get("authorization") or {}
                if (
                    previous_auth.get("thread_id") == thread_id
                    and previous_auth.get("turn_id") == turn_id
                    and previous_auth.get("turn_started_at_ms") == turn_started_at_ms
                ):
                    result = dict(previous)
                    result["idempotent"] = True
                    self.bridge.record(
                        "LEASE_REUSE",
                        pane=pane,
                        generation=previous.get("generation"),
                    )
                    return result
                if (
                    previous_auth.get("thread_id") != thread_id
                    or not previous_auth.get("turn_started_at_ms")
                    or turn_started_at_ms <= previous_auth["turn_started_at_ms"]
                ):
                    raise BridgeError(
                        "EXECUTION_LEASE_ALREADY_ACTIVE",
                        pane=pane,
                        generation=previous.get("generation"),
                    )
            if previous and previous.get("state") == "REVOKED" and thread_id:
                previous_auth = previous.get("authorization") or {}
                revoked_at_ms = previous.get("revoked_at_ms")
                if (
                    previous_auth.get("thread_id") == thread_id
                    and (
                        previous_auth.get("turn_id") == turn_id
                        or revoked_at_ms is None
                        or turn_started_at_ms <= revoked_at_ms
                    )
                ):
                    raise BridgeError(
                        "NEW_USER_TURN_REQUIRED",
                        pane=pane,
                        thread_id=thread_id,
                        turn_id=turn_id,
                        turn_started_at_ms=turn_started_at_ms,
                        revoked_at_ms=revoked_at_ms,
                    )
            generation = self.bridge.generations.get(pane, 0) + 1
            self.bridge.generations[pane] = generation
            lease = {
                "pane": pane,
                "generation": generation,
                "state": "ACTIVE",
                "issued_at": now(),
            }
            if thread_id:
                lease["authorization"] = {
                    "thread_id": thread_id,
                    "turn_id": turn_id,
                    "turn_started_at_ms": turn_started_at_ms,
                }
            self.bridge.leases[pane] = lease
            self.bridge.persist_state()
        if previous and previous.get("state") == "ACTIVE":
            self.bridge.record(
                "LEASE_SUPERSEDE",
                pane=pane,
                previous_generation=previous.get("generation"),
                generation=generation,
            )
        self.bridge.record("LEASE_ACQUIRE", pane=pane, generation=generation)
        return dict(lease)

    def release_execution(self, pane: str, generation: int):
        self.bridge.require_lease(pane, generation)
        with self.bridge.lock:
            self.bridge.leases[pane]["state"] = "RELEASED"
            lease = dict(self.bridge.leases[pane])
            self.bridge.persist_state()
        self.bridge.record("LEASE_RELEASE", pane=pane, generation=generation)
        return lease

    def execution_status(self, pane: str):
        self.bridge.authorize(pane)
        with self.bridge.lock:
            lease = self.bridge.leases.get(pane)
            return {"lease": dict(lease) if lease else None}

    def terminal_type(self, pane: str, generation: int, text: str):
        self.bridge.require_lease(pane, generation)
        self.bridge.tmux.send_text(pane, text)
        self.bridge.record(
            "TYPE",
            pane=pane,
            generation=generation,
            bytes=len(text.encode()),
        )
        return {"accepted": True, "bytes": len(text.encode())}
