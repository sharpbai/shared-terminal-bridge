#!/usr/bin/env python3
"""End-to-end validation for the combined local Bridge prototype."""

import argparse
import json
import pathlib
import socket
import subprocess
import sys
import time


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE_SCRIPT = PROJECT_ROOT / "bridge" / "local_bridge.py"
TMUX_SOCKET = "combined-bridge-poc"
SESSION = "combined-bridge-poc"
CONTROL_SOCKET = pathlib.Path("/tmp/combined-bridge-control.sock")
EVENT_SOCKET = pathlib.Path("/tmp/combined-bridge-events.sock")
STATE_FILE = pathlib.Path("/tmp/combined-bridge-state.json")
AUTHORIZED_MARKER = "COMBINED_ALLOWED_ACTION"
STALE_MARKER = "COMBINED_STALE_ACTION"
PRIVATE_MARKER = "COMBINED_PRIVATE_PANE"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit only the machine-readable baseline result",
    )
    return parser.parse_args()


def tmux(*arguments: str, capture: bool = False, check: bool = True):
    options = {"check": check, "capture_output": capture, "text": True}
    if not check and not capture:
        options["stderr"] = subprocess.DEVNULL
    return subprocess.run(
        ["tmux", "-L", TMUX_SOCKET, *arguments],
        **options,
    )


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


def emit_human_event(pane: str):
    event = {
        "type": "human_interrupt",
        "source": "tmux_client",
        "key": "C-c",
        "pane": pane,
        "client": "combined-poc-client",
        "session": SESSION,
    }
    producer = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        producer.sendto(json.dumps(event).encode(), str(EVENT_SOCKET))
    finally:
        producer.close()


def send_command(pane: str, command: str):
    tmux("send-keys", "-t", pane, "-l", command)
    tmux("send-keys", "-t", pane, "Enter")


def create_fixture():
    tmux("kill-server", check=False)
    tmux(
        "new-session",
        "-d",
        "-s",
        SESSION,
        "-c",
        str(PROJECT_ROOT),
    )
    pane_a = tmux(
        "display-message",
        "-p",
        "-t",
        SESSION,
        "#{pane_id}",
        capture=True,
    ).stdout.strip()
    pane_b = tmux(
        "split-window",
        "-d",
        "-P",
        "-F",
        "#{pane_id}",
        "-t",
        pane_a,
        "-c",
        str(PROJECT_ROOT),
        capture=True,
    ).stdout.strip()
    send_command(pane_b, f"printf '{PRIVATE_MARKER}\\n'")
    time.sleep(0.3)
    return pane_a, pane_b


