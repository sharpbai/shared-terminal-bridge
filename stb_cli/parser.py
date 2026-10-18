"""管理并进入 Shared Terminal Bridge 托管的 tmux 会话。"""

import argparse
import pathlib

from stb_cli.config import DEFAULT_BRIDGE_SOCKET
from stb_cli.parser_admin import add_admin_parsers
from stb_cli.parser_execution import add_execution_parsers
from stb_cli.parser_sessions import add_session_parsers


class ChineseArgumentParser(argparse.ArgumentParser):
    def format_help(self):
        help_text = super().format_help()
        if help_text.startswith("usage:"):
            help_text = "用法：" + help_text[len("usage:"):]
        return help_text


def configure_help(command_parser):
    command_parser._positionals.title = "位置参数"
    command_parser._optionals.title = "选项"
    for action in command_parser._actions:
        if action.dest == "help":
            action.help = "显示帮助并退出"
    return command_parser


def parser():
    root = ChineseArgumentParser(
        description=(
            f"{__doc__}\n\n"
            "首次使用 / Agent 接入：\n"
            "  不知道如何使用？先运行 stb discover --json 获取能力与安全规则。\n"
            "  要让 Codex 使用共享终端？运行 stb mcp 查看 MCP 全局接入指引。\n"
            "  MCP 已连接？直接按工具 instructions/schema 操作，无需 skill。\n"
            "  人工进入终端：stb list，然后 stb enter <会话名称>。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "常用示例：\n"
            "  stb discover --json    # Agent 自发现入口\n"
            "  stb mcp                # MCP 全局接入指引\n"
            "  stb list\n"
            "  stb enter my-session\n"
            "  stb create my-session --cwd /path/to/project --enter\n"
            "  stb lease my-session\n"
            "  stb approvals\n"
            "  stb jobs\n"
            "  stb history verify33\n"
            "  stb watch job_a1b2c3d4e5f6\n"
            "  stb approve lr_a1b2c3d4e5f6\n"
            "  stb stop my-session\n\n"
            "  stb daemon status\n"
            "提示：MCP 创建会话后，直接执行 stb enter <会话名称> 即可进入。"
        ),
    )
    configure_help(root)
    root.add_argument(
        "--tmux-socket",
        default="default",
        metavar="名称",
        help="tmux socket 名称（默认：default）",
    )
    root.add_argument(
        "--bridge-socket",
        type=pathlib.Path,
        default=DEFAULT_BRIDGE_SOCKET,
        metavar="路径",
        help="Bridge Unix socket 路径",
    )
    subparsers = root.add_subparsers(
        dest="command",
        required=True,
        title="可用命令",
        metavar="命令",
        parser_class=ChineseArgumentParser,
    )
    add_session_parsers(subparsers, configure_help)
    add_execution_parsers(subparsers, configure_help)
    add_admin_parsers(subparsers, configure_help)
    for name, description in (
        ("discover", "自发现：能力导航、Agent 入口与安全规则（无需 daemon）"),
        ("mcp", "显示 MCP 全局注册指引，不修改配置"),
    ):
        entry = configure_help(subparsers.add_parser(name, help=description, description=description))
        entry.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    return root
