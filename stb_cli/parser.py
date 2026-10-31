"""Agent discovery, observation and job execution only."""
from stb_cli.parser_common import command_root, configure_help
from stb_cli.parser_execution import add_execution_parsers
from stb_cli.parser_sessions import add_session_parsers


def parser():
    root, commands = command_root("stb",
        "STB Agent 执行入口。\n首次使用：已知会话名先 stb bootstrap 会话名；未知时先 list。\n"
        "bootstrap 已包含规则和终端上下文；后续刷新用 stb context 会话名 --lines 40。\n"
        "执行返回 job ID，后续用 job/wait/interrupt；不要因超时重提。")
    add_session_parsers(commands, configure_help)
    add_execution_parsers(commands, configure_help)
    for name, help_text in (("bootstrap", "首次只读接入：返回终端上下文、规则与执行模板"),
                            ("context", "只读刷新终端画面与状态，确认实际环境；不执行命令")):
        context = configure_help(commands.add_parser(name, help=help_text))
        context.add_argument("name", metavar="会话名")
        context.add_argument("--lines", type=int, choices=range(1, 101), default=40,
                             metavar="1-100", help="最多读取的终端行数，默认 40")
    entry = configure_help(commands.add_parser("discover", help="Agent 自发现：能力、规则与调用引导"))
    entry.add_argument("--json", action="store_true", help="机器可读 JSON")
    return root
