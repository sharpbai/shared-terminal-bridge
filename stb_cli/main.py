"""Agent CLI dispatch; management is a separate executable/package."""
import subprocess
import sys
from stb_cli.commands_execution import handle_execution_command
from stb_cli.commands_sessions import handle_session_command
from stb_cli.discovery import handle_discovery_command
from stb_cli.parser import parser
from stb_cli.bootstrap import handle_context_command


def run_cli(command_parser, handlers):
    if len(sys.argv) == 1:
        command_parser.print_help()
        return 0
    args = command_parser.parse_args()
    try:
        for handler in handlers:
            result = handler(args)
            if result is not None:
                return result
        raise RuntimeError(f"未知命令：{args.command}")
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"错误：{error}", file=sys.stderr)
        print(f"可运行 {command_parser.prog} --help 查看中文使用说明。", file=sys.stderr)
        return 1


def main():
    return run_cli(parser(), (handle_discovery_command, handle_context_command,
                             handle_session_command, handle_execution_command))
