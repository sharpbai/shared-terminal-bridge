"""Validated command submission into an authorized tmux pane."""

import shlex
import uuid

from bridge.common import BridgeError, now, unix_ms
from bridge.config import (
    DEFAULT_IDLE_BUDGET_MS,
    DEFAULT_TOTAL_BUDGET_MS,
    HIGH_RESOURCE_CLASSES,
    JOB_CAPTURE_LINES,
    LONG_RUN_APPROVAL_MS,
    MAX_TOTAL_BUDGET_MS,
)


class SubmitService:
    def __init__(self, bridge):
        self.bridge = bridge

    @staticmethod
    def _command_completeness(text: str):
        """Reject only definite local-input incompleteness; never expand or run it."""
        if "\x00" in text:
            return "nul_byte"
        if "\n" in text or "\r" in text:
            return "multiline_not_supported"
        if text.rstrip().endswith("\\"):
            return "trailing_continuation"
        try:
            shlex.split(text, posix=True)
        except ValueError as error:
            if "No closing quotation" in str(error):
                return "unclosed_quote"
        return None

    def terminal_submit(
        self,
        pane: str,
        generation: int,
        text: str,
        expected_duration_ms: int = DEFAULT_TOTAL_BUDGET_MS,
        resource_class: str = "normal",
        long_run_approval_id: str = None,
    ):
        """Type one literal command and press Enter under the same lease check."""
        self.bridge.require_lease(pane, generation)
        incomplete = self.bridge._command_completeness(text)
        if incomplete:
            raise BridgeError("COMMAND_INCOMPLETE", reason=incomplete)
        try:
            expected_duration_ms = int(expected_duration_ms)
            if expected_duration_ms < 1:
                raise ValueError
        except (TypeError, ValueError) as error:
            raise BridgeError("INVALID_EXPECTED_DURATION") from error
        if resource_class not in {"normal", "high_io", "full_scan"}:
            raise BridgeError("INVALID_RESOURCE_CLASS", resource_class=resource_class)
        requires_approval = (
            expected_duration_ms > LONG_RUN_APPROVAL_MS
            or resource_class in HIGH_RESOURCE_CLASSES
        )
        if requires_approval:
            with self.bridge.lock:
                approval = self.bridge.long_run_approvals.get(long_run_approval_id)
                valid = bool(
                    approval
                    and not approval["consumed"]
                    and approval["pane"] == pane
                    and approval["generation"] == generation
                    and approval["command_fingerprint"]
                    == self.bridge._command_fingerprint(text)
                    and approval["expected_duration_ms"] == expected_duration_ms
                    and approval["resource_class"] == resource_class
                )
                if valid:
                    approval["consumed"] = True
            if not valid:
                total_budget_ms = min(
                    MAX_TOTAL_BUDGET_MS,
                    max(expected_duration_ms, DEFAULT_TOTAL_BUDGET_MS),
                )
                request = self.bridge.terminal_long_run_request(
                    pane,
                    generation,
                    text,
                    expected_duration_ms,
                    resource_class,
                    min(DEFAULT_IDLE_BUDGET_MS, total_budget_ms),
                    total_budget_ms,
                )
                raise BridgeError(
                    "LONG_RUN_APPROVAL_REQUIRED",
                    pane=pane,
                    generation=generation,
                    request_id=request["request_id"],
                    interaction="input_required",
                    command=text,
                    command_fingerprint=request["command_fingerprint"],
                    expected_duration_ms=expected_duration_ms,
                    resource_class=resource_class,
                    idle_budget_ms=request["idle_budget_ms"],
                    total_budget_ms=request["total_budget_ms"],
                    prompt=(
                        "请向用户展示完整命令和资源影响；收到后续明确批准消息前不要执行。"
                    ),
                )
        baseline = self.bridge.tmux.read(pane, JOB_CAPTURE_LINES)
        try:
            baseline_pane_command = (
                self.bridge.tmux.state(pane).get("current_command")
                if hasattr(self.bridge.tmux, "state") else None
            )
        except BridgeError:
            baseline_pane_command = None
        if hasattr(self.bridge.tmux, "submit"):
            self.bridge.tmux.submit(pane, text)
        else:  # Minimal test doubles and third-party backends.
            self.bridge.tmux.send_text(pane, text)
            self.bridge.tmux.send_key(pane, "Enter")
        job = self.bridge._create_job(
            pane, generation, text, expected_duration_ms, resource_class, baseline,
            baseline_pane_command,
        )
        byte_count = len(text.encode())
        self.bridge.record(
            "SUBMIT",
            pane=pane,
            generation=generation,
            bytes=byte_count,
            job_id=job["job_id"],
            command=self.bridge._history_command(text),
            command_fingerprint=job["command_fingerprint"],
        )
        return {
            "accepted": True,
            "bytes": byte_count,
            "key": "Enter",
            "expected_duration_ms": expected_duration_ms,
            "resource_class": resource_class,
            "long_running_notice": expected_duration_ms > 30_000,
            "approval_id": long_run_approval_id if requires_approval else None,
            "job_id": job["job_id"],
            "job_state": job["state"],
        }
