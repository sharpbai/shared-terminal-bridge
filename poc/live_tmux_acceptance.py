#!/usr/bin/env python3
"""Manual acceptance test against an existing, daily-use tmux server."""

import argparse
import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE_SCRIPT = PROJECT_ROOT / "bridge" / "local_bridge.py"
RUN_ID = os.getpid()
CONTROL_SOCKET = pathlib.Path(f"/tmp/live-tmux-acceptance-{RUN_ID}-control.sock")
EVENT_SOCKET = pathlib.Path(f"/tmp/live-tmux-acceptance-{RUN_ID}-events.sock")
STATE_FILE = pathlib.Path(f"/tmp/live-tmux-acceptance-{RUN_ID}-state.json")
HISTORY_FILE = pathlib.Path(f"/tmp/live-tmux-acceptance-{RUN_ID}-history.jsonl")
WINDOW_NAME = "bridge-acceptance"
ALLOWED_MARKER = "LIVE_BRIDGE_ACTION_ALLOWED"
STALE_MARKER = "LIVE_BRIDGE_STALE_ACTION_MUST_NOT_APPEAR"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tmux-socket", default="default")
    parser.add_argument(
        "--origin-pane",
        help="pane to return to; defaults to inherited TMUX_PANE",
    )
    parser.add_argument("--client", help="tmux client name; auto-detected by default")
    parser.add_argument("--timeout", type=int, default=120)
    return parser.parse_args()


def tmux(socket_name, *arguments, capture=False, check=True):
    return subprocess.run(
        ["tmux", "-L", socket_name, *arguments],
        check=check,
        capture_output=capture,
        text=True,
    )


def tmux_text(socket_name, *arguments):
    return tmux(socket_name, *arguments, capture=True).stdout.strip()


def call(method, params=None):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(str(CONTROL_SOCKET))
    with client:
        writer = client.makefile("w", encoding="utf-8")
        reader = client.makefile("r", encoding="utf-8")
        writer.write(json.dumps({"method": method, "params": params or {}}) + "\n")
        writer.flush()
        return json.loads(reader.readline())


def wait_for_socket(path):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    raise RuntimeError(f"Bridge socket did not appear: {path}")


def find_client(socket_name, origin_pane, requested):
    rows = tmux_text(
        socket_name,
        "list-clients",
        "-F",
        "#{client_name}|#{pane_id}",
    ).splitlines()
    clients = [row.split("|", 1) for row in rows if "|" in row]
    if requested:
        if not any(name == requested for name, _ in clients):
            raise RuntimeError(f"tmux client not found: {requested}")
        return requested
    matches = [name for name, pane in clients if pane == origin_pane]
    if len(matches) != 1:
        raise RuntimeError(
            "Cannot uniquely identify the tmux client on the current pane; "
            "pass --client explicitly"
        )
    return matches[0]


def root_ctrl_c_binding(socket_name):
    result = tmux(
        socket_name,
        "list-keys",
        "-T",
        "root",
        "C-c",
        capture=True,
        check=False,
    )
    return result.stdout.strip() or None if result.returncode == 0 else None


def restore_binding_directly(socket_name, original):
    if original is None:
        tmux(
            socket_name,
            "unbind-key",
            "-T",
            "root",
            "C-c",
            check=False,
        )
        return
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="live-acceptance-binding-",
            suffix=".conf",
            delete=False,
        ) as temporary:
            temporary.write(original + "\n")
            temporary_path = pathlib.Path(temporary.name)
        os.chmod(temporary_path, 0o600)
        tmux(socket_name, "source-file", str(temporary_path))
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def require_ok(response, label):
    if not response.get("ok"):
        raise RuntimeError(f"{label} failed: {json.dumps(response)}")
    return response["result"]