def start_control_client():
    return subprocess.Popen(
        [
            "tmux",
            "-L",
            TMUX_SOCKET,
            "-C",
            "attach-session",
            "-t",
            SESSION,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def wait_for_path(path: pathlib.Path):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    raise RuntimeError(f"Socket did not appear: {path}")


def wait_for_client():
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = tmux(
            "list-clients",
            "-F",
            "#{client_name}",
            capture=True,
            check=False,
        )
        names = [line for line in result.stdout.splitlines() if line]
        if names:
            return names[0]
        time.sleep(0.05)
    raise RuntimeError("Control client did not attach")


def wait_for_revoked(pane: str):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        response = call("execution_status", {"pane": pane})
        lease = response.get("result", {}).get("lease")
        if lease and lease.get("state") == "REVOKED":
            return response
        time.sleep(0.05)
    raise RuntimeError("Lease was not revoked")


def main() -> int:
    args = parse_args()
    pane_a, pane_b = create_fixture()
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
            pane_a,
            "--state-file",
            str(STATE_FILE),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    control_client = None

    try:
        wait_for_path(CONTROL_SOCKET)
        wait_for_path(EVENT_SOCKET)
        control_client = start_control_client()
        client_name = wait_for_client()

        inventory = call("terminal_list")
        active = call("get_active_pane", {"client": client_name})
        read_allowed = call("terminal_read", {"pane": pane_a, "lines": 100})
        state_allowed = call("terminal_state", {"pane": pane_a})
        read_denied = call("terminal_read", {"pane": pane_b, "lines": 100})
        binding = call("install_human_binding")

        acquired = call("acquire_execution", {"pane": pane_a})
        generation = acquired["result"]["generation"]
        typed = call(
            "terminal_type",
            {
                "pane": pane_a,
                "generation": generation,
                "text": f"printf '{AUTHORIZED_MARKER}\\n'",
            },
        )
        entered = call(
            "terminal_key",
            {
                "pane": pane_a,
                "generation": generation,
                "key": "Enter",
            },
        )
        agent_interrupt = call(
            "terminal_interrupt",
            {"pane": pane_a, "generation": generation},
        )
        active_after_agent = call("execution_status", {"pane": pane_a})

        emit_human_event(pane_a)
        revoked = wait_for_revoked(pane_a)
        stale = call(
            "terminal_type",
            {
                "pane": pane_a,
                "generation": generation,
                "text": STALE_MARKER,
            },
        )
        audit = call("audit_log")
        time.sleep(0.2)
        pane_contents = tmux(
            "capture-pane",
            "-p",
            "-t",
            pane_a,
            "-S",
            "-100",
            capture=True,
        ).stdout

        visible = json.dumps(
            {
                "inventory": inventory,
                "active": active,
                "read_allowed": read_allowed,
                "state_allowed": state_allowed,
                "read_denied": read_denied,
            }
        )
        audit_actions = [
            entry["action"]
            for entry in audit.get("result", {}).get("entries", [])
        ]

        checks = {
            "inventory_ok": inventory.get("ok") is True,
            "active_client_ok": (
                active.get("result", {}).get("pane") == pane_a
            ),
            "authorized_read_ok": read_allowed.get("ok") is True,
            "authorized_state_ok": state_allowed.get("ok") is True,
            "unauthorized_denied": (
                read_denied.get("error", {}).get("code")
                == "PANE_ACCESS_DENIED"
            ),
            "private_content_not_leaked": PRIVATE_MARKER not in visible,
            "binding_installed": binding.get("ok") is True,
            "active_action_allowed": typed.get("ok") and entered.get("ok"),
            "agent_interrupt_not_revoke": (
                agent_interrupt.get("ok")
                and active_after_agent["result"]["lease"]["state"] == "ACTIVE"
            ),
            "human_event_revoked": (
                revoked["result"]["lease"]["state"] == "REVOKED"
            ),
            "stale_action_denied": (
                stale.get("error", {}).get("code")
                == "EXECUTION_LEASE_INVALID"
            ),
            "allowed_action_reached_pane": AUTHORIZED_MARKER in pane_contents,
            "stale_action_absent": STALE_MARKER not in pane_contents,
            "audit_complete": all(
                action in audit_actions
                for action in (
                    "LIST",
                    "ACTIVE",
                    "READ",
                    "STATE",
                    "ACCESS_DENY",
                    "LEASE_ACQUIRE",
                    "TYPE",
                    "KEY",
                    "AGENT_INTERRUPT",
                    "HUMAN_INTERRUPT",
                    "LEASE_REVOKE",
                    "ACTION_DENY",
                )
            ),
        }

        passed = all(checks.values())
        baseline_result = {
            "schema_version": 1,
            "suite": "combined_bridge",
            "passed": passed,
            "checks": checks,
            "lease_state": revoked["result"]["lease"]["state"],
            "stale_error": stale.get("error", {}).get("code"),
            "audit_actions": audit_actions,
        }

        if args.json:
            print(json.dumps(baseline_result, sort_keys=True))
        else:
            print("Combined Local Bridge end-to-end checks:")
            print(json.dumps(checks, indent=2))
            print()
            print("Lease after Human event:")
            print(json.dumps(revoked, indent=2))
            print()
            print("Stale action response:")
            print(json.dumps(stale, indent=2))
            print()
            print("Audit actions:")
            print(json.dumps(audit_actions, indent=2))
            print()

        if passed:
            if not args.json:
                print("PASS: combined local Bridge prototype passed end-to-end.")
            return 0
        if not args.json:
            print("FAIL: combined Bridge did not satisfy every check.")
        return 1
    finally:
        if control_client is not None:
            if control_client.poll() is None:
                control_client.terminate()
            try:
                control_client.wait(timeout=2)
            except subprocess.TimeoutExpired:
                control_client.kill()
                control_client.wait(timeout=2)
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
