#!/usr/bin/env python3
"""PoC for pane-scoped, read-only tmux Observation APIs."""

import dataclasses
import json
import pathlib
import subprocess
import time


TMUX_SOCKET = "observation-bridge-poc"
SESSION = "observation-bridge-poc"
AUTHORIZED_MARKER = "AUTHORIZED_PANE_MARKER"
PRIVATE_MARKER = "PRIVATE_PANE_MARKER"
MAX_LINES = 5000


def run_tmux(*arguments: str, capture: bool = False, check: bool = True):
    options = {
        "check": check,
        "capture_output": capture,
        "text": True,
    }
    if not check and not capture:
        options["stderr"] = subprocess.DEVNULL
    return subprocess.run(
        ["tmux", "-L", TMUX_SOCKET, *arguments],
        **options,
    )


@dataclasses.dataclass
class PaneAccessDenied(Exception):
    pane: str

    def as_dict(self):
        return {
            "error": {
                "code": "PANE_ACCESS_DENIED",
                "pane": self.pane,
            }
        }


class ObservationBridge:
    LIST_FORMAT = "\t".join(
        [
            "#{session_name}",
            "#{window_id}",
            "#{pane_id}",
            "#{pane_index}",
            "#{pane_active}",
        ]
    )
    STATE_FORMAT = "\t".join(
        [
            "#{session_name}",
            "#{window_id}",
            "#{pane_id}",
            "#{pane_index}",
            "#{pane_active}",
            "#{pane_current_command}",
            "#{pane_current_path}",
            "#{pane_pid}",
            "#{pane_tty}",
            "#{pane_dead}",
        ]
    )

    def __init__(self, allowed_panes):
        self.allowed_panes = set(allowed_panes)
        self.audit = []

    def _authorize(self, pane: str) -> None:
        if pane not in self.allowed_panes:
            self.audit.append(
                f"READ_DENY  pane={pane} reason=PANE_ACCESS_DENIED"
            )
            raise PaneAccessDenied(pane)

    def terminal_list(self):
        result = run_tmux(
            "list-panes",
            "-a",
            "-F",
            self.LIST_FORMAT,
            capture=True,
        )
        panes = []
        for line in result.stdout.splitlines():
            session, window, pane, index, active = line.split("\t")
            panes.append(
                {
                    "server": TMUX_SOCKET,
                    "session": session,
                    "window": window,
                    "pane": pane,
                    "pane_index": int(index),
                    "active": active == "1",
                    "authorized": pane in self.allowed_panes,
                }
            )
        self.audit.append(f"LIST       panes={len(panes)}")
        return {"panes": panes}

    def terminal_read(self, pane: str, lines: int = 100):
        if not 1 <= lines <= MAX_LINES:
            raise ValueError("INVALID_LINE_LIMIT")
        self._authorize(pane)
        result = run_tmux(
            "capture-pane",
            "-p",
            "-t",
            pane,
            "-S",
            f"-{lines}",
            capture=True,
        )
        self.audit.append(f"READ       pane={pane} lines={lines}")
        return {
            "pane": pane,
            "lines_requested": lines,
            "content": result.stdout,
            "truncated": False,
        }

    def terminal_state(self, pane: str):
        self._authorize(pane)
        result = run_tmux(
            "display-message",
            "-p",
            "-t",
            pane,
            self.STATE_FORMAT,
            capture=True,
        )
        fields = result.stdout.rstrip("\n").split("\t")
        if len(fields) != 10 or not fields[2]:
            raise RuntimeError("PANE_NOT_FOUND")
        (
            session,
            window,
            pane_id,
            index,
            active,
            current_command,
            cwd,
            pid,
            tty,
            dead,
        ) = fields
        self.audit.append(f"STATE      pane={pane}")
        return {
            "server": TMUX_SOCKET,
            "session": session,
            "window": window,
            "pane": pane_id,
            "pane_index": int(index),
            "active": active == "1",
            "current_command": current_command,
            "cwd": cwd,
            "pid": int(pid),
            "tty": tty,
            "dead": dead == "1",
        }


def send_marker(pane: str, marker: str) -> None:
    run_tmux("send-keys", "-t", pane, "-l", f"printf '{marker}\\n'")
    run_tmux("send-keys", "-t", pane, "Enter")


def create_fixture():
    run_tmux("kill-server", check=False)
    run_tmux(
        "new-session",
        "-d",
        "-s",
        SESSION,
        "-c",
        str(pathlib.Path.cwd()),
    )
    first = run_tmux(
        "display-message",
        "-p",
        "-t",
        SESSION,
        "#{pane_id}",
        capture=True,
    ).stdout.strip()
    second = run_tmux(
        "split-window",
        "-d",
        "-P",
        "-F",
        "#{pane_id}",
        "-t",
        first,
        "-c",
        str(pathlib.Path.cwd()),
        capture=True,
    ).stdout.strip()
    send_marker(first, AUTHORIZED_MARKER)
    send_marker(second, PRIVATE_MARKER)
    time.sleep(0.4)
    return first, second


def main() -> int:
    authorized_pane, private_pane = create_fixture()
    bridge = ObservationBridge({authorized_pane})

    inventory = bridge.terminal_list()
    authorized_read = bridge.terminal_read(authorized_pane, lines=100)
    authorized_state = bridge.terminal_state(authorized_pane)

    denied_error = None
    try:
        bridge.terminal_read(private_pane, lines=100)
    except PaneAccessDenied as error:
        denied_error = error.as_dict()

    serialized_visible_results = json.dumps(
        {
            "inventory": inventory,
            "read": authorized_read,
            "state": authorized_state,
            "denied": denied_error,
        },
        ensure_ascii=False,
    )

    passed = (
        len(inventory["panes"]) == 2
        and AUTHORIZED_MARKER in authorized_read["content"]
        and PRIVATE_MARKER not in serialized_visible_results
        and authorized_state["pane"] == authorized_pane
        and denied_error is not None
        and denied_error["error"]["code"] == "PANE_ACCESS_DENIED"
    )

    print("terminal_list:")
    print(json.dumps(inventory, ensure_ascii=False, indent=2))
    print()
    print("terminal_read (authorized pane):")
    print(json.dumps(authorized_read, ensure_ascii=False, indent=2))
    print()
    print("terminal_state (authorized pane):")
    print(json.dumps(authorized_state, ensure_ascii=False, indent=2))
    print()
    print("terminal_read (unauthorized pane):")
    print(json.dumps(denied_error, ensure_ascii=False, indent=2))
    print()
    print("Audit:")
    for entry in bridge.audit:
        print(entry)
    print()

    if passed:
        print("PASS: two panes were enumerated with minimal metadata.")
        print("PASS: authorized pane history and state were readable.")
        print("PASS: unauthorized pane content was denied and did not leak.")
        return 0

    print("FAIL: Observation Bridge validation did not satisfy all checks.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