def main():
    args = parse_args()
    origin_pane = args.origin_pane or os.environ.get("TMUX_PANE")
    if not origin_pane:
        raise RuntimeError(
            "this shell is not inside tmux; first run "
            "'tmux new-session -s bridge-manual', then run this script "
            "inside that session. --origin-pane is reserved for an "
            "explicitly identified client"
        )
    origin_session = tmux_text(
        args.tmux_socket,
        "display-message",
        "-p",
        "-t",
        origin_pane,
        "#{session_name}",
    )
    client_name = find_client(args.tmux_socket, origin_pane, args.client)
    original_binding = root_ctrl_c_binding(args.tmux_socket)
    test_pane = None
    server = None
    binding_installed = False
    checks = {}

    for path in (CONTROL_SOCKET, EVENT_SOCKET, STATE_FILE, HISTORY_FILE, pathlib.Path(f"{STATE_FILE}.lock")):
        if path.exists():
            path.unlink()

    try:
        test_pane = tmux_text(
            args.tmux_socket,
            "new-window",
            "-d",
            "-P",
            "-F",
            "#{pane_id}",
            "-t",
            origin_session,
            "-n",
            WINDOW_NAME,
            "-c",
            str(PROJECT_ROOT),
        )
        server = subprocess.Popen(
            [
                sys.executable,
                str(BRIDGE_SCRIPT),
                "serve",
                "--tmux-socket",
                args.tmux_socket,
                "--control-socket",
                str(CONTROL_SOCKET),
                "--event-socket",
                str(EVENT_SOCKET),
                "--allow-pane",
                test_pane,
                "--state-file",
                str(STATE_FILE),
                "--history-file",
                str(HISTORY_FILE),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        wait_for_socket(CONTROL_SOCKET)

        inventory = require_ok(call("terminal_list"), "terminal_list")
        state = require_ok(call("terminal_state", {"pane": test_pane}), "terminal_state")
        history = require_ok(
            call("terminal_read", {"pane": test_pane, "lines": 20}),
            "terminal_read",
        )
        denied = call("terminal_read", {"pane": origin_pane, "lines": 20})
        checks["observation_authorized"] = (
            state["pane"] == test_pane and history["pane"] == test_pane
        )
        checks["other_pane_denied"] = (
            denied.get("error", {}).get("code") == "PANE_ACCESS_DENIED"
        )
        checks["inventory_scoped"] = any(
            pane["pane"] == test_pane and pane["authorized"]
            for pane in inventory["panes"]
        )

        require_ok(call("install_human_binding"), "install_human_binding")
        binding_installed = True
        lease = require_ok(
            call("acquire_execution", {"pane": test_pane}),
            "acquire_execution",
        )
        generation = lease["generation"]
        require_ok(
            call(
                "terminal_type",
                {"pane": test_pane, "generation": generation, "text": f"printf '{ALLOWED_MARKER}\\n'"},
            ),
            "terminal_type marker",
        )
        require_ok(
            call("terminal_key", {"pane": test_pane, "generation": generation, "key": "Enter"}),
            "terminal_key Enter",
        )
        require_ok(
            call("terminal_interrupt", {"pane": test_pane, "generation": generation}),
            "agent interrupt",
        )
        after_agent = require_ok(
            call("execution_status", {"pane": test_pane}),
            "execution_status after Agent C-c",
        )
        checks["agent_ctrl_c_kept_lease"] = after_agent["lease"]["state"] == "ACTIVE"

        require_ok(
            call(
                "terminal_type",
                {"pane": test_pane, "generation": generation, "text": "ping 1.1.1.1"},
            ),
            "terminal_type ping",
        )
        require_ok(
            call("terminal_key", {"pane": test_pane, "generation": generation, "key": "Enter"}),
            "terminal_key ping Enter",
        )
        tmux(args.tmux_socket, "switch-client", "-c", client_name, "-t", test_pane)
        tmux(
            args.tmux_socket,
            "display-message",
            "-c",
            client_name,
            "Physically press Ctrl+C to stop ping and revoke the Agent lease",
        )

        deadline = time.monotonic() + args.timeout
        revoked = None
        while time.monotonic() < deadline:
            status = require_ok(
                call("execution_status", {"pane": test_pane}),
                "execution_status while waiting",
            )
            if status["lease"]["state"] == "REVOKED":
                revoked = status["lease"]
                break
            time.sleep(0.1)
        if revoked is None:
            raise RuntimeError("Timed out waiting for physical Ctrl+C")

        stale = call(
            "terminal_type",
            {"pane": test_pane, "generation": generation, "text": STALE_MARKER},
        )
        checks["human_ctrl_c_revoked_lease"] = revoked["state"] == "REVOKED"
        checks["stale_generation_denied"] = (
            stale.get("error", {}).get("code") == "EXECUTION_LEASE_INVALID"
        )
        time.sleep(0.3)
        content = tmux_text(
            args.tmux_socket,
            "capture-pane",
            "-p",
            "-t",
            test_pane,
            "-S",
            "-100",
        )
        checks["allowed_action_visible"] = ALLOWED_MARKER in content
        checks["stale_action_absent"] = STALE_MARKER not in content
        audit = require_ok(call("audit_log"), "audit_log")
        actions = [entry["action"] for entry in audit["entries"]]
        checks["audit_complete"] = all(
            action in actions
            for action in (
                "READ",
                "STATE",
                "ACCESS_DENY",
                "LEASE_ACQUIRE",
                "AGENT_INTERRUPT",
                "HUMAN_INTERRUPT",
                "LEASE_REVOKE",
                "ACTION_DENY",
            )
        )
        return_code = 0 if all(checks.values()) else 1
    finally:
        if binding_installed and CONTROL_SOCKET.exists():
            try:
                require_ok(call("restore_human_binding"), "restore_human_binding")
                binding_installed = False
            except (OSError, RuntimeError):
                pass
        if binding_installed:
            restore_binding_directly(args.tmux_socket, original_binding)
        try:
            tmux(args.tmux_socket, "switch-client", "-c", client_name, "-t", origin_pane)
        except subprocess.CalledProcessError:
            pass
        if test_pane:
            tmux(args.tmux_socket, "kill-pane", "-t", test_pane, check=False)
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=2)
        for path in (CONTROL_SOCKET, EVENT_SOCKET, STATE_FILE, HISTORY_FILE, pathlib.Path(f"{STATE_FILE}.lock")):
            if path.exists():
                path.unlink()

    print("Live tmux acceptance checks:")
    print(json.dumps(checks, indent=2))
    if return_code == 0:
        print("\nPASS: daily-use tmux acceptance test passed.")
    else:
        print("\nFAIL: one or more acceptance checks failed.")
    return return_code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
