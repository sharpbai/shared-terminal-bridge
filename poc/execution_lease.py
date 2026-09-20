#!/usr/bin/env python3
"""PoC: revoke a pane-scoped execution lease on Human Ctrl+C."""

import dataclasses
import pathlib
import subprocess
import threading

from human_event_socket import (
    EventReceiver,
    install_binding,
    show_events,
    tmux,
)


TMUX_SOCKET = "execution-lease-poc"
SESSION = "execution-lease-poc"
EVENT_SOCKET = pathlib.Path("/tmp/shared-terminal-execution-lease.sock")
GENERATION = 1
ALLOWED_MARKER = "LEASE_GEN_1_ACTION_ALLOWED"
DENIED_MARKER = "STALE_ACTION_SHOULD_NOT_RUN"


@dataclasses.dataclass
class Lease:
    pane: str
    generation: int
    state: str = "ACTIVE"


class LeaseGuard:
    def __init__(self, lease: Lease):
        self.lease = lease
        self.audit = []
        self._lock = threading.Lock()

    def record(self, action: str, **fields) -> None:
        details = " ".join(f"{key}={value}" for key, value in fields.items())
        self.audit.append(f"{action:<10} {details}".rstrip())

    def handle_event(self, event) -> None:
        if (
            event.get("type") == "human_interrupt"
            and event.get("pane") == self.lease.pane
        ):
            with self._lock:
                previous = self.lease.state
                self.lease.state = "REVOKED"
                self.record(
                    "OVERRIDE",
                    pane=self.lease.pane,
                    generation=self.lease.generation,
                    previous=previous,
                    state=self.lease.state,
                    event_seq=event.get("seq"),
                )

    def send_command(self, generation: int, command: str) -> bool:
        with self._lock:
            if (
                self.lease.state != "ACTIVE"
                or generation != self.lease.generation
            ):
                self.record(
                    "DENY",
                    pane=self.lease.pane,
                    generation=generation,
                    lease_generation=self.lease.generation,
                    state=self.lease.state,
                )
                return False

            self.record(
                "ALLOW",
                pane=self.lease.pane,
                generation=generation,
                bytes=len(command.encode()),
            )

        tmux(
            TMUX_SOCKET,
            "send-keys",
            "-t",
            self.lease.pane,
            "-l",
            command,
        )
        tmux(TMUX_SOCKET, "send-keys", "-t", self.lease.pane, "Enter")
        return True


def ensure_clean_session() -> str:
    tmux(TMUX_SOCKET, "kill-server", check=False)
    tmux(
        TMUX_SOCKET,
        "new-session",
        "-d",
        "-s",
        SESSION,
        "-c",
        str(pathlib.Path.cwd()),
    )
    result = subprocess.run(
        [
            "tmux",
            "-L",
            TMUX_SOCKET,
            "display-message",
            "-p",
            "-t",
            SESSION,
            "#{pane_id}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def capture_pane(pane: str) -> str:
    result = subprocess.run(
        [
            "tmux",
            "-L",
            TMUX_SOCKET,
            "capture-pane",
            "-p",
            "-t",
            pane,
            "-S",
            "-100",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def main() -> int:
    pane = ensure_clean_session()
    lease = Lease(pane=pane, generation=GENERATION)
    guard = LeaseGuard(lease)
    receiver = EventReceiver(EVENT_SOCKET, on_event=guard.handle_event)
    receiver.start()

    try:
        install_binding(TMUX_SOCKET, EVENT_SOCKET, SESSION)
        guard.record(
            "LEASE",
            pane=pane,
            generation=GENERATION,
            state=lease.state,
        )

        # Programmatic Agent Ctrl+C must not revoke the lease.
        tmux(TMUX_SOCKET, "send-keys", "-t", pane, "C-c")
        guard.record(
            "AGENT_KEY",
            pane=pane,
            generation=GENERATION,
            key="C-c",
            state=lease.state,
        )

        allowed = guard.send_command(
            GENERATION,
            f"printf '{ALLOWED_MARKER}\\n'",
        )
        if not allowed:
            print("FAIL: active lease rejected the initial Agent action.")
            return 1

        print("Execution Lease PoC")
        print(f"pane: {pane}")
        print(f"generation: {GENERATION}")
        print(f"state: {lease.state}")
        print()
        print(f"The pane already contains: {ALLOWED_MARKER}")
        print("Inside tmux, run:  ping 1.1.1.1")
        print("Physically press Ctrl+C, then detach with Ctrl+B, D.")
        print("After detach, the PoC will try an action using generation=1.")
        print()

        tmux(TMUX_SOCKET, "attach-session", "-t", SESSION)
    finally:
        receiver.stop()

    denied = not guard.send_command(
        GENERATION,
        f"printf '{DENIED_MARKER}\\n'",
    )
    pane_contents = capture_pane(pane)

    show_events(receiver.events)
    print()
    print("Lease state:", lease.state)
    print("Audit:")
    for entry in guard.audit:
        print(entry)

    passed = (
        lease.state == "REVOKED"
        and denied
        and ALLOWED_MARKER in pane_contents
        and DENIED_MARKER not in pane_contents
    )

    print()
    if passed:
        print("PASS: Human Ctrl+C revoked generation=1.")
        print("PASS: stale generation=1 action was denied before reaching pane.")
        return 0

    print("FAIL: execution lease validation did not satisfy all conditions.")
    print(
        "Checks:",
        {
            "lease_revoked": lease.state == "REVOKED",
            "stale_action_denied": denied,
            "allowed_marker_present": ALLOWED_MARKER in pane_contents,
            "denied_marker_absent": DENIED_MARKER not in pane_contents,
        },
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
