"""Terminal job creation, monitoring, waiting, and submission."""

import shlex
import subprocess
import sys
import threading
import uuid

try:
    from bridge.common import BridgeError, now, unix_ms
    from bridge.config import (
        DEFAULT_IDLE_BUDGET_MS,
        DEFAULT_TOTAL_BUDGET_MS,
        HIGH_RESOURCE_CLASSES,
        JOB_CAPTURE_LINES,
        JOB_POLL_INTERVAL_SECONDS,
        JOB_PROMPT_STABLE_MS,
        JOB_TERMINAL_STATES,
        LONG_RUN_APPROVAL_MS,
        MAX_JOB_WAIT_MS,
        MAX_RETAINED_JOBS,
        MAX_TOTAL_BUDGET_MS,
        REMOTE_TRANSPORT_COMMANDS,
    )
    from bridge.context_policy import AIContextPolicy
except ModuleNotFoundError:
    from common import BridgeError, now, unix_ms
    from config import (
        DEFAULT_IDLE_BUDGET_MS,
        DEFAULT_TOTAL_BUDGET_MS,
        HIGH_RESOURCE_CLASSES,
        JOB_CAPTURE_LINES,
        JOB_POLL_INTERVAL_SECONDS,
        JOB_PROMPT_STABLE_MS,
        JOB_TERMINAL_STATES,
        LONG_RUN_APPROVAL_MS,
        MAX_JOB_WAIT_MS,
        MAX_RETAINED_JOBS,
        MAX_TOTAL_BUDGET_MS,
        REMOTE_TRANSPORT_COMMANDS,
    )
    from context_policy import AIContextPolicy


