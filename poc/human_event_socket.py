#!/usr/bin/env python3
"""PoC: publish tmux Human Ctrl+C events over a Unix datagram socket."""

import argparse
import datetime
import json
import os
import pathlib
import shlex
import socket
import subprocess
import sys
import threading
import time


DEFAULT_TMUX_SOCKET = "human-event-socket-poc"
DEFAULT_SESSION = "human-event-socket-poc"
DEFAULT_EVENT_SOCKET = pathlib.Path("/tmp/shared-terminal-human-event.sock")


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


def install_binding(
    tmux_socket: str,
    event_socket: pathlib.Path,
    session_name: str,
) -> None:
    script = pathlib.Path(__file__).resolve()
    emit_command = " ".join(
        [
            shlex.quote(sys.executable),
            shlex.quote(str(script)),
            "emit",
            "--socket-path",
            shlex.quote(str(event_socket)),
            "--pane",
            shlex.quote("#{pane_id}"),
            "--client",
            shlex.quote("#{client_name}"),
            "--session",
            shlex.quote(session_name),
        ]
    )

    # C-c reaches the pane first. Event delivery runs asynchronously and is
    # deliberately fail-open.
    tmux(
        tmux_socket,
        "bind-key",
        "-T",
        "root",
        "C-c",
        "send-keys",
        "C-c",
        r"\;",
        "run-shell",
        "-b",
        emit_command,
    )


def timestamp() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="milliseconds")


def emit_event(args) -> int:
    event = {
        "type": "human_interrupt",
        "source": "tmux_client",
        "key": "C-c",
        "session": args.session,
        "pane": args.pane,
        "client": args.client,
        "timestamp": timestamp(),
    }
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode()

    producer = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        producer.sendto(payload, str(args.socket_path))
    except OSError:
        # The Human control path must keep working when the consumer is absent.
        return 0
    finally:
        producer.close()
    return 0


class EventReceiver:
    def __init__(self, socket_path: pathlib.Path, on_event=None):
        self.socket_path = socket_path
        self.on_event = on_event
        self.events = []
        self._sequence = 0
        self._stop = threading.Event()
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self._socket.settimeout(0.2)
        self._thread = threading.Thread(target=self._receive, daemon=True)

    def start(self) -> None:
        if self.socket_path.exists():
            self.socket_path.unlink()
        self._socket.bind(str(self.socket_path))
        os.chmod(self.socket_path, 0o600)
        self._thread.start()

    def _receive(self) -> None:
        while not self._stop.is_set():
            try:
                payload = self._socket.recv(65535)
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                event = json.loads(payload)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            self._sequence += 1
            event["seq"] = self._sequence
            self.events.append(event)
            if self.on_event is not None:
                self.on_event(event)

    def stop(self) -> None:
        time.sleep(0.3)
        self._stop.set()
        self._thread.join(timeout=1)
        self._socket.close()
        if self.socket_path.exists():
            self.socket_path.unlink()


def show_events(events) -> None:
    print()
    print(f"Received events: {len(events)}")
    for event in events:
        print(json.dumps(event, ensure_ascii=False, sort_keys=True))


def run_listener_test(args, *, attach: bool, inject_agent: bool) -> int:
    receiver = EventReceiver(args.socket_path)
    receiver.start()
    try:
        ensure_session(args.tmux_socket, args.session)
        install_binding(args.tmux_socket, args.socket_path, args.session)

        if inject_agent:
            tmux(
                args.tmux_socket,
                "send-keys",
                "-t",
                args.session,
                "C-c",
            )
            time.sleep(0.5)
        elif attach:
            print("Human Event Unix Socket PoC")
            print(f"tmux socket: {args.tmux_socket}")
            print(f"session: {args.session}")
            print(f"event socket: {args.socket_path} (mode 0600)")
            print()
            print("Inside tmux, run:  ping 1.1.1.1")
            print("Physically press Ctrl+C, then detach with Ctrl+B, D.")
            print()
            tmux(
                args.tmux_socket,
                "attach-session",
                "-t",
                args.session,
            )
    finally:
        receiver.stop()

    show_events(receiver.events)
    if inject_agent:
        if receiver.events:
            print("FAIL: agent send-keys was misclassified as Human input.")
            return 1
        print("PASS: agent send-keys produced no Human event.")
    return 0


def run_fail_open_test(args) -> int:
    if args.socket_path.exists():
        args.socket_path.unlink()
    ensure_session(args.tmux_socket, args.session)
    install_binding(args.tmux_socket, args.socket_path, args.session)
    print("Fail-open test: no event listener is running.")
    print("Inside tmux, run ping and physically press Ctrl+C.")
    print("The ping must still stop immediately. Then detach with Ctrl+B, D.")
    tmux(args.tmux_socket, "attach-session", "-t", args.session)
    print("PASS if Ctrl+C stopped the foreground process normally.")
    return 0


def add_shared_arguments(parser) -> None:
    parser.add_argument("--tmux-socket", default=DEFAULT_TMUX_SOCKET)
    parser.add_argument("--session", default=DEFAULT_SESSION)
    parser.add_argument(
        "--socket-path",
        type=pathlib.Path,
        default=DEFAULT_EVENT_SOCKET,
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Test tmux Human events over a local Unix socket."
    )
    add_shared_arguments(parser)
    subparsers = parser.add_subparsers(dest="command")

    emit_parser = subparsers.add_parser("emit", help=argparse.SUPPRESS)
    emit_parser.add_argument("--socket-path", type=pathlib.Path, required=True)
    emit_parser.add_argument("--pane", required=True)
    emit_parser.add_argument("--client", default="")
    emit_parser.add_argument("--session", required=True)

    subparsers.add_parser(
        "agent-test",
        help="verify tmux send-keys does not emit a Human event",
    )
    subparsers.add_parser(
        "fail-open",
        help="verify Ctrl+C works when no event listener exists",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "emit":
            return emit_event(args)
        if args.command == "agent-test":
            return run_listener_test(args, attach=False, inject_agent=True)
        if args.command == "fail-open":
            return run_fail_open_test(args)
        return run_listener_test(args, attach=True, inject_agent=False)
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
