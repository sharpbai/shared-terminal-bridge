"""History and daemon administration CLI commands."""

import json

from stb_cli.client import bridge_call
from stb_cli.config import DEFAULT_LOG_FILE
from stb_cli.daemon import (
    bridge_available,
    bridge_process_running,
    start_bridge_daemon,
    stop_bridge_daemon,
)


def _history(args):
    result = bridge_call(
        args.bridge_socket,
        "terminal_history",
        {
            "session": args.name,
            "pane": args.pane,
            "action": args.action,
            "limit": args.limit,
        },
    )
    entries = result.get("entries", [])
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif not entries:
        print("没有匹配的交互历史。")
    else:
        print(f"交互历史：{len(entries)} 条")
        for entry in entries:
            target = entry.get("session") or entry.get("pane") or "-"
            summary = (
                entry.get("command") or entry.get("state") or entry.get("reason") or ""
            )
            print(
                f"{entry.get('timestamp', '')}  "
                f"{entry.get('action', ''):<20} {target}  {summary}"
            )
        print(f"\n历史文件：{result.get('history_file', '')}")


def _daemon(args):
    if args.action == "start":
        result = start_bridge_daemon(args.tmux_socket, args.bridge_socket)
        if result["already_running"]:
            print("Bridge daemon 已在运行。")
        else:
            print(f"Bridge daemon 已启动，PID：{result['pid']}")
            if result.get("stale_state_backup"):
                print("已归档失联 tmux server 的旧状态：" f"{result['stale_state_backup']}")
    elif args.action == "status":
        running, pid = bridge_process_running()
        available = bridge_available(args.bridge_socket)
        print(f"进程：{'运行中' if running else '未运行'}")
        if pid:
            print(f"PID：{pid}")
        print(f"控制 socket：{'可用' if available else '不可用'}")
        print(f"日志：{DEFAULT_LOG_FILE}")
        if not running or not available:
            return 1
    elif args.action == "stop":
        print("Bridge daemon 已停止。" if stop_bridge_daemon() else "Bridge daemon 未运行。")
    elif args.action == "logs":
        if DEFAULT_LOG_FILE.exists():
            lines = DEFAULT_LOG_FILE.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()[-50:]
            print("\n".join(lines))
        else:
            print("暂无 Bridge 日志。")
    return 0


def handle_admin_command(args):
    if args.command == "history":
        _history(args)
        return 0
    if args.command == "daemon":
        return _daemon(args)
    return None
