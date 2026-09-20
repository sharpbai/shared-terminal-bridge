#!/usr/bin/env python3
"""Validate MCP-created sessions and manual stb management commands."""

import json
import pathlib
import socket
import subprocess
import sys
import time


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = PROJECT_ROOT / "bridge" / "local_bridge.py"
MCP = PROJECT_ROOT / "mcp_server" / "server.py"
STB = PROJECT_ROOT / "bin" / "stb"
TMUX_SOCKET = "managed-session-poc"
CONTROL_SOCKET = pathlib.Path("/tmp/managed-session-control.sock")
EVENT_SOCKET = pathlib.Path("/tmp/managed-session-events.sock")
STATE_FILE = pathlib.Path("/tmp/managed-session-state.json")
MANAGED_NAME = "managed-poc"
ORDINARY_NAME = "ordinary-poc"


def tmux(*arguments, capture=False, check=True):
    return subprocess.run(
        ["tmux", "-L", TMUX_SOCKET, *arguments],
        check=check,
        capture_output=capture,
        text=True,
    )


def wait_for(path):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    raise RuntimeError(f"path did not appear: {path}")


def modern_params(**values):
    return {
        **values,
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientCapabilities": {},
        },
    }


def mcp_request(process, request):
    process.stdin.write(json.dumps(request) + "\n")
    process.stdin.flush()
    return json.loads(process.stdout.readline())


def stb(*arguments, check=True):
    return subprocess.run(
        [
            str(STB),
            "--tmux-socket",
            TMUX_SOCKET,
            "--bridge-socket",
            str(CONTROL_SOCKET),
            *arguments,
        ],
        check=check,
        capture_output=True,
        text=True,
    )


def bridge_call(method, params=None):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(str(CONTROL_SOCKET))
    with client:
        writer = client.makefile("w", encoding="utf-8")
        reader = client.makefile("r", encoding="utf-8")
        writer.write(json.dumps({"method": method, "params": params or {}}) + "\n")
        writer.flush()
        return json.loads(reader.readline())


def main():
    tmux("kill-server", check=False)
    for path in (
        CONTROL_SOCKET,
        EVENT_SOCKET,
        STATE_FILE,
        pathlib.Path(f"{STATE_FILE}.lock"),
    ):
        if path.exists():
            path.unlink()
    tmux("new-session", "-d", "-s", ORDINARY_NAME, "-c", str(PROJECT_ROOT))
    bridge = subprocess.Popen(
        [
            sys.executable,
            str(BRIDGE),
            "serve",
            "--tmux-socket",
            TMUX_SOCKET,
            "--control-socket",
            str(CONTROL_SOCKET),
            "--event-socket",
            str(EVENT_SOCKET),
            "--state-file",
            str(STATE_FILE),
            "--allow-session-management",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    mcp = None
    try:
        wait_for(CONTROL_SOCKET)
        mcp = subprocess.Popen(
            [
                sys.executable,
                str(MCP),
                "--bridge-socket",
                str(CONTROL_SOCKET),
                "--enable-session-management",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        created = mcp_request(
            mcp,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": modern_params(
                    name="terminal_session_create",
                    arguments={"name": MANAGED_NAME, "cwd": str(PROJECT_ROOT)},
                ),
            },
        )
        created_payload = created["result"]["structuredContent"]
        pane = created_payload["result"]["pane"]
        state = mcp_request(
            mcp,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": modern_params(
                    name="terminal_state",
                    arguments={"pane": pane},
                ),
            },
        )
        listed = json.loads(stb("list", "--json").stdout)
        info = json.loads(stb("info", MANAGED_NAME, "--json").stdout)
        panes = stb("panes", MANAGED_NAME).stdout
        new_window = tmux(
            "new-window",
            "-d",
            "-P",
            "-F",
            "#{window_id}",
            "-t",
            f"{MANAGED_NAME}:",
            capture=True,
        ).stdout.strip()
        new_window_history = int(
            tmux(
                "display-message",
                "-p",
                "-t",
                new_window,
                "#{history_limit}",
                capture=True,
            ).stdout.strip()
        )
        lease = json.loads(stb("lease", MANAGED_NAME).stdout)
        generation = lease["generation"]
        released = json.loads(
            stb("release", MANAGED_NAME, str(generation)).stdout
        )
        ordinary_stop = stb("stop", ORDINARY_NAME, check=False)
        stopped = json.loads(stb("stop", MANAGED_NAME).stdout)
        remaining = tmux(
            "list-sessions",
            "-F",
            "#{session_name}",
            capture=True,
        ).stdout.splitlines()
        persisted = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        audit = bridge_call("audit_log")["result"]["entries"]
        actions = [entry["action"] for entry in audit]
        checks = {
            "mcp_created_managed_session": (
                created_payload.get("ok") is True
                and created_payload["result"]["name"] == MANAGED_NAME
            ),
            "new_pane_auto_authorized": (
                state["result"]["structuredContent"].get("ok") is True
            ),
            "managed_history_limit_100k": (
                created_payload["result"]["history_limit"] == 100000
                and info["history_limit"] == 100000
            ),
            "managed_mouse_enabled": (
                created_payload["result"]["mouse"] is True
                and info["mouse"] is True
            ),
            "future_window_history_limit_100k": (
                new_window_history == 100000
            ),
            "stb_list_found_session": any(
                session["name"] == MANAGED_NAME for session in listed
            ),
            "stb_info_matches": info["pane"] == pane,
            "stb_panes_matches": pane in panes,
            "stb_lease_and_release": (
                lease["state"] == "ACTIVE"
                and released["state"] == "RELEASED"
            ),
            "ordinary_session_protected": (
                ordinary_stop.returncode != 0 and ORDINARY_NAME in remaining
            ),
            "managed_session_stopped": (
                stopped["stopped"] is True and MANAGED_NAME not in remaining
            ),
            "dynamic_acl_removed_from_state": (
                not persisted.get("managed_sessions")
            ),
            "session_audit_complete": all(
                action in actions
                for action in ("SESSION_CREATE", "SESSION_STOP", "STATE")
            ),
        }
        print("Managed session and stb checks:")
        print(json.dumps(checks, indent=2))
        if all(checks.values()):
            print("\nPASS: MCP created an authorized managed tmux session.")
            print("PASS: stb managed it without touching an ordinary session.")
            return 0
        print("\nFAIL: managed session validation failed.")
        return 1
    finally:
        if mcp is not None and mcp.poll() is None:
            mcp.terminate()
            mcp.wait(timeout=3)
        if bridge.poll() is None:
            bridge.terminate()
            bridge.wait(timeout=3)
        tmux("kill-server", check=False)
        for path in (
            CONTROL_SOCKET,
            EVENT_SOCKET,
            STATE_FILE,
            pathlib.Path(f"{STATE_FILE}.lock"),
        ):
            if path.exists():
                path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
