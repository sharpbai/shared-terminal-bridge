"""Start, inspect, and stop the local Bridge daemon."""

import os
import pathlib
import subprocess
import sys
import time

from stb_cli.client import bridge_available, bridge_call, managed_sessions, tmux
from stb_cli.config import (
    BRIDGE_SCRIPT, DEFAULT_BRIDGE_SOCKET, DEFAULT_EVENT_SOCKET,
    DEFAULT_HISTORY_FILE, DEFAULT_LOG_FILE, DEFAULT_PID_FILE,
    DEFAULT_STATE_FILE, PROJECT_ROOT,
)

def read_pid():
    try:
        return int(DEFAULT_PID_FILE.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None

def process_command(pid):
    if pid is None:
        return ""
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()

def bridge_process_running():
    pid = read_pid()
    command = process_command(pid)
    return bool(pid and str(BRIDGE_SCRIPT) in command), pid

def start_bridge_daemon(tmux_socket, bridge_socket):
    if bridge_available(bridge_socket):
        bridge_call(bridge_socket, "install_human_binding")
        return {"started": False, "pid": read_pid(), "already_running": True}
    running, pid = bridge_process_running()
    if running:
        raise RuntimeError(
            f"Bridge 进程 {pid} 正在运行，但 socket 不可用；请查看 {DEFAULT_LOG_FILE}"
        )

    bootstrap = None
    stale_state_backup = None
    probe = tmux(tmux_socket, "list-sessions", capture=True, check=False)
    if probe.returncode != 0:
        # The persisted pane/lease identities belong to a tmux server that no
        # longer exists. Preserve them for diagnosis, but do not attach them to
        # the new server that new-session is about to create.
        if DEFAULT_STATE_FILE.exists():
            stale_state_backup = DEFAULT_STATE_FILE.with_name(
                f"{DEFAULT_STATE_FILE.stem}.orphaned-{int(time.time())}.json"
            )
            DEFAULT_STATE_FILE.replace(stale_state_backup)
        bootstrap = f"__stb_bootstrap_{os.getpid()}"
        tmux(tmux_socket, "new-session", "-d", "-s", bootstrap)

    log_file = DEFAULT_LOG_FILE.open("a", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            str(BRIDGE_SCRIPT),
            "serve",
            "--tmux-socket",
            tmux_socket,
            "--control-socket",
            str(bridge_socket),
            "--event-socket",
            str(DEFAULT_EVENT_SOCKET),
            "--state-file",
            str(DEFAULT_STATE_FILE),
            "--history-file",
            str(DEFAULT_HISTORY_FILE),
            "--allow-session-management",
        ],
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=log_file,
        start_new_session=True,
        text=True,
    )
    log_file.close()
    DEFAULT_PID_FILE.write_text(f"{process.pid}\n", encoding="utf-8")
    os.chmod(DEFAULT_PID_FILE, 0o600)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if bridge_available(bridge_socket):
            bridge_call(bridge_socket, "install_human_binding")
            return {
                "started": True,
                "pid": process.pid,
                "already_running": False,
                "bootstrap": bootstrap,
                "stale_state_backup": (
                    str(stale_state_backup) if stale_state_backup else None
                ),
            }
        if process.poll() is not None:
            break
        time.sleep(0.05)
    if bootstrap:
        tmux(tmux_socket, "kill-session", "-t", bootstrap, check=False)
    raise RuntimeError(f"Bridge 启动失败；请查看 {DEFAULT_LOG_FILE}")

def stop_bridge_daemon():
    running, pid = bridge_process_running()
    if not running:
        DEFAULT_PID_FILE.unlink(missing_ok=True)
        return False
    os.kill(pid, 15)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if not process_command(pid):
            DEFAULT_PID_FILE.unlink(missing_ok=True)
            return True
        time.sleep(0.05)
    raise RuntimeError(f"Bridge 进程 {pid} 未在 5 秒内退出")
