"""Bounded terminal observation and event-driven delta waiting."""

import time
import uuid

try:
    from bridge.common import BridgeError, now
    from bridge.config import (
        CONTEXT_CAPTURE_LINES,
        DEFAULT_IDLE_BUDGET_MS,
        DEFAULT_TOTAL_BUDGET_MS,
        DEFAULT_WAIT_MS,
        MAX_LINES,
        MAX_TOTAL_BUDGET_MS,
        MAX_WAIT_MS,
    )
    from bridge.context_policy import AIContextPolicy
except ModuleNotFoundError:
    from common import BridgeError, now
    from config import (
        CONTEXT_CAPTURE_LINES,
        DEFAULT_IDLE_BUDGET_MS,
        DEFAULT_TOTAL_BUDGET_MS,
        DEFAULT_WAIT_MS,
        MAX_LINES,
        MAX_TOTAL_BUDGET_MS,
        MAX_WAIT_MS,
    )
    from context_policy import AIContextPolicy


class ObservationService:
    def __init__(self, bridge):
        self.bridge = bridge

    def terminal_read(self, pane: str, lines: int = 100):
        if not 1 <= lines <= MAX_LINES:
            raise BridgeError("INVALID_LINE_LIMIT", lines=lines)
        self.bridge.authorize(pane)
        content = self.bridge.tmux.read(pane, lines)
        with self.bridge.lock:
            lease = self.bridge.leases.get(pane)
            lease_snapshot = dict(lease) if lease else None
        self.bridge.record("READ", pane=pane, lines=lines)
        return {
            "pane": pane,
            "lines_requested": lines,
            "content": content,
            "truncated": False,
            "execution": {
                "lease": lease_snapshot,
                "human_override": bool(
                    lease_snapshot
                    and lease_snapshot.get("state") == "REVOKED"
                    and lease_snapshot.get("event_seq") is not None
                ),
                "interrupt_source": self.bridge._interrupt_source(pane, lease_snapshot),
            },
        }

    def terminal_read_delta(
        self,
        pane: str,
        cursor: str = None,
        max_bytes: int = AIContextPolicy.DEFAULT_MAX_BYTES,
        max_lines: int = AIContextPolicy.DEFAULT_MAX_LINES,
        command_echo: str = None,
    ):
        """Return only output added after an opaque Bridge-owned cursor."""
        self.bridge.authorize(pane)
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

        current = self.bridge.tmux.read(pane, CONTEXT_CAPTURE_LINES)
        clock = time.monotonic()
        with self.bridge.lock:
            previous = ""
            budget = {
                "started_monotonic": clock,
                "last_change_monotonic": clock,
                "consecutive_quiet": 0,
                "idle_budget_ms": DEFAULT_IDLE_BUDGET_MS,
                "total_budget_ms": DEFAULT_TOTAL_BUDGET_MS,
            }
            if cursor is not None:
                saved = self.bridge.observation_cursors.get(cursor)
                if saved is None or saved["pane"] != pane:
                    raise BridgeError("OBSERVATION_CURSOR_INVALID", pane=pane)
                previous = saved["content"]
                budget.update(
                    {
                        key: saved[key]
                        for key in budget
                        if key in saved
                    }
                )

        observation = AIContextPolicy.apply(
            previous,
            current,
            max_bytes=max_bytes,
            max_lines=max_lines,
            command_echo=command_echo,
        )
        if not observation["no_change"]:
            budget["last_change_monotonic"] = clock
            budget["consecutive_quiet"] = 0
        with self.bridge.lock:
            next_cursor = self.bridge._replace_observation_cursor(
                cursor, pane, current, budget
            )
            lease = self.bridge.leases.get(pane)
            lease_snapshot = dict(lease) if lease else None
        human_override = bool(
            lease_snapshot
            and lease_snapshot.get("state") == "REVOKED"
            and lease_snapshot.get("event_seq") is not None
        )
        self.bridge.record(
            "READ_DELTA",
            pane=pane,
            cursor=next_cursor,
            raw_delta_lines=observation["raw_delta_lines"],
            returned_lines=observation["returned_lines"],
        )
        return {
            "pane": pane,
            "cursor": next_cursor,
            **observation,
            "execution": {
                "lease": lease_snapshot,
                "human_override": human_override,
                "interrupt_source": self.bridge._interrupt_source(pane, lease_snapshot),
            },
        }

    def _replace_observation_cursor(self, old_cursor, pane, content, budget):
        next_cursor = uuid.uuid4().hex
        self.bridge.observation_cursors[next_cursor] = {
            "pane": pane,
            "content": content,
            "created_at": now(),
            **budget,
        }
        if old_cursor is not None:
            self.bridge.observation_cursors.pop(old_cursor, None)
        while len(self.bridge.observation_cursors) > 256:
            oldest = next(iter(self.bridge.observation_cursors))
            self.bridge.observation_cursors.pop(oldest, None)
        return next_cursor

    def _interrupt_source(self, pane, lease_snapshot=None):
        if (
            lease_snapshot
            and lease_snapshot.get("state") == "REVOKED"
            and lease_snapshot.get("event_seq") is not None
        ):
            return "human"
        event = getattr(self.bridge, "interrupt_sources", {}).get(pane)
        return event.get("source") if event else None

    @staticmethod
    def _validate_wait_budgets(
        wait_ms, idle_budget_ms, total_budget_ms, max_bytes, max_lines
    ):
        try:
            values = tuple(
                int(value)
                for value in (
                    wait_ms, idle_budget_ms, total_budget_ms, max_bytes, max_lines
                )
            )
            wait_ms, idle_budget_ms, total_budget_ms, max_bytes, max_lines = values
            if not 1 <= wait_ms <= MAX_WAIT_MS:
                raise ValueError
            if not 1 <= idle_budget_ms <= MAX_TOTAL_BUDGET_MS:
                raise ValueError
            if not 1 <= total_budget_ms <= MAX_TOTAL_BUDGET_MS:
                raise ValueError
            if idle_budget_ms > total_budget_ms:
                raise ValueError
            if not 1 <= max_bytes <= AIContextPolicy.MAX_BYTES:
                raise ValueError
            if not 1 <= max_lines <= AIContextPolicy.MAX_LINES:
                raise ValueError
            return values
        except (TypeError, ValueError) as error:
            raise BridgeError("INVALID_WAIT_BUDGET") from error

    def _wait_for_pane_change(self, pane, previous, deadline):
        while True:
            current = self.bridge.tmux.read(pane, CONTEXT_CAPTURE_LINES)
            changed = current != previous
            with self.bridge.lock:
                lease = self.bridge.leases.get(pane)
                lease_snapshot = dict(lease) if lease else None
            human_override = bool(
                lease_snapshot
                and lease_snapshot.get("state") == "REVOKED"
                and lease_snapshot.get("event_seq") is not None
            )
            if changed or human_override or time.monotonic() >= deadline:
                return current, changed, human_override, lease_snapshot
            time.sleep(0.25)

    @staticmethod
    def _classify_wait(
        changed,
        human_override,
        consecutive_quiet,
        idle_elapsed_ms,
        total_elapsed_ms,
        idle_budget_ms,
        total_budget_ms,
    ):
        if human_override:
            return "INTERRUPTED"
        if (
            consecutive_quiet >= 2
            or idle_elapsed_ms >= idle_budget_ms
            or total_elapsed_ms >= total_budget_ms
        ):
            return "BUDGET_EXHAUSTED"
        return "CHANGED" if changed else "QUIET"

    def terminal_wait_delta(
        self,
        pane: str,
        cursor: str,
        wait_ms: int = DEFAULT_WAIT_MS,
        idle_budget_ms: int = DEFAULT_IDLE_BUDGET_MS,
        total_budget_ms: int = DEFAULT_TOTAL_BUDGET_MS,
        max_bytes: int = AIContextPolicy.DEFAULT_MAX_BYTES,
        max_lines: int = AIContextPolicy.DEFAULT_MAX_LINES,
        command_echo: str = None,
    ):
        """Wait locally for pane output without writing or inferring completion."""
        self.bridge.authorize(pane)
        (
            wait_ms,
            idle_budget_ms,
            total_budget_ms,
            max_bytes,
            max_lines,
        ) = self._validate_wait_budgets(
            wait_ms, idle_budget_ms, total_budget_ms, max_bytes, max_lines
        )

        with self.bridge.lock:
            saved = self.bridge.observation_cursors.get(cursor)
            if saved is None or saved["pane"] != pane:
                raise BridgeError("OBSERVATION_CURSOR_INVALID", pane=pane)
            previous = saved["content"]
            started = saved.get("started_monotonic", time.monotonic())
            last_change = saved.get("last_change_monotonic", started)
            consecutive_quiet = saved.get("consecutive_quiet", 0)

        wait_started = time.monotonic()
        deadline = wait_started + wait_ms / 1000
        current, changed, human_override, lease_snapshot = (
            self._wait_for_pane_change(pane, previous, deadline)
        )

        clock = time.monotonic()
        observation = AIContextPolicy.apply(
            previous,
            current,
            max_bytes=max_bytes,
            max_lines=max_lines,
            command_echo=command_echo,
        )
        if changed:
            last_change = clock
            consecutive_quiet = 0
        else:
            consecutive_quiet += 1
        total_elapsed_ms = int((clock - started) * 1000)
        idle_elapsed_ms = int((clock - last_change) * 1000)
        state = self._classify_wait(
            changed,
            human_override,
            consecutive_quiet,
            idle_elapsed_ms,
            total_elapsed_ms,
            idle_budget_ms,
            total_budget_ms,
        )

        budget = {
            "started_monotonic": started,
            "last_change_monotonic": last_change,
            "consecutive_quiet": consecutive_quiet,
            "idle_budget_ms": idle_budget_ms,
            "total_budget_ms": total_budget_ms,
        }
        with self.bridge.lock:
            next_cursor = self.bridge._replace_observation_cursor(
                cursor, pane, current, budget
            )
        self.bridge.record(
            "WAIT_DELTA",
            pane=pane,
            state=state,
            waited_ms=int((clock - wait_started) * 1000),
            consecutive_quiet=consecutive_quiet,
        )
        return {
            "pane": pane,
            "cursor": next_cursor,
            "state": state,
            "waited_ms": int((clock - wait_started) * 1000),
            "budget": {
                "idle_budget_ms": idle_budget_ms,
                "total_budget_ms": total_budget_ms,
                "idle_elapsed_ms": idle_elapsed_ms,
                "total_elapsed_ms": total_elapsed_ms,
                "consecutive_quiet": consecutive_quiet,
            },
            **observation,
            "execution": {
                "lease": lease_snapshot,
                "human_override": human_override,
                "interrupt_source": self.bridge._interrupt_source(pane, lease_snapshot),
            },
        }
