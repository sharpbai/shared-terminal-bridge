"""Argument definitions for history and daemon commands."""


def add_admin_parsers(subparsers, configure_help):
    cleanup = configure_help(subparsers.add_parser('cleanup-tasks',
        help='备份并清理未结束任务状态（默认只预览，不停止终端命令）'))
    cleanup.add_argument('--pane', help='仅清理指定 pane，例如 %%21')
    cleanup.add_argument('--yes', action='store_true', help='确认清理并重启 Bridge；撤销所有租约')
    history = configure_help(subparsers.add_parser("history", help="查看持久化的 tmux/STB 交互历史"))
    history.add_argument("name", nargs="?", metavar="会话", help="按托管会话名称筛选")
    history.add_argument("--pane", metavar="面板", help="按 pane ID 筛选")
    history.add_argument("--action", metavar="动作", help="按动作类型筛选")
    history.add_argument("--limit", type=int, default=100, metavar="条数", help="返回最近记录数（1-1000）")
    history.add_argument("--json", action="store_true", help="输出机器可读的 JSON")

    daemon = configure_help(subparsers.add_parser("daemon", help="启动、查看或停止后台 Bridge"))
    daemon.add_argument(
        "action",
        choices=("start", "status", "stop", "logs"),
        metavar="操作",
        help="start / status / stop / logs",
    )


__all__ = ["add_admin_parsers"]
