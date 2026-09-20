#!/usr/bin/env python3
"""Validate backup and restoration of tmux root C-c bindings."""

import json
import pathlib
import socket
import subprocess
import sys
import time


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE_SCRIPT = PROJECT_ROOT / "bridge" / "local_bridge.py"
TMUX_SOCKET = "binding-restore-poc"
SESSION = "binding-restore-poc"
CONTROL_SOCKET = pathlib.Path("/tmp/binding-restore-control.sock")
EVENT_SOCKET = pathlib.Path("/tmp/binding-restore-events.sock")
STATE_FILE = pathlib.Path("/tmp/binding-restore-state.json")


def tmux(*arguments: str, capture: bool = False, check: bool = True):
    return subprocess.run(
        ["tmux", "-L", TMUX_SOCKET, *arguments],
        check=check,
        capture_output=capture,
        stderr=subprocess.DEVNULL if not check and not capture else None,
        text=True,
    )


def binding():
    result = tmux(
        "list-keys",
        "-T",
        "root",
        "C-c",
        capture=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def call(method: str):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(str(CONTROL_SOCKET))
    with client:
        writer = client.makefile("w", encoding="utf-8")
        reader = client.makefile("r", encoding="utf-8")
        writer.write(json.dumps({"method": method, "params": {}}) + "\n")
        writer.flush()
        return json.loads(reader.readline())


def wait_for_socket():
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if CONTROL_SOCKET.exists() and EVENT_SOCKET.exists():
            return
        time.sleep(0.05)
    raise RuntimeError("Bridge sockets did not appear")


def main() -> int:
    tmux("kill-server", check=False)
    tmux("new-session", "-d", "-s", SESSION)
    pane = tmux(
        "display-message",
        "-p",
        "-t",
        SESSION,
        "#{pane_id}",
        capture=True,
    ).stdout.strip()

    tmux(
        "bind-key",
        "-T",
        "root",
        "C-c",
        "display-message",
        "ORIGINAL_CTRL_C_BINDING",
    )
    original = binding()

    for path in (CONTROL_SOCKET, EVENT_SOCKET, STATE_FILE):
        if path.exists():
            path.unlink()
    server = subprocess.Popen(
        [
            sys.executable,
            str(BRIDGE_SCRIPT),
            "serve",
            "--tmux-socket",
            TMUX_SOCKET,
            "--control-socket",
            str(CONTROL_SOCKET),
            "--event-socket",
            str(EVENT_SOCKET),
            "--allow-pane",
            pane,
            "--state-file",
            str(STATE_FILE),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        wait_for_socket()

        install_custom = call("install_human_binding")
        installed_custom = binding()
        status_custom = call("human_binding_status")
        restore_custom = call("restore_human_binding")
        restored_custom = binding()

        tmux("unbind-key", "-T", "root", "C-c")
        absent_before = binding()
        install_absent = call("install_human_binding")
        installed_absent = binding()
        restore_absent = call("restore_human_binding")
        absent_after = binding()

        restore_without_snapshot = call("restore_human_binding")
        audit = call("audit_log")
        actions = [
            entry["action"]
            for entry in audit.get("result", {}).get("entries", [])
        ]

        checks = {
            "original_binding_detected": (
                original is not None
                and "ORIGINAL_CTRL_C_BINDING" in original
            ),
            "human_binding_installed_over_custom": (
                install_custom.get("ok")
                and "emit-event" in (installed_custom or "")
            ),
            "custom_snapshot_reported": (
                status_custom.get("result", {}).get(
                    "original_binding_present"
                )
                is True
            ),
            "custom_binding_restored_exactly": (
                restore_custom.get("ok")
                and restored_custom == original
            ),
            "absent_binding_detected": absent_before is None,
            "human_binding_installed_over_absent": (
                install_absent.get("ok")
                and "emit-event" in (installed_absent or "")
            ),
            "absence_restored": (
                restore_absent.get("ok") and absent_after is None
            ),
            "double_restore_fail_closed": (
                restore_without_snapshot.get("error", {}).get("code")
                == "BINDING_SNAPSHOT_NOT_FOUND"
            ),
            "audit_complete": (
                actions.count("BINDING_INSTALL") == 2
                and actions.count("BINDING_RESTORE") == 2
            ),
        }

        print("Binding lifecycle checks:")
        print(json.dumps(checks, indent=2))
        print()
        print("Original binding:")
        print(original)
        print()
        print("Restored binding:")
        print(restored_custom)
        print()

        if all(checks.values()):
            print("PASS: custom C-c binding was restored exactly.")
            print("PASS: an originally absent binding was restored as absent.")
            print("PASS: restore without a snapshot failed closed.")
            return 0
        print("FAIL: binding lifecycle validation failed.")
        return 1
    finally:
        if server.poll() is None:
            server.terminate()
        try:
            server.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=2)
        tmux("kill-server", check=False)
        for path in (CONTROL_SOCKET, EVENT_SOCKET, STATE_FILE):
            if path.exists():
                path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
