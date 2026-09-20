#!/usr/bin/env python3
"""End-to-end validation of MCP stdio -> Bridge socket -> tmux."""

import json
import pathlib
import socket
import subprocess
import sys
import time


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE_SCRIPT = PROJECT_ROOT / "bridge" / "local_bridge.py"
MCP_SCRIPT = PROJECT_ROOT / "mcp_server" / "server.py"
TMUX_SOCKET = "mcp-bridge-poc"
SESSION = "mcp-bridge-poc"
CONTROL_SOCKET = pathlib.Path("/tmp/mcp-bridge-control.sock")
EVENT_SOCKET = pathlib.Path("/tmp/mcp-bridge-events.sock")
STATE_FILE = pathlib.Path("/tmp/mcp-bridge-state.json")
MARKER = "MCP_BRIDGE_OBSERVATION_MARKER"
WRITE_MARKER = "MCP_BRIDGE_LEASED_WRITE_ALLOWED"
STALE_MARKER = "MCP_BRIDGE_STALE_WRITE_MUST_NOT_APPEAR"


def tmux(*arguments, capture=False, check=True):
    return subprocess.run(
        ["tmux", "-L", TMUX_SOCKET, *arguments],
        check=check,
        capture_output=capture,
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


def wait_for(path):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    raise RuntimeError(f"path did not appear: {path}")


def mcp_request(process, request):
    process.stdin.write(json.dumps(request) + "\n")
    process.stdin.flush()
    line = process.stdout.readline()
    if not line:
        raise RuntimeError("MCP server closed stdout")
    return json.loads(line)


def modern_params(**values):
    return {
        **values,
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientCapabilities": {},
            "io.modelcontextprotocol/clientInfo": {
                "name": "mcp-end-to-end-poc",
                "version": "1",
            },
        },
    }


def emit_human_event(pane):
    event = {
        "type": "human_interrupt",
        "source": "tmux_client",
        "key": "C-c",
        "pane": pane,
        "client": "mcp-end-to-end-poc",
        "session": SESSION,
    }
    producer = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        producer.sendto(json.dumps(event).encode(), str(EVENT_SOCKET))
    finally:
        producer.close()


def wait_for_revoked(pane):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        response = bridge_call("execution_status", {"pane": pane})
        lease = response.get("result", {}).get("lease")
        if lease and lease.get("state") == "REVOKED":
            return lease
        time.sleep(0.05)
    raise RuntimeError("lease was not revoked")


