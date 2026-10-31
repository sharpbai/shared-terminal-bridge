"""Shared Chinese help and socket options, without management commands."""
import argparse
import pathlib
from stb_cli.config import DEFAULT_BRIDGE_SOCKET

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


def command_root(prog, description, *, socket_options=False):
    root = ChineseArgumentParser(prog=prog, description=description,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    configure_help(root)
    root.set_defaults(tmux_socket="default", bridge_socket=DEFAULT_BRIDGE_SOCKET)
    if socket_options:
        root.add_argument("--tmux-socket", default="default", metavar="名称", help="tmux socket 名称")
        root.add_argument("--bridge-socket", type=pathlib.Path, default=DEFAULT_BRIDGE_SOCKET,
                          metavar="路径", help="Bridge Unix socket 路径")
    subparsers = root.add_subparsers(dest="command", required=True, title="可用命令",
                                    metavar="命令", parser_class=ChineseArgumentParser)
    return root, subparsers
