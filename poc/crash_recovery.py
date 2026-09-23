#!/usr/bin/env python3
"""Validate fail-closed Bridge state recovery after daemon SIGKILL."""

import json
import pathlib
import socket
import stat
import subprocess
import sys
import time


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE_SCRIPT = PROJECT_ROOT / "bridge" / "local_bridge.py"
TMUX_SOCKET = "crash-recovery-poc"
SESSION = "crash-recovery-poc"
CONTROL_SOCKET = pathlib.Path("/tmp/crash-recovery-control.sock")
EVENT_SOCKET = pathlib.Path("/tmp/crash-recovery-events.sock")
STATE_FILE = pathlib.Path("/tmp/crash-recovery-state.json")
HISTORY_FILE = pathlib.Path("/tmp/crash-recovery-history.jsonl")
ORIGINAL_LABEL = "CRASH_RECOVERY_ORIGINAL_BINDING"


def tmux(*arguments: str, capture: bool = False, check: bool = True):
    options = {"check": check, "capture_output": capture, "text": True}
    if not check and not capture:
        options["stderr"] = subprocess.DEVNULL
    return subprocess.run(
        ["tmux", "-L", TMUX_SOCKET, *arguments],
        **options,
    )


def binding():
    result = tmux(
        "list-keys", "-T", "root", "C-c", capture=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def call(method: str, params=None):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(str(CONTROL_SOCKET))
    with client:
        writer = client.makefile("w", encoding="utf-8")
        reader = client.makefile("r", encoding="utf-8")
        writer.write(
            json.dumps({"method": method, "params": params or {}}) + "\n"
        )
        writer.flush()
        return json.loads(reader.readline())


def start_server(pane: str):
    for path in (CONTROL_SOCKET, EVENT_SOCKET):
        if path.exists():
            path.unlink()
    process = subprocess.Popen(
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
            "--state-file",
            str(STATE_FILE),
            "--history-file",
            str(HISTORY_FILE),
            "--allow-pane",
            pane,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if CONTROL_SOCKET.exists() and EVENT_SOCKET.exists():
            return process
        if process.poll() is not None:
            raise RuntimeError(process.stderr.read())
        time.sleep(0.05)
    raise RuntimeError("Bridge sockets did not appear")


def stop_server(process, *, crash=False):
    if process.poll() is None:
        if crash:
            process.kill()
        else:
            process.terminate()
    process.wait(timeout=3)


def main() -> int:
    tmux("kill-server", check=False)
    for path in (CONTROL_SOCKET, EVENT_SOCKET, STATE_FILE, HISTORY_FILE):
        if path.exists():
            path.unlink()
    tmux("new-session", "-d", "-s", SESSION, "-c", str(PROJECT_ROOT))
    pane = tmux(
        "display-message", "-p", "-t", SESSION, "#{pane_id}", capture=True
    ).stdout.strip()
    tmux(
        "bind-key",
        "-T",
        "root",
        "C-c",
        "display-message",
        ORIGINAL_LABEL,
    )
    original = binding()
    first = None
    second = None

    try:
        first = start_server(pane)
        installed = call("install_human_binding")
        acquired = call("acquire_execution", {"pane": pane})
        generation_1 = acquired["result"]["generation"]
        installed_binding = binding()
        state_before_crash = json.loads(STATE_FILE.read_text())
        mode_before = stat.S_IMODE(STATE_FILE.stat().st_mode)

        stop_server(first, crash=True)
        first = None

        second = start_server(pane)
        recovered = call("execution_status", {"pane": pane})
        binding_status = call("human_binding_status")
        stale = call(
            "terminal_type",
            {
                "pane": pane,
                "generation": generation_1,
                "text": "SHOULD_NOT_RUN_AFTER_CRASH",
            },
        )
        restored = call("restore_human_binding")
        restored_binding = binding()
        acquired_2 = call("acquire_execution", {"pane": pane})
        generation_2 = acquired_2["result"]["generation"]
        state_after = json.loads(STATE_FILE.read_text())
        mode_after = stat.S_IMODE(STATE_FILE.stat().st_mode)

        lease = recovered["result"]["lease"]
        checks = {
            "state_written_before_crash": (
                state_before_crash["leases"][pane]["state"] == "ACTIVE"
            ),
            "state_mode_0600_before": mode_before == 0o600,
            "binding_snapshot_persisted": (
                state_before_crash["binding"]["original"] == original
                and state_before_crash["binding"]["installed"] is True
            ),
            "human_binding_survived_crash": (
                installed.get("ok") and "emit-event" in installed_binding
            ),
            "active_lease_revoked_on_restart": (
                lease["state"] == "REVOKED"
                and lease["revoke_reason"] == "daemon_restart"
            ),
            "stale_generation_denied": (
                stale.get("error", {}).get("code")
                == "EXECUTION_LEASE_INVALID"
            ),
            "binding_snapshot_recovered": (
                binding_status["result"]["snapshot_available"] is True
                and binding_status["result"]["installed"] is True
            ),
            "original_binding_restored": (
                restored.get("ok") and restored_binding == original
            ),
            "generation_monotonic_after_restart": generation_2 > generation_1,
            "state_mode_0600_after": mode_after == 0o600,
            "state_records_generation_2": (
                state_after["generations"][pane] == generation_2
            ),
        }

        print("Crash recovery checks:")
        print(json.dumps(checks, indent=2))
        print()
        print("Recovered lease:")
        print(json.dumps(lease, indent=2))
        print()
        if all(checks.values()):
            print("PASS: daemon crash did not revive an ACTIVE lease.")
            print("PASS: stale generation was denied after restart.")
            print("PASS: original binding snapshot survived and restored.")
            print("PASS: generation remained monotonic and state stayed 0600.")
            return 0
        print("FAIL: crash recovery validation failed.")
        return 1
    finally:
        if first is not None and first.poll() is None:
            stop_server(first)
        if second is not None and second.poll() is None:
            stop_server(second)
        tmux("kill-server", check=False)
        for path in (CONTROL_SOCKET, EVENT_SOCKET, STATE_FILE, HISTORY_FILE):
            if path.exists():
                path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
