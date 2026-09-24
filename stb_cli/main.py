"""Command dispatch for the STB command-line client."""

import os
import subprocess
import sys

from stb_cli.client import find_session, tmux
from stb_cli.commands_admin import handle_admin_command
from stb_cli.commands_execution import handle_execution_command
from stb_cli.commands_sessions import enter_session, handle_session_command
from stb_cli.parser import parser


COMMAND_HANDLERS = (
    handle_session_command,
    handle_execution_command,
    handle_admin_command,
)


def main():
    args = parser().parse_args()
    try:
        for handler in COMMAND_HANDLERS:
            result = handler(args)
            if result is not None:
                return result
        raise RuntimeError(f"未知命令：{args.command}")
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"错误：{error}", file=sys.stderr)
        print("可运行 stb --help 查看中文使用说明。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