def start_mcp(enable_actions=False):
    command = [
        sys.executable,
        str(MCP_SCRIPT),
        "--bridge-socket",
        str(CONTROL_SOCKET),
    ]
    if enable_actions:
        command.append("--enable-actions")
    return subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


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
    tmux("new-session", "-d", "-s", SESSION, "-c", str(PROJECT_ROOT))
    pane = tmux(
        "display-message",
        "-p",
        "-t",
        SESSION,
        "#{pane_id}",
        capture=True,
    ).stdout.strip()
    tmux("send-keys", "-t", pane, "-l", f"printf '{MARKER}\\n'")
    tmux("send-keys", "-t", pane, "Enter")
    time.sleep(0.2)

    bridge = subprocess.Popen(
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
    mcp = None
    try:
        wait_for(CONTROL_SOCKET)
        mcp = start_mcp()
        discovery = mcp_request(
            mcp,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "server/discover",
                "params": modern_params(),
            },
        )
        tools = mcp_request(
            mcp,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": modern_params(),
            },
        )
        state = mcp_request(
            mcp,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": modern_params(
                    name="terminal_state",
                    arguments={"pane": pane},
                ),
            },
        )
        history = mcp_request(
            mcp,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": modern_params(
                    name="terminal_read",
                    arguments={"pane": pane, "lines": 20},
                ),
            },
        )
        disabled = mcp_request(
            mcp,
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": modern_params(
                    name="terminal_type",
                    arguments={"pane": pane, "generation": 1, "text": "id"},
                ),
            },
        )
        names = [tool["name"] for tool in tools["result"]["tools"]]
        history_payload = history["result"]["structuredContent"]
        state_payload = state["result"]["structuredContent"]

        mcp.terminate()
        mcp.wait(timeout=3)
        mcp = start_mcp(enable_actions=True)
        action_tools = mcp_request(
            mcp,
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/list",
                "params": modern_params(),
            },
        )
        action_names = [
            tool["name"] for tool in action_tools["result"]["tools"]
        ]
        acquired = bridge_call("acquire_execution", {"pane": pane})
        generation = acquired["result"]["generation"]
        typed = mcp_request(
            mcp,
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": modern_params(
                    name="terminal_type",
                    arguments={
                        "pane": pane,
                        "generation": generation,
                        "text": f"printf '{WRITE_MARKER}\\n'",
                    },
                ),
            },
        )
        entered = mcp_request(
            mcp,
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": modern_params(
                    name="terminal_key",
                    arguments={
                        "pane": pane,
                        "generation": generation,
                        "key": "Enter",
                    },
                ),
            },
        )
        time.sleep(0.2)
        agent_interrupt = mcp_request(
            mcp,
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": modern_params(
                    name="terminal_interrupt",
                    arguments={"pane": pane, "generation": generation},
                ),
            },
        )
        active_after_agent = bridge_call("execution_status", {"pane": pane})
        task_submit = mcp_request(
            mcp,
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": modern_params(
                    name="terminal_task_block",
                    arguments={
                        "pane": pane,
                        "generation": generation,
                        "commands": [
                            "printf 'TASK_BLOCK_ALPHA\\n'",
                            "printf 'TASK_BLOCK_BETA\\n'",
                        ],
                    },
                ),
            },
        )
        block_id = task_submit["result"]["structuredContent"]["result"]["block_id"]
        explicit_task_submits = []
        for request_id, command in enumerate(
            ("printf 'TASK_BLOCK_ALPHA\\n'", "printf 'TASK_BLOCK_BETA\\n'"),
            11,
        ):
            explicit_task_submits.append(mcp_request(
                mcp,
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "tools/call",
                    "params": modern_params(
                        name="terminal_submit",
                        arguments={
                            "pane": pane,
                            "generation": generation,
                            "text": command,
                            "expected_duration_ms": 30_000,
                            "resource_class": "normal",
                        },
                    ),
                },
            ))
            time.sleep(0.1)
        task_observe = mcp_request(
            mcp,
            {
                "jsonrpc": "2.0",
                "id": 13,
                "method": "tools/call",
                "params": modern_params(
                    name="terminal_task_observe",
                    arguments={"block_id": block_id},
                ),
            },
        )
        emit_human_event(pane)
        revoked = wait_for_revoked(pane)
        stale = mcp_request(
            mcp,
            {
                "jsonrpc": "2.0",
                "id": 50,
                "method": "tools/call",
                "params": modern_params(
                    name="terminal_type",
                    arguments={
                        "pane": pane,
                        "generation": generation,
                        "text": STALE_MARKER,
                    },
                ),
            },
        )
        time.sleep(0.2)
        pane_content = tmux(
            "capture-pane",
            "-p",
            "-t",
            pane,
            "-S",
            "-100",
            capture=True,
        ).stdout
        audit_actions = [
            entry["action"]
            for entry in bridge_call("audit_log")["result"]["entries"]
        ]
        checks = {
            "modern_discovery": (
                "2026-07-28" in discovery["result"]["supportedVersions"]
            ),
            "read_only_tool_catalog": names
            == [
                "terminal_list",
                "get_active_pane",
                "terminal_read",
                "terminal_read_delta",
                "terminal_state",
                "terminal_wait_delta",
            ],
            "state_crossed_mcp_and_bridge": (
                state_payload.get("result", {}).get("pane") == pane
            ),
            "history_crossed_mcp_and_bridge": (
                MARKER in history_payload.get("result", {}).get("content", "")
            ),
            "actions_disabled_by_default": (
                disabled.get("error", {}).get("code") == -32602
            ),
            "bridge_audit_received_reads": all(
                action in audit_actions
                for action in ("READ", "STATE")
            ),
            "actions_explicitly_enabled": all(
                name in action_names
                for name in (
                    "terminal_type",
                    "terminal_key",
                    "terminal_interrupt",
                    "terminal_task_block",
                    "terminal_task_observe",
                )
            ),
            "task_block_is_local_and_commands_are_explicit": (
                task_submit["result"]["isError"] is False
                and task_submit["result"]["structuredContent"]["result"]["writes_to_pane"]
                is False
                and all(not item["result"]["isError"] for item in explicit_task_submits)
                and task_observe["result"]["structuredContent"]["result"]["state"]
                == "ACTIVE"
                and "TASK_BLOCK_ALPHA"
                in task_observe["result"]["structuredContent"]["result"]["content"]
                and "TASK_BLOCK_BETA"
                in task_observe["result"]["structuredContent"]["result"]["content"]
            ),
            "lease_acquisition_not_exposed": (
                "acquire_execution" not in action_names
            ),
            "out_of_band_lease_accepted": (
                acquired.get("ok") is True and generation >= 1
            ),
            "mcp_write_and_enter_accepted": (
                typed["result"]["isError"] is False
                and entered["result"]["isError"] is False
                and WRITE_MARKER in pane_content
            ),
            "agent_interrupt_kept_lease_active": (
                agent_interrupt["result"]["isError"] is False
                and active_after_agent["result"]["lease"]["state"]
                == "ACTIVE"
            ),
            "human_event_revoked_lease": revoked["state"] == "REVOKED",
            "stale_mcp_write_rejected": (
                stale["result"]["isError"] is True
                and stale["result"]["structuredContent"]["error"]["code"]
                == "EXECUTION_LEASE_INVALID"
            ),
            "stale_write_absent_from_pane": STALE_MARKER not in pane_content,
            "action_audit_complete": all(
                action in audit_actions
                for action in (
                    "LEASE_ACQUIRE",
                    "TYPE",
                    "KEY",
                    "AGENT_INTERRUPT",
                    "TASK_BLOCK_CREATE",
                    "TASK_BLOCK_OBSERVE",
                    "HUMAN_INTERRUPT",
                    "LEASE_REVOKE",
                    "ACTION_DENY",
                )
            ),
        }
        print("Full MCP read/write end-to-end checks:")
        print(json.dumps(checks, indent=2))
        if not checks["task_block_is_local_and_commands_are_explicit"]:
            print("Task block diagnostic:")
            print(
                json.dumps(
                    task_observe["result"]["structuredContent"],
                    indent=2,
                )
            )
            print("Pane tail diagnostic:")
            print(pane_content[-4000:])
        if all(checks.values()):
            print("\nPASS: MCP stdio reached the authorized tmux pane read-only.")
            print("PASS: Action tools were absent and rejected by default.")
            print("PASS: explicitly enabled MCP actions honored the lease.")
            print("PASS: Human Override revoked and blocked stale MCP writes.")
            return 0
        print("\nFAIL: minimal MCP end-to-end validation failed.")
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
