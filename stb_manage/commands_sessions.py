"""Managed-session CLI commands."""

import json
import os
import pathlib

from stb_cli.client import bridge_call, find_session, managed_sessions, tmux
from stb_manage.daemon import start_bridge_daemon


SESSION_COMMANDS = {"create", "enter", "stop"}


def enter_session(socket_name, name):
    if find_session(socket_name, name) is None:
        raise RuntimeError(f"不是托管会话或会话不存在：{name}")
    if os.environ.get("TMUX"):
        result = tmux(socket_name, "switch-client", "-t", name, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"无法切换到会话：{name}")
        return
    os.execvp(
        "tmux",
        ["tmux", "-L", socket_name, "attach-session", "-t", name],
    )


def _require_session(args):
    session = find_session(args.tmux_socket, args.name)
    if session is None:
        raise RuntimeError(f"不是托管会话或会话不存在：{args.name}")
    return session


def _create(args):
    daemon = start_bridge_daemon(args.tmux_socket, args.bridge_socket)
    bootstrap = daemon.get("bootstrap")
    try:
        result = bridge_call(
            args.bridge_socket,
            "terminal_session_create",
            {"name": args.name, "cwd": str(pathlib.Path(args.cwd).resolve())},
        )
    finally:
        if bootstrap:
            tmux(args.tmux_socket, "kill-session", "-t", bootstrap, check=False)
    if daemon.get("started"):
        print(f"已自动启动 Bridge daemon（PID {daemon['pid']}）。")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.enter:
        enter_session(args.tmux_socket, args.name)


def handle_session_command(args):
    if args.command not in SESSION_COMMANDS:
        return None
    if args.command == "create":
        _create(args)
    elif args.command == "enter":
        enter_session(args.tmux_socket, args.name)
    elif args.command == "stop":
        _require_session(args)
        if args.direct:
            tmux(args.tmux_socket, "kill-session", "-t", args.name)
            print(f"已直接停止托管会话：{args.name}")
        else:
            result = bridge_call(
                args.bridge_socket, "terminal_session_stop", {"name": args.name}
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
