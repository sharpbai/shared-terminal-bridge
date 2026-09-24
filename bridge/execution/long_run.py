"""Explicit approval lifecycle and budgets for long-running commands."""

import hashlib
import re
import uuid

from bridge.common import BridgeError, now, unix_ms
from bridge.config import (
    DEFAULT_IDLE_BUDGET_MS,
    LONG_RUN_REQUEST_TTL_MS,
    MAX_TOTAL_BUDGET_MS,
)


class LongRunService:
    def __init__(self, bridge):
        self.bridge = bridge

    @staticmethod
    def _command_fingerprint(text: str):
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _history_command(text: str):
        sensitive = re.compile(
            r"(password|passwd|api[_-]?key|access[_-]?token|secret)\s*(=|:)|"
            r"\b(export|setenv)\b.*(token|secret|password|key)",
            re.IGNORECASE,
        )
        return "[REDACTED_SENSITIVE_COMMAND]" if sensitive.search(text) else text

    @staticmethod
    def _validate_long_run_budget(
        expected_duration_ms, idle_budget_ms=None, total_budget_ms=None
    ):
        try:
            expected_duration_ms = int(expected_duration_ms)
            if total_budget_ms is None:
                total_budget_ms = min(
                    MAX_TOTAL_BUDGET_MS,
                    max(expected_duration_ms, expected_duration_ms * 2),
                )
            if idle_budget_ms is None:
                idle_budget_ms = min(
                    total_budget_ms,
                    max(DEFAULT_IDLE_BUDGET_MS, expected_duration_ms // 2),
                )
            idle_budget_ms = int(idle_budget_ms)
            total_budget_ms = int(total_budget_ms)
            if expected_duration_ms < 1 or not 1 <= idle_budget_ms <= total_budget_ms:
                raise ValueError
            if (
                expected_duration_ms > MAX_TOTAL_BUDGET_MS
                or total_budget_ms > MAX_TOTAL_BUDGET_MS
                or total_budget_ms < expected_duration_ms
            ):
                raise ValueError
        except (TypeError, ValueError) as error:
            raise BridgeError("INVALID_LONG_RUN_BUDGET") from error
        return expected_duration_ms, idle_budget_ms, total_budget_ms

    def _long_run_request(self, request_id: str):
        with self.bridge.lock:
            request = self.bridge.long_run_requests.get(request_id)
        if request is None:
            raise BridgeError("LONG_RUN_REQUEST_NOT_FOUND", request_id=request_id)
        if request.get("expires_at_ms", 0) <= unix_ms():
            with self.bridge.lock:
                request["status"] = "EXPIRED"
                self.bridge.persist_state()
            raise BridgeError("LONG_RUN_REQUEST_EXPIRED", request_id=request_id)
        return request

    def terminal_long_run_request(
        self,
        pane: str,
        generation: int,
        text: str,
        expected_duration_ms: int,
        resource_class: str,
        idle_budget_ms: int = None,
        total_budget_ms: int = None,
    ):
        """Create a durable, non-executing approval request for one command."""
        lease = self.bridge.require_lease(pane, generation)
        if not text or "\x00" in text:
            raise BridgeError("INVALID_LONG_RUN_COMMAND")
        (
            expected_duration_ms,
            idle_budget_ms,
            total_budget_ms,
        ) = self.bridge._validate_long_run_budget(
            expected_duration_ms, idle_budget_ms, total_budget_ms
        )
        if resource_class not in {"normal", "high_io", "full_scan"}:
            raise BridgeError("INVALID_RESOURCE_CLASS", resource_class=resource_class)
        fingerprint = self.bridge._command_fingerprint(text)
        with self.bridge.lock:
            existing = next(
                (
                    item for item in self.bridge.long_run_requests.values()
                    if item.get("pane") == pane
                    and item.get("command_fingerprint") == fingerprint
                    and item.get("expected_duration_ms") == expected_duration_ms
                    and item.get("resource_class") == resource_class
                    and item.get("status") in {"PENDING", "APPROVED"}
                    and item.get("expires_at_ms", 0) > unix_ms()
                ),
                None,
            )
            if existing is not None:
                return {
                    **existing,
                    "interaction": "input_required",
                    "prompt": (
                        "请向用户展示完整命令和资源影响；收到后续明确批准消息前不要执行。"
                    ),
                }
            request_id = f"lr_{uuid.uuid4().hex[:12]}"
            requested_at_ms = unix_ms()
            request = {
                "request_id": request_id,
                "status": "PENDING",
                "pane": pane,
                "requested_generation": generation,
                "command": text,
                "command_fingerprint": fingerprint,
                "expected_duration_ms": expected_duration_ms,
                "resource_class": resource_class,
                "idle_budget_ms": idle_budget_ms,
                "total_budget_ms": total_budget_ms,
                "authorization": dict(lease.get("authorization") or {}),
                "requested_at": now(),
                "requested_at_ms": requested_at_ms,
                "expires_at_ms": requested_at_ms + LONG_RUN_REQUEST_TTL_MS,
            }
            self.bridge.long_run_requests[request_id] = request
            self.bridge.persist_state()
        self.bridge.record(
            "LONG_RUN_REQUEST",
            pane=pane,
            generation=generation,
            request_id=request_id,
            command_fingerprint=fingerprint,
            resource_class=resource_class,
        )
        return {
            **request,
            "interaction": "input_required",
            "prompt": "请向用户展示完整命令和资源影响；收到后续明确批准消息前不要执行。",
        }

    def terminal_long_run_requests(self, status: str = None):
        """List approval requests for the local administrative CLI."""
        if status is not None and status not in {
            "PENDING", "APPROVED", "REJECTED", "CONSUMED", "EXPIRED"
        }:
            raise BridgeError("INVALID_LONG_RUN_STATUS", status=status)
        current_ms = unix_ms()
        changed = False
        with self.bridge.lock:
            for request in self.bridge.long_run_requests.values():
                if (
                    request.get("status") in {"PENDING", "APPROVED"}
                    and request.get("expires_at_ms", 0) <= current_ms
                ):
                    request["status"] = "EXPIRED"
                    changed = True
            if changed:
                self.bridge.persist_state()
            requests = [
                dict(request) for request in self.bridge.long_run_requests.values()
                if status is None or request.get("status") == status
            ]
        requests.sort(key=lambda item: item.get("requested_at_ms", 0), reverse=True)
        return {"requests": requests}

    def terminal_long_run_decide(self, request_id: str, decision: str):
        """Record a trusted local administrator's approve/reject decision."""
        if decision not in {"approve", "reject"}:
            raise BridgeError("INVALID_LONG_RUN_DECISION", decision=decision)
        request = self.bridge._long_run_request(request_id)
        if request.get("status") not in {"PENDING", "APPROVED"}:
            raise BridgeError(
                "LONG_RUN_REQUEST_NOT_PENDING",
                request_id=request_id,
                status=request.get("status"),
            )
        with self.bridge.lock:
            request["status"] = "APPROVED" if decision == "approve" else "REJECTED"
            request["decision_source"] = "local_cli"
            request["decided_at"] = now()
            self.bridge.persist_state()
        self.bridge.record(
            "LONG_RUN_DECIDE",
            pane=request["pane"],
            request_id=request_id,
            decision=decision,
            source="local_cli",
        )
        return dict(request)

    def terminal_long_run_approve(
        self,
        pane: str,
        generation: int,
        text: str = None,
        expected_duration_ms: int = None,
        resource_class: str = None,
        idle_budget_ms: int = None,
        total_budget_ms: int = None,
        request_id: str = None,
    ):
        """Record explicit, one-command long-run consent in local state."""
        self.bridge.require_lease(pane, generation)
        if request_id is not None:
            pending = self.bridge._long_run_request(request_id)
        else:
            if text is None:
                raise BridgeError("LONG_RUN_REQUEST_ID_REQUIRED")
            fingerprint = self.bridge._command_fingerprint(text)
            with self.bridge.lock:
                pending = next(
                    (
                        item for item in self.bridge.long_run_requests.values()
                        if item.get("pane") == pane
                        and item.get("command_fingerprint") == fingerprint
                        and item.get("status") == "PENDING"
                    ),
                    None,
                )
            if pending is None:
                raise BridgeError("LONG_RUN_REQUEST_NOT_FOUND")
            request_id = pending["request_id"]
        if pending.get("pane") != pane:
            raise BridgeError("LONG_RUN_REQUEST_PANE_MISMATCH", request_id=request_id)
        text = pending["command"]
        fingerprint = pending["command_fingerprint"]
        expected_duration_ms = pending["expected_duration_ms"]
        resource_class = pending["resource_class"]
        idle_budget_ms = pending["idle_budget_ms"]
        total_budget_ms = pending["total_budget_ms"]
        with self.bridge.lock:
            lease = self.bridge.leases.get(pane) or {}
            authorization = lease.get("authorization") or {}
        pending_authorization = (pending or {}).get("authorization") or {}
        locally_approved = (
            pending.get("status") == "APPROVED"
            and pending.get("decision_source") == "local_cli"
        )
        later_user_turn = bool(
            authorization.get("turn_id")
            and pending_authorization.get("turn_id")
            and authorization.get("thread_id") == pending_authorization.get("thread_id")
            and authorization.get("turn_id") != pending_authorization.get("turn_id")
            and authorization.get("turn_started_at_ms", 0)
            > pending_authorization.get("turn_started_at_ms", 0)
        )
        if pending.get("status") == "REJECTED":
            raise BridgeError("LONG_RUN_REQUEST_REJECTED", request_id=request_id)
        if not locally_approved and not later_user_turn:
            raise BridgeError(
                "LONG_RUN_APPROVAL_NEW_USER_TURN_REQUIRED",
                pane=pane,
                request_id=request_id,
                command_fingerprint=fingerprint,
            )
        approval_id = uuid.uuid4().hex
        approval = {
            "approval_id": approval_id,
            "request_id": request_id,
            "pane": pane,
            "generation": generation,
            "command": text,
            "command_fingerprint": fingerprint,
            "expected_duration_ms": expected_duration_ms,
            "resource_class": resource_class,
            "idle_budget_ms": idle_budget_ms,
            "total_budget_ms": total_budget_ms,
            "created_at": now(),
            "consumed": False,
        }
        with self.bridge.lock:
            self.bridge.long_run_approvals[approval_id] = approval
            pending["status"] = "CONSUMED"
            pending["consumed_at"] = now()
            self.bridge.persist_state()
        self.bridge.record(
            "LONG_RUN_APPROVE",
            pane=pane,
            generation=generation,
            approval_id=approval_id,
            request_id=request_id,
            command_fingerprint=approval["command_fingerprint"],
            resource_class=resource_class,
            total_budget_ms=total_budget_ms,
        )
        return dict(approval)
