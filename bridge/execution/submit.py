"""Validated command submission into an authorized tmux pane."""

import shlex
import uuid

from bridge.common import BridgeError, now, unix_ms
from bridge.execution.lifecycle import EXECUTING, execution_phase
from bridge.config import (
    DEFAULT_TOTAL_BUDGET_MS,
    JOB_CAPTURE_LINES,
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
        if any(ord(character) < 32 or ord(character) == 127 for character in text):
            return "control_character_not_supported"
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
        stream = self.bridge.ensure_terminal_stream(pane)
        read_baseline = getattr(self.bridge.tmux, 'read_logical_lines', self.bridge.tmux.read)
        baseline = read_baseline(pane, JOB_CAPTURE_LINES)
        try:
            baseline_pane_command = (
                self.bridge.tmux.state(pane).get("current_command")
                if hasattr(self.bridge.tmux, "state") else None
            )
        except BridgeError:
            baseline_pane_command = None
        # Publish the task before Enter can run it. Event handling shares this
        # lock, so there is no submitted-but-untracked interrupt window.
        with self.bridge.lock:
            self.bridge.require_lease(pane, generation)
            if stream is not None:
                active = next((existing for existing in self.bridge.jobs.values()
                               if existing['pane'] == pane
                               and execution_phase(existing) == EXECUTING), None)
                if active:
                    raise BridgeError('TERMINAL_JOB_ALREADY_RUNNING', pane=pane,
                                      job_id=active['job_id'])
            job = self.bridge._create_job(
                pane, generation, text, expected_duration_ms, resource_class, baseline,
                baseline_pane_command,
            )
            if stream is not None:
                job['event_stream_pending'] = True
            try:
                if stream is not None:
                    stream.submit(job['job_id'], generation, text)
                elif hasattr(self.bridge.tmux, "submit"):
                    self.bridge.tmux.submit(pane, text)
                else:  # Minimal test doubles and third-party backends.
                    self.bridge.tmux.send_text(pane, text)
                    self.bridge.tmux.send_key(pane, "Enter")
            except Exception:
                job.update(state="FAILED", execution_phase="FINISHED")
                self.bridge.persist_state()
                raise
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
            "job_id": job["job_id"],
            "job_state": job["state"],
        }