class JobService:
    def __init__(self, bridge):
        self.bridge = bridge

    @staticmethod
    def _last_nonempty_line(content: str):
        return next(
            (line.strip() for line in reversed(AIContextPolicy.normalize(content)) if line.strip()),
            "",
        )

    @staticmethod
    def _job_hard_deadline_ms(submitted_at_ms: int, expected_duration_ms: int):
        allowance = max(expected_duration_ms * 3, 20 * 60 * 1000)
        return submitted_at_ms + allowance

    def _create_job(
        self, pane, generation, text, expected_duration_ms, resource_class,
        baseline, baseline_pane_command=None,
    ):
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        submitted_at_ms = unix_ms()
        job = {
            "job_id": job_id,
            "pane": pane,
            "generation": generation,
            "command": text,
            "command_fingerprint": self.bridge._command_fingerprint(text),
            "expected_duration_ms": expected_duration_ms,
            "resource_class": resource_class,
            "state": "RUNNING",
            "completion_confidence": None,
            "submitted_at": now(),
            "submitted_at_ms": submitted_at_ms,
            "hard_deadline_ms": self.bridge._job_hard_deadline_ms(
                submitted_at_ms, expected_duration_ms
            ),
            "strategy_review_at_ms": submitted_at_ms + 10 * 60 * 1000,
            "baseline_content": baseline,
            "baseline_prompt": self.bridge._last_nonempty_line(baseline),
            "baseline_pane_command": baseline_pane_command,
            "last_content": baseline,
            "last_change_ms": submitted_at_ms,
            "last_activity_at": now(),
            "progress": None,
            "last_evidence_lines": [],
            "output_excerpt": None,
            "last_meaningful_activity_at": None,
            "notification_sent": False,
        }
        with self.bridge.lock:
            self.bridge.jobs[job_id] = job
            while len(self.bridge.jobs) > MAX_RETAINED_JOBS:
                removable = next(
                    (
                        existing_id for existing_id, existing in self.bridge.jobs.items()
                        if existing_id != job_id and existing.get("state") != "RUNNING"
                    ),
                    None,
                )
                if removable is None:
                    break
                self.bridge.jobs.pop(removable, None)
            self.bridge.persist_state()
        self.bridge.record(
            "JOB_CREATE", pane=pane, generation=generation, job_id=job_id,
            command=self.bridge._history_command(text),
            command_fingerprint=job["command_fingerprint"],
            expected_duration_ms=expected_duration_ms,
            resource_class=resource_class,
        )
        return job

    @staticmethod
    def _interaction_prompt(delta_content: str):
        lines = [line for line in AIContextPolicy.normalize(delta_content) if line.strip()]
        tail = "\n".join(lines[-6:]).lower()
        patterns = (
            "password for ", "password:", "[y/n]", "[y/n]:", "(y/n)",
            "press enter", "are you sure you want to continue connecting",
        )
        return next((pattern for pattern in patterns if pattern in tail), None)


    def _notify_job(self, job):
        if (
            sys.platform != "darwin"
            or job.get("notification_sent")
            or (
                job.get("expected_duration_ms", 0) <= 30_000
                and job.get("resource_class") not in HIGH_RESOURCE_CLASSES
            )
        ):
            return
        title = "Shared Terminal Bridge"
        elapsed = max(0, unix_ms() - job["submitted_at_ms"]) // 1000
        message = f"{job['job_id']} {job['state']}，已运行 {elapsed} 秒"
        escape = lambda value: value.replace("\\", "\\\\").replace('"', '\\"')
        script = (
            f'display notification "{escape(message)}" '
            f'with title "{escape(title)}"'
        )
        try:
            subprocess.run(
                ["osascript", "-e", script],
                check=False,
                capture_output=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        with self.bridge.lock:
            job["notification_sent"] = True
            self.bridge.persist_state()

    def _job_evidence(self, job, current, baseline, lease_snapshot):
        pane_command = None
        if hasattr(self.bridge.tmux, "state"):
            try:
                pane_command = self.bridge.tmux.state(job["pane"]).get(
                    "current_command"
                )
            except BridgeError:
                pass
        observation = AIContextPolicy.apply(
            baseline,
            current,
            max_bytes=AIContextPolicy.DEFAULT_MAX_BYTES,
            max_lines=AIContextPolicy.DEFAULT_MAX_LINES,
            command_echo=job["command"],
        )
        output_excerpt = AIContextPolicy.job_output(
            baseline, current, job["command"]
        )
        evidence_lines = [
            line
            for line in AIContextPolicy.normalize(observation["content"])
            if line.strip() and not line.strip().endswith(job["command"].strip())
        ][-5:]
        return {
            "pane_command": pane_command,
            "output_excerpt": output_excerpt,
            "human_override": bool(
                lease_snapshot
                and lease_snapshot.get("state") == "REVOKED"
                and lease_snapshot.get("event_seq") is not None
                and lease_snapshot.get("generation") == job["generation"]
            ),
            # Prompt detection is job-local. A generic delta can contain stale
            # pane history after scrollback shifts and must not trigger it.
            "prompt": self.bridge._interaction_prompt(output_excerpt["content"]),
            "last_line": self.bridge._last_nonempty_line(current),
            "evidence_lines": evidence_lines,
        }

    @staticmethod
    def _apply_job_state(job, evidence, current, baseline, current_ms):
        if evidence["human_override"]:
            job["state"] = "INTERRUPTED_BY_HUMAN"
            job["completion_confidence"] = "authoritative"
        elif evidence["prompt"]:
            job["state"] = "NEEDS_ATTENTION"
            job["attention_reason"] = evidence["prompt"]
            job["completion_confidence"] = "heuristic"
        elif (
            job.get("baseline_pane_command") in REMOTE_TRANSPORT_COMMANDS
            and evidence["pane_command"]
            and evidence["pane_command"] != job.get("baseline_pane_command")
        ):
            job["state"] = "NEEDS_ATTENTION"
            job["attention_reason"] = "session_context_changed"
            job["completion_confidence"] = "tmux_state"
        elif (
            job["baseline_prompt"]
            and evidence["last_line"] == job["baseline_prompt"]
            and current != baseline
            and current_ms - job["last_change_ms"] >= JOB_PROMPT_STABLE_MS
        ):
            job["state"] = "COMPLETED"
            job["completion_confidence"] = "prompt_returned"
            job["completed_at"] = now()
        elif current_ms >= job["hard_deadline_ms"]:
            job["state"] = "HUMAN_DECISION_REQUIRED"
            job["completion_confidence"] = "deadline"

    def _publish_terminal_job(self, job):
        if job["state"] not in JOB_TERMINAL_STATES:
            return
        self.bridge.record(
            "JOB_STATE",
            pane=job["pane"],
            job_id=job["job_id"],
            state=job["state"],
            attention_reason=job.get("attention_reason"),
            completion_confidence=job.get("completion_confidence"),
            output_excerpt=(job.get("output_excerpt") or {}).get("content", ""),
        )
        self.bridge._signal_job_waits(job["job_id"], job["state"])
        self.bridge._notify_job(job)

    def _refresh_job(self, job_id: str):
        with self.bridge.lock:
            job = self.bridge.jobs.get(job_id)
            if job is None:
                raise BridgeError("TERMINAL_JOB_NOT_FOUND", job_id=job_id)
            if job["state"] in JOB_TERMINAL_STATES:
                return job
            pane = job["pane"]
            previous = job["last_content"]
            baseline = job["baseline_content"]
            lease = self.bridge.leases.get(pane)
            lease_snapshot = dict(lease) if lease else None
        try:
            current = self.bridge.tmux.read(pane, JOB_CAPTURE_LINES)
        except BridgeError as error:
            current_ms = unix_ms()
            state = job["state"]
            if current_ms >= job["hard_deadline_ms"]:
                with self.bridge.lock:
                    job["state"] = "HUMAN_DECISION_REQUIRED"
                    job["completion_confidence"] = "deadline"
                    job["attention_reason"] = "pane_unavailable_at_hard_deadline"
                    self.bridge.persist_state()
                    state = job["state"]
                self.bridge.record(
                    "JOB_STATE",
                    pane=pane,
                    job_id=job_id,
                    state=state,
                    reason=error.code,
                )
                self.bridge._signal_job_waits(job_id, state)
                self.bridge._notify_job(job)
            return job
        current_ms = unix_ms()
        changed = current != previous
        evidence = self._job_evidence(job, current, baseline, lease_snapshot)
        with self.bridge.lock:
            if changed:
                job["last_content"] = current
                job["output_excerpt"] = evidence["output_excerpt"]
                job["last_change_ms"] = current_ms
                job["last_activity_at"] = now()
                if evidence["evidence_lines"]:
                    job["last_evidence_lines"] = evidence["evidence_lines"]
                    job["last_meaningful_activity_at"] = now()
            self._apply_job_state(job, evidence, current, baseline, current_ms)
            state = job["state"]
            if state in JOB_TERMINAL_STATES:
                self.bridge.persist_state()
        self._publish_terminal_job(job)
        return job

    def _job_result(self, job, include_output=False):
        current_ms = unix_ms()
        result = {
            key: job.get(key) for key in (
                "job_id", "pane", "generation", "command", "command_fingerprint",
                "expected_duration_ms", "resource_class", "state",
                "completion_confidence", "submitted_at", "hard_deadline_ms",
                "strategy_review_at_ms", "last_activity_at", "progress",
                "last_meaningful_activity_at", "last_evidence_lines",
                "attention_reason", "completed_at", "output_excerpt",
            )
        }
        result["elapsed_ms"] = max(0, current_ms - job["submitted_at_ms"])
        result["hard_deadline_remaining_ms"] = max(
            0, job["hard_deadline_ms"] - current_ms
        )
        excerpt = job.get("output_excerpt") or {}
        result["output_complete"] = (
            job.get("state") == "COMPLETED"
            and not bool(excerpt.get("omitted_lines") or excerpt.get("omitted_bytes"))
        )
        result["recommended_action"] = {
            "COMPLETED": "CONTINUE",
            "INTERRUPTED_BY_HUMAN": "STOP_CURRENT_TURN",
            "NEEDS_ATTENTION": "MODEL_OR_HUMAN_DECISION",
            "HUMAN_DECISION_REQUIRED": "HUMAN_DECISION",
            "RUNNING": "WAIT",
        }.get(job.get("state"), "INSPECT")
        if include_output:
            result["observation"] = AIContextPolicy.apply(
                job["baseline_content"],
                job["last_content"],
                max_bytes=AIContextPolicy.DEFAULT_MAX_BYTES,
                max_lines=AIContextPolicy.DEFAULT_MAX_LINES,
                command_echo=job["command"],
            )
        return result


    def job_monitor_loop(self):
        while not self.bridge.stop_event.is_set():
            with self.bridge.lock:
                running = [
                    job_id for job_id, job in self.bridge.jobs.items()
                    if job.get("state") == "RUNNING"
                ]
            for job_id in running:
                try:
                    self.bridge._refresh_job(job_id)
                except BridgeError:
                    continue
            self.bridge.stop_event.wait(JOB_POLL_INTERVAL_SECONDS)
