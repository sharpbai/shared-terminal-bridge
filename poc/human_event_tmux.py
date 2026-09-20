#!/usr/bin/env python3
"""PoC: distinguish human Ctrl+C from tmux send-keys Ctrl+C.

The test uses an isolated tmux server so it does not change the user's normal
tmux server or ~/.tmux.conf. Human input passes through tmux's root key table;
`tmux send-keys` writes directly to a pane and therefore bypasses the binding.
"""

import argparse
import pathlib
import shlex
import subprocess
import sys


DEFAULT_SOCKET = "human-event-poc"
DEFAULT_SESSION = "human-event-poc"
DEFAULT_LOG = pathlib.Path("/tmp/tmux-human-events.log")


def tmux(socket_name: str, *arguments: str, check: bool = True):
    return subprocess.run(
        ["tmux", "-L", socket_name, *arguments],
        check=check,
        text=True,
    )


def ensure_session(socket_name: str, session_name: str) -> None:
    exists = tmux(
        socket_name,
        "has-session",
        "-t",
        session_name,
        check=False,
    )
    if exists.returncode != 0:
        tmux(
            socket_name,
            "new-session",
            "-d",
            "-s",
            session_name,
            "-c",
            str(pathlib.Path.cwd()),
        )


def install_binding(socket_name: str, event_log: pathlib.Path) -> None:
    quoted_log = shlex.quote(str(event_log))
    record_event = (
        'printf "%s HUMAN_INTERRUPT pane=%s client=%s\\n" '
        '"$(date +%FT%T%z)" "#{pane_id}" "#{client_name}" '
        f">> {quoted_log}"
    )

    # send-keys runs first so logging failure cannot block SIGINT.
    tmux(
        socket_name,
        "bind-key",
        "-T",
        "root",
        "C-c",
        "send-keys",
        "C-c",
        r"\;",
        "run-shell",
        "-b",
        record_event,
    )


def show_events(event_log: pathlib.Path) -> None:
    print()
    print(f"Events in {event_log}:")
    if event_log.exists():
        contents = event_log.read_text(encoding="utf-8")
        print(contents, end="" if contents.endswith("\n") else "\n")
    else:
        print("(no events)")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Test human Ctrl+C detection at the tmux input layer."
    )
    parser.add_argument("--socket", default=DEFAULT_SOCKET)
    parser.add_argument("--session", default=DEFAULT_SESSION)
    parser.add_argument("--log", type=pathlib.Path, default=DEFAULT_LOG)
    parser.add_argument(
        "--agent-ctrl-c",
        action="store_true",
        help="inject Ctrl+C with tmux send-keys without attaching",
    )
    parser.add_argument(
        "--show-events",
        action="store_true",
        help="show the event log without attaching",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        ensure_session(args.socket, args.session)
        install_binding(args.socket, args.log)

        if args.agent_ctrl_c:
            tmux(
                args.socket,
                "send-keys",
                "-t",
                args.session,
                "C-c",
            )
            print("Injected agent Ctrl+C with tmux send-keys.")
            print("It should not create a HUMAN_INTERRUPT event.")
            show_events(args.log)
            return 0

        if args.show_events:
            show_events(args.log)
            return 0

        print("Human Event Layer tmux PoC")
        print(f"Isolated tmux socket: {args.socket}")
        print(f"Session: {args.session}")
        print(f"Event log: {args.log}")
        print()
        print("Inside tmux, run:  ping 1.1.1.1")
        print("Then physically press Ctrl+C and detach with Ctrl+B, D.")
        print("The script will display the resulting event log.")
        print()

        tmux(args.socket, "attach-session", "-t", args.session)
        show_events(args.log)
        return 0
    except FileNotFoundError:
        print("tmux is not installed or not available in PATH.", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        print(
            f"tmux command failed with exit code {error.returncode}",
            file=sys.stderr,
        )
        return error.returncode


if __name__ == "__main__":
    raise SystemExit(main())
