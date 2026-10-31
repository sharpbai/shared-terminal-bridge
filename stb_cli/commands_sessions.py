"""Read-only session inspection. Lifecycle mutations live in stb_manage."""
import json
from stb_cli.client import find_session, managed_sessions
from stb_cli.output import print_session_info, print_sessions
from stb_cli.session_info import session_info


def _require_session(args):
    session = find_session(args.tmux_socket, args.name)
    if session is None:
        raise RuntimeError(f"不是托管会话或会话不存在：{args.name}")
    return session


def handle_session_command(args):
    if args.command == "list":
        print_sessions(managed_sessions(args.tmux_socket), args.json)
    elif args.command == "info":
        session = session_info(args, _require_session(args))
        if args.json:
            print(json.dumps(session, ensure_ascii=False, indent=2))
        else:
            print_session_info(session)
    else:
        return None
    return 0
