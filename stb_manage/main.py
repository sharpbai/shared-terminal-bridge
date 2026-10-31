"""Independent human management dispatcher, never dispatches execution."""
from stb_cli.main import run_cli
from stb_cli.commands_sessions import handle_session_command as inspect_session
from stb_cli.discovery import handle_discovery_command
from stb_manage.commands_sessions import handle_session_command
from stb_manage.commands_admin import handle_admin_command
from stb_manage.parser import parser


def main():
    return run_cli(parser(), (inspect_session, handle_session_command, handle_admin_command, handle_discovery_command))
