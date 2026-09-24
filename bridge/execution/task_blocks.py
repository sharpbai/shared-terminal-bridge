"""Task-block planning, constrained execution, and direct terminal input."""

import re
import uuid

try:
    from bridge.common import BridgeError, now, unix_ms
    from bridge.config import (
        CONTEXT_CAPTURE_LINES,
        LONG_RUN_APPROVAL_MS,
        TASK_BLOCK_MAX_DURATION_MS,
        TASK_BLOCK_MAX_STEPS,
    )
    from bridge.context_policy import AIContextPolicy
except ModuleNotFoundError:
    from common import BridgeError, now, unix_ms
    from config import (
        CONTEXT_CAPTURE_LINES,
        LONG_RUN_APPROVAL_MS,
        TASK_BLOCK_MAX_DURATION_MS,
        TASK_BLOCK_MAX_STEPS,
    )
    from context_policy import AIContextPolicy


class TaskBlockService:
    def __init__(self, bridge):
        self.bridge = bridge

    def terminal_task_block(
        self,
        pane: str,
        generation: int,
        commands,
        stop_on_error: bool = True,
    ):
        """Create local task metadata without writing anything to the pane.

        Commands are retained only as a count.  Callers must submit every
        visible terminal action separately through terminal_submit/key/type.
        """
        self.bridge.require_lease(pane, generation)
        if not isinstance(commands, list) or not 1 <= len(commands) <= 32:
            raise BridgeError("INVALID_TASK_BLOCK", reason="commands must contain 1..32 items")
        if any(not isinstance(command, str) or not command.strip() for command in commands):
            raise BridgeError("INVALID_TASK_BLOCK", reason="commands must be non-empty strings")
        if any("\x00" in command for command in commands):
            raise BridgeError("INVALID_TASK_BLOCK", reason="commands must not contain NUL")
        total_bytes = sum(len(command.encode()) for command in commands)
        if total_bytes > 16_384:
            raise BridgeError("INVALID_TASK_BLOCK", reason="command bytes exceed 16384")

        block_id = uuid.uuid4().hex
        baseline = self.bridge.tmux.read(pane, CONTEXT_CAPTURE_LINES)
        with self.bridge.lock:
            self.bridge.task_blocks[block_id] = {
                "block_id": block_id,
                "pane": pane,
                "generation": generation,
                "commands": len(commands),
                "stop_on_error": bool(stop_on_error),
                "transport": "none",
                "last_content": baseline,
                "cursor": None,
                "state": "PLANNED",
                "created_at": now(),
            }
        self.bridge.record(
            "TASK_BLOCK_CREATE",
            pane=pane,
            generation=generation,
            block_id=block_id,
            commands=len(commands),
            bytes=total_bytes,
        )
        return {
            "accepted": True,
            "block_id": block_id,
            "pane": pane,
            "generation": generation,
            "commands": len(commands),
            "transport": "none",
            "writes_to_pane": False,
            "explicit_submits_required": True,
            "state": "PLANNED",
        }

    @staticmethod
    def _task_assertion(assertion, content: str):
        if assertion is None:
            return {"passed": True, "type": None}
        if not isinstance(assertion, dict) or len(assertion) != 1:
            raise BridgeError(
                "INVALID_TASK_BLOCK", reason="assert must contain exactly one predicate"
            )
        predicate, value = next(iter(assertion.items()))
        if predicate not in {"contains", "not_contains", "regex"} or not isinstance(value, str):
            raise BridgeError(
                "INVALID_TASK_BLOCK", reason="unsupported assertion predicate"
            )
        if predicate == "contains":
            passed = value in content
        elif predicate == "not_contains":
            passed = value not in content
        else:
            try:
                passed = re.search(value, content) is not None
            except re.error as error:
                raise BridgeError("INVALID_TASK_BLOCK", reason="invalid assertion regex") from error
        return {"passed": passed, "type": predicate, "value": value}

    @staticmethod
    def _compact_task_excerpt(excerpt, max_bytes=2048):
        compact = dict(excerpt or {})
        encoded = compact.get("content", "").encode("utf-8", errors="replace")
        if len(encoded) > max_bytes:
            omitted = len(encoded) - max_bytes
            suffix = encoded[-max_bytes:].decode("utf-8", errors="ignore")
            compact["content"] = f"[... {omitted} task-block bytes omitted ...]\n{suffix}"
            compact["task_block_omitted_bytes"] = omitted
        return compact

    def _normalize_runner_steps(self, steps):
        if not isinstance(steps, list) or not 1 <= len(steps) <= TASK_BLOCK_MAX_STEPS:
            raise BridgeError(
                "INVALID_TASK_BLOCK",
                reason=f"steps must contain 1..{TASK_BLOCK_MAX_STEPS} items",
            )
        normalized = []
        for index, step in enumerate(steps, 1):
            if not isinstance(step, dict):
                raise BridgeError(
                    "INVALID_TASK_BLOCK", reason="each step must be an object"
                )
            text = step.get("text")
            if not isinstance(text, str) or not text.strip():
                raise BridgeError(
                    "INVALID_TASK_BLOCK", reason="step text must be non-empty"
                )
            self.bridge._validate_read_only_command(text)
            try:
                expected = int(step.get("expected_duration_ms", 30_000))
                if not 1 <= expected <= LONG_RUN_APPROVAL_MS:
                    raise ValueError
            except (TypeError, ValueError) as error:
                raise BridgeError(
                    "INVALID_TASK_BLOCK",
                    reason="read-only step expected_duration_ms must be 1..120000",
                ) from error
            self.bridge._task_assertion(step.get("assert"), "")
            normalized.append(
                {
                    "step_id": step.get("step_id") or f"step-{index}",
                    "text": text,
                    "expected_duration_ms": expected,
                    "assert": step.get("assert"),
                }
            )
        return normalized

    def _start_runner_block(self, pane, generation, normalized, max_duration_ms):
        block_id = f"tb_{uuid.uuid4().hex[:12]}"
        block = {
            "block_id": block_id,
            "pane": pane,
            "generation": generation,
            "mode": "read_only_runner_v1",
            "state": "RUNNING",
            "created_at": now(),
            "max_duration_ms": max_duration_ms,
            "steps_total": len(normalized),
            "steps": [],
        }
        with self.bridge.lock:
            self.bridge.task_blocks[block_id] = block
        self.bridge.record(
            "TASK_BLOCK_START",
            pane=pane,
            generation=generation,
            block_id=block_id,
            steps=len(normalized),
            mode=block["mode"],
        )
        return block

    def _run_runner_step(
        self, block, step, pane, generation, remaining, stop_on_error
    ):
        try:
            self.bridge.require_lease(pane, generation)
        except BridgeError as error:
            with self.bridge.lock:
                lease = self.bridge.leases.get(pane) or {}
            block["state"] = (
                "INTERRUPTED" if lease.get("state") == "REVOKED" else "NEEDS_ATTENTION"
            )
            block["stop_reason"] = error.code
            return False
        submitted = self.bridge.terminal_submit(
            pane,
            generation,
            step["text"],
            min(step["expected_duration_ms"], remaining),
            "normal",
        )
        job_id = submitted["job_id"]
        result = self.bridge.terminal_wait_job(job_id, wait_ms=max(1, remaining))
        excerpt = result.get("output_excerpt") or {}
        assertion = self.bridge._task_assertion(
            step["assert"], excerpt.get("content", "")
        )
        block["steps"].append(
            {
                "step_id": step["step_id"],
                "job_id": job_id,
                "state": result["state"],
                "completion_confidence": result.get("completion_confidence"),
                "assertion": assertion,
                "output_ref": f"job://{job_id}",
                "output_excerpt": self.bridge._compact_task_excerpt(excerpt),
            }
        )
        if result["state"] == "COMPLETED" and assertion["passed"]:
            return True
        block["state"] = (
            "INTERRUPTED"
            if result["state"] == "INTERRUPTED_BY_HUMAN"
            else "NEEDS_ATTENTION"
        )
        block["stop_reason"] = (
            result.get("attention_reason")
            or ("assertion_failed" if not assertion["passed"] else result["state"])
        )
        return result["state"] == "COMPLETED" and not stop_on_error

    def terminal_task_block_execute(
        self,
        pane: str,
        generation: int,
        steps,
        max_duration_ms: int = TASK_BLOCK_MAX_DURATION_MS,
        stop_on_error: bool = True,
    ):
        """Run a bounded sequence of conservatively classified read-only jobs."""
        self.bridge.require_lease(pane, generation)
        try:
            max_duration_ms = int(max_duration_ms)
            if not 1 <= max_duration_ms <= TASK_BLOCK_MAX_DURATION_MS:
                raise ValueError
        except (TypeError, ValueError) as error:
            raise BridgeError(
                "INVALID_TASK_BLOCK", reason="max_duration_ms outside supported range"
            ) from error
        normalized = self._normalize_runner_steps(steps)
        started_ms = unix_ms()
        block = self._start_runner_block(
            pane, generation, normalized, max_duration_ms
        )
        block_id = block["block_id"]

        for step in normalized:
            elapsed = unix_ms() - started_ms
            remaining = max_duration_ms - elapsed
            if remaining <= 0:
                block["state"] = "NEEDS_REPLAN"
                block["stop_reason"] = "block_duration_exhausted"
                break
            # Re-check before every side effect so Ctrl+C or a newer turn stops
            # all not-yet-started steps.
            if not self._run_runner_step(
                block, step, pane, generation, remaining, stop_on_error
            ):
                break

        if block["state"] == "RUNNING":
            block["state"] = "COMPLETED"
        block["completed_at"] = now()
        block["elapsed_ms"] = unix_ms() - started_ms
        with self.bridge.lock:
            self.bridge.task_blocks[block_id] = block
        self.bridge.record(
            "TASK_BLOCK_STATE", pane=pane, generation=generation,
            block_id=block_id, state=block["state"],
            steps_completed=len(block["steps"]), stop_reason=block.get("stop_reason"),
        )
        return dict(block)

    def terminal_task_observe(
        self,
        block_id: str,
        max_bytes: int = AIContextPolicy.DEFAULT_MAX_BYTES,
        max_lines: int = AIContextPolicy.DEFAULT_MAX_LINES,
    ):
        try:
            max_bytes = int(max_bytes)
            max_lines = int(max_lines)
            if not 1 <= max_bytes <= AIContextPolicy.MAX_BYTES:
                raise ValueError
            if not 1 <= max_lines <= AIContextPolicy.MAX_LINES:
                raise ValueError
        except (TypeError, ValueError) as error:
            raise BridgeError(
                "INVALID_CONTEXT_BUDGET",
                max_bytes=max_bytes,
                max_lines=max_lines,
            ) from error
        with self.bridge.lock:
            block = self.bridge.task_blocks.get(block_id)
            if block is None:
                raise BridgeError("TASK_BLOCK_NOT_FOUND", block_id=block_id)
            pane = block["pane"]
            previous = block["last_content"]
            generation = block["generation"]
        self.bridge.authorize(pane)
        current = self.bridge.tmux.read(pane, CONTEXT_CAPTURE_LINES)
        result = AIContextPolicy.apply(
            previous,
            current,
            max_bytes=max_bytes,
            max_lines=max_lines,
        )
        with self.bridge.lock:
            next_cursor = uuid.uuid4().hex
            block["cursor"] = next_cursor
            block["last_content"] = current
            lease = self.bridge.leases.get(pane)
            lease_snapshot = dict(lease) if lease else None
        human_override = bool(
            lease_snapshot
            and lease_snapshot.get("state") == "REVOKED"
            and lease_snapshot.get("event_seq") is not None
        )
        if human_override:
            state = "INTERRUPTED"
        elif (
            lease_snapshot
            and lease_snapshot.get("state") == "ACTIVE"
            and lease_snapshot.get("generation") == generation
        ):
            state = "ACTIVE"
        else:
            state = "INACTIVE"
        with self.bridge.lock:
            block["state"] = state
        self.bridge.record("TASK_BLOCK_OBSERVE", pane=pane, block_id=block_id, state=state)
        return {
            "block_id": block_id,
            "pane": pane,
            "state": state,
            "exit_code": None,
            "cursor": next_cursor,
            **result,
            "execution": {"lease": lease_snapshot, "human_override": human_override},
        }

    def terminal_key(self, pane: str, generation: int, key: str):
        self.bridge.require_lease(pane, generation)
        self.bridge.tmux.send_key(pane, key)
        self.bridge.record("KEY", pane=pane, generation=generation, key=key)
        return {"accepted": True, "key": key}

    def terminal_interrupt(self, pane: str, generation: int):
        self.bridge.require_lease(pane, generation)
        self.bridge.tmux.send_key(pane, "C-c")
        interrupt_id = uuid.uuid4().hex
        with self.bridge.lock:
            self.bridge.interrupt_sources[pane] = {
                "source": "agent",
                "interrupt_id": interrupt_id,
                "generation": generation,
                "timestamp": now(),
            }
        self.bridge.record(
            "AGENT_INTERRUPT",
            pane=pane,
            generation=generation,
            interrupt_id=interrupt_id,
        )
        return {"accepted": True, "source": "agent", "interrupt_id": interrupt_id}
