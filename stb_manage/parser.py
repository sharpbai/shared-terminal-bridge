"""Human maintenance CLI, intentionally without run/input/wait."""
import os
from stb_cli.parser_common import command_root, configure_help
from stb_cli.parser_sessions import add_session_parsers
from stb_manage.parser_admin import add_admin_parsers


def parser():
    root, commands = command_root("stb-manage",
        "STB 人工管理入口：会话生命周期、daemon、历史与救急清理。\n"
        "Agent 执行请使用 stb；管理操作不作为普通任务的前置步骤。", socket_options=True)
    add_session_parsers(commands, configure_help)
    create = configure_help(commands.add_parser("create", help="创建托管会话"))
    create.add_argument("name")
    create.add_argument("--cwd", default=os.getcwd())
    create.add_argument("--enter", action="store_true")
    enter = configure_help(commands.add_parser("enter", help="进入或切换到托管会话"))
    enter.add_argument("name")
    stop = configure_help(commands.add_parser("stop", help="停止托管会话"))
    stop.add_argument("name")
    stop.add_argument("--direct", action="store_true", help="Bridge 不可用时直接停止托管会话")
    add_admin_parsers(commands, configure_help)
    mcp = configure_help(commands.add_parser("mcp", help="显示 MCP 注册指引，不修改配置"))
    mcp.add_argument("--json", action="store_true")
    return root
