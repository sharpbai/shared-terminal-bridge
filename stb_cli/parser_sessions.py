"""Read-only session discovery for Agent and human inspection."""


def add_session_parsers(subparsers, configure_help):
    listing = configure_help(subparsers.add_parser("list", help="列出托管会话"))
    listing.add_argument("--json", action="store_true", help="机器可读 JSON")
    info = configure_help(subparsers.add_parser("info", help="查看会话、所有窗口面板及当前任务 ID"))
    info.add_argument("name", metavar="名称")
    info.add_argument("--json", action="store_true", help="机器可读 JSON")
