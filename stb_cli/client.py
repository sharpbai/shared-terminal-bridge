"""tmux discovery and Bridge Unix-socket client operations."""

import json
import socket
import subprocess

from stb_cli.config import SESSION_FORMAT

def tmux(socket_name, *arguments, capture=False, check=True):
    return subprocess.run(
        ["tmux", "-L", socket_name, *arguments],
        check=check,
        capture_output=capture,
        text=True,
    )

def managed_sessions(socket_name):
    result = tmux(
        socket_name,
        "list-sessions",
        "-F",
        SESSION_FORMAT,
        capture=True,
        check=False,
    )
    sessions = []
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) != 9 or fields[4] != "1":
            continue
        (
            name,
            session_id,
            windows,
            attached,
            _,
            managed_id,
            created_at,
            history_limit,
            mouse,
        ) = fields
        pane = tmux(
            socket_name,
            "display-message",
            "-p",
            "-t",
            name,
            "#{pane_id}",
            capture=True,
        ).stdout.strip()
        sessions.append(
            {
                "name": name,
                "session_id": session_id,
                "pane": pane,
                "windows": int(windows),
                "attached": int(attached),
                "managed_id": managed_id,
                "created_at": created_at,
                "history_limit": int(history_limit),
                "mouse": mouse == "1",
            }
        )
    return sessions

def find_session(socket_name, name):
    return next(
        (session for session in managed_sessions(socket_name) if session["name"] == name),
        None,
    )

def bridge_call(socket_path, method, params=None):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(str(socket_path))
        with client:
            writer = client.makefile("w", encoding="utf-8")
            reader = client.makefile("r", encoding="utf-8")
            writer.write(json.dumps({"method": method, "params": params or {}}) + "\n")
            writer.flush()
            line = reader.readline()
    except OSError as error:
        raise RuntimeError(f"无法连接 Bridge（{socket_path}）：{error}") from error
    if not line:
        raise RuntimeError("Bridge 返回了空响应")
    response = json.loads(line)
    if not response.get("ok"):
        raise RuntimeError(json.dumps(response["error"], ensure_ascii=False))
    return response["result"]

def bridge_available(socket_path):
    try:
        bridge_call(socket_path, "terminal_session_list")
        return True
    except RuntimeError:
        return False
