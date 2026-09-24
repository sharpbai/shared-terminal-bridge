"""Argument definitions for managed-session commands."""

import os


def add_session_parsers(subparsers, configure_help):
    list_parser = configure_help(subparsers.add_parser("list", help="列出所有托管会话"))
    list_parser.add_argument("--json", action="store_true", help="输出机器可读的 JSON")

    create = configure_help(subparsers.add_parser("create", help="通过 Bridge 创建托管会话"))
    create.add_argument("name", metavar="名称", help="新会话名称")
    create.add_argument("--cwd", default=os.getcwd(), metavar="目录", help="会话工作目录")
    create.add_argument("--enter", action="store_true", help="创建成功后立即进入")

    enter = configure_help(subparsers.add_parser("enter", help="进入或切换到托管会话"))
    enter.add_argument("name", metavar="名称", help="要进入的会话名称")

    info = configure_help(subparsers.add_parser("info", help="查看一个托管会话的详细信息"))
    info.add_argument("name", metavar="名称", help="会话名称")
    info.add_argument("--json", action="store_true", help="输出机器可读的 JSON")

    panes = configure_help(subparsers.add_parser("panes", help="列出托管会话中的面板"))
    panes.add_argument("name", metavar="名称", help="会话名称")

    stop = configure_help(subparsers.add_parser("stop", help="停止并清理托管会话"))
    stop.add_argument("name", metavar="名称", help="要停止的会话名称")
    stop.add_argument(
        "--direct",
        action="store_true",
        help="Bridge 不可用时直接停止；仅限带托管标记的会话",
    )


__all__ = ["add_session_parsers"]
