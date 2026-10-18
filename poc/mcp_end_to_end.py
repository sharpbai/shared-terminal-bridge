#!/usr/bin/env python3
"""Isolated real MCP stdio -> Bridge socket -> tmux, task-only API."""
import json
import pathlib
import shlex
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bridge.local_bridge import request as bridge_request


def main():
    socket_name = "stb-mcp-" + uuid.uuid4().hex[:10]
    processes = []
    def tmux(*args):
        return subprocess.run(["tmux", "-L", socket_name, *args],
            capture_output=True, text=True, check=True).stdout
    def until(check):
        deadline = time.monotonic() + 5
        while not check():
            if time.monotonic() >= deadline:
                raise RuntimeError("fixture timeout")
            time.sleep(.01)
    try:
        with tempfile.TemporaryDirectory(prefix="mcp-task-", dir="/tmp") as folder:
            folder = pathlib.Path(folder)
            control = folder / "control.sock"
            tmux("new-session", "-d", "-s", "test",
                 "env PS1='MCP> ' /bin/bash --noprofile --norc -i")
            until(lambda: tmux("capture-pane", "-p", "-t", "%0").rstrip().endswith("MCP>"))
            bridge = subprocess.Popen([sys.executable, str(ROOT / "bridge/local_bridge.py"),
                "serve", "--tmux-socket", socket_name, "--control-socket", str(control),
                "--event-socket", str(folder / "events.sock"), "--state-file", str(folder / "state.json"),
                "--history-file", str(folder / "history.jsonl"), "--allow-pane", "%0"],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            processes.append(bridge)
            until(control.exists)
            assert bridge_request(control, "install_human_binding", {})["ok"]
            def start(actions=False):
                args = [sys.executable, str(ROOT / "mcp_server/server.py"), "--bridge-socket", str(control)]
                if actions:
                    args.append("--enable-actions")
                process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True)
                processes.append(process)
                return process
            def request(process, method, params):
                process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                    "params": {**params, "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        "io.modelcontextprotocol/clientCapabilities": {}}}}) + "\n")
                process.stdin.flush()
                return json.loads(process.stdout.readline())
            def call(process, name, **args):
                return request(process, "tools/call", {"name": name, "arguments": args})
            readonly = start()
            assert not call(readonly, "terminal_state", pane="%0")["result"]["isError"]
            assert "error" in call(readonly, "terminal_run", pane="%0", request_id="denied", text="echo forbidden")
            print("PASS: MCP stdio reached the authorized tmux pane read-only.")
            print("PASS: Action tools were absent and rejected by default.")
            model = start(True)
            tools = request(model, "tools/list", {})["result"]["tools"]
            assert all("generation" not in t["inputSchema"]["properties"] for t in tools)
            result = call(model, "terminal_run", pane="%0", request_id="one",
                          text="printf 'MODEL_TASK_OK\\n'", wait_ms=5000)["result"]["structuredContent"]
            assert result["ok"] and result["result"]["state"] == "COMPLETED", result
            assert "generation" not in result["result"]
            print("PASS: explicitly enabled MCP actions honored the lease.")
            slow = call(model, "terminal_run", pane="%0", request_id="slow", text="sleep 60", wait_ms=1)
            job_id = slow["result"]["structuredContent"]["result"]["job_id"]
            until(lambda: tmux("display-message", "-p", "-t", "%0", "#{pane_current_command}").strip() == "sleep")
            # Invoke the actual tmux client binding; source remains Human.
            binding = shlex.split(tmux("list-keys", "-T", "root", "C-c"))
            tmux(*binding[binding.index("C-c") + 1:])
            def interrupted():
                status = call(model, "terminal_job_status", job_id=job_id)
                return status["result"]["structuredContent"]["result"]["state"] == "INTERRUPTED_BY_HUMAN"
            until(interrupted)
            newer = call(model, "terminal_run", pane="%0", request_id="new", text="sleep 60", wait_ms=1)
            assert not newer["result"]["isError"], newer
            assert call(model, "terminal_interrupt_job", job_id=job_id)["result"]["isError"]
            replay = call(model, "terminal_run", pane="%0", request_id="slow", text="sleep 60", wait_ms=1)
            assert replay["result"]["structuredContent"]["result"]["state"] == "INTERRUPTED_BY_HUMAN"
            print("PASS: Human Override revoked and blocked stale MCP writes.")
    finally:
        for process in reversed(processes):
            process.terminate()
            process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream:
                    stream.close()
        subprocess.run(["tmux", "-L", socket_name, "kill-server"], capture_output=True)


if __name__ == "__main__":
    main()
