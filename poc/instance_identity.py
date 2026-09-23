#!/usr/bin/env python3
"""Validate daemon singleton locking and tmux server identity."""

import json
import pathlib
import socket
import subprocess
import sys
import time


ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "bridge" / "local_bridge.py"
TMUX_SOCKET = "instance-identity-poc"
SESSION = "instance-identity-poc"
STATE = pathlib.Path("/tmp/instance-identity-state.json")
HISTORY = pathlib.Path("/tmp/instance-identity-history.jsonl")
LOCK = pathlib.Path(f"{STATE}.lock")
CONTROL_1 = pathlib.Path("/tmp/instance-identity-control-1.sock")
EVENT_1 = pathlib.Path("/tmp/instance-identity-event-1.sock")
CONTROL_2 = pathlib.Path("/tmp/instance-identity-control-2.sock")
EVENT_2 = pathlib.Path("/tmp/instance-identity-event-2.sock")


def tmux(*args, capture=False, check=True):
    options = {"check": check, "capture_output": capture, "text": True}
    if not check and not capture:
        options["stderr"] = subprocess.DEVNULL
    return subprocess.run(["tmux", "-L", TMUX_SOCKET, *args], **options)


def create_tmux():
    tmux("new-session", "-d", "-s", SESSION, "-c", str(ROOT))
    return tmux(
        "display-message", "-p", "-t", SESSION, "#{pane_id}", capture=True
    ).stdout.strip()


def start(control, event, pane):
    return subprocess.Popen(
        [
            sys.executable,
            str(BRIDGE),
            "serve",
            "--tmux-socket",
            TMUX_SOCKET,
            "--control-socket",
            str(control),
            "--event-socket",
            str(event),
            "--state-file",
            str(STATE),
            "--history-file",
            str(HISTORY),
            "--allow-pane",
            pane,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def wait_socket(process, path):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists():
            return True
        if process.poll() is not None:
            return False
        time.sleep(0.05)
    return False


def call(method, params=None):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(str(CONTROL_1))
    with client:
        writer = client.makefile("w")
        reader = client.makefile("r")
        writer.write(json.dumps({"method": method, "params": params or {}}) + "\n")
        writer.flush()
        return json.loads(reader.readline())


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        process.wait(timeout=3)


def cleanup():
    tmux("kill-server", check=False)
    for path in (
        STATE, HISTORY, LOCK, CONTROL_1, EVENT_1, CONTROL_2, EVENT_2
    ):
        if path.exists():
            path.unlink()


def main():
    cleanup()
    pane_1 = create_tmux()
    first = start(CONTROL_1, EVENT_1, pane_1)
    second = None
    replacement = None
    try:
        if not wait_socket(first, CONTROL_1):
            raise RuntimeError(first.stderr.read())
        lease = call("acquire_execution", {"pane": pane_1})
        old_generation = lease["result"]["generation"]
        persisted = json.loads(STATE.read_text())
        old_server_id = persisted["tmux_server_id"]

        second = start(CONTROL_2, EVENT_2, pane_1)
        second.wait(timeout=3)
        second_error = second.stderr.read()

        stop(first)
        first = None
        tmux("kill-server")
        pane_2 = create_tmux()
        replacement = start(CONTROL_1, EVENT_1, pane_2)
        replacement.wait(timeout=3)
        replacement_error = replacement.stderr.read()
        new_server_id = tmux(
            "show-environment",
            "-g",
            "SHARED_TERMINAL_BRIDGE_SERVER_ID",
            capture=True,
        ).stdout.strip().split("=", 1)[1]

        checks = {
            "state_has_server_identity": bool(old_server_id),
            "second_daemon_rejected": second.returncode != 0,
            "second_error_is_singleton": (
                "INSTANCE_ALREADY_RUNNING" in second_error
            ),
            "second_created_no_control_socket": not CONTROL_2.exists(),
            "pane_id_reused_for_test": pane_2 == pane_1,
            "new_tmux_server_has_new_identity": new_server_id != old_server_id,
            "replacement_daemon_rejected": replacement.returncode != 0,
            "replacement_error_is_identity_mismatch": (
                "STATE_TMUX_SERVER_MISMATCH" in replacement_error
            ),
            "old_generation_remains_only_in_old_state": (
                persisted["generations"][pane_1] == old_generation
            ),
        }
        print("Singleton and server identity checks:")
        print(json.dumps(checks, indent=2))
        print()
        if all(checks.values()):
            print("PASS: a second daemon could not acquire the same state.")
            print("PASS: rebuilt tmux server was rejected despite pane ID reuse.")
            print("PASS: old lease state was not applied to the new server.")
            return 0
        print("FAIL: singleton/server identity validation failed.")
        return 1
    finally:
        stop(first)
        stop(second)
        stop(replacement)
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
