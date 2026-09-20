#!/usr/bin/env python3
"""PoC: resolve active pane from an explicit tmux client."""

import json
import pathlib
import subprocess
import time


TMUX_SOCKET = "active-pane-poc"
SESSION_A = "active-pane-a"
SESSION_B = "active-pane-b"


def tmux(*arguments: str, capture: bool = False, check: bool = True):
    options = {
        "check": check,
        "capture_output": capture,
        "text": True,
    }
    if not check and not capture:
        options["stderr"] = subprocess.DEVNULL
    return subprocess.run(
        ["tmux", "-L", TMUX_SOCKET, *arguments],
        **options,
    )


def create_session(name: str) -> str:
    tmux(
        "new-session",
        "-d",
        "-s",
        name,
        "-c",
        str(pathlib.Path.cwd()),
    )
    return tmux(
        "display-message",
        "-p",
        "-t",
        name,
        "#{pane_id}",
        capture=True,
    ).stdout.strip()


def start_control_client(session: str):
    return subprocess.Popen(
        [
            "tmux",
            "-L",
            TMUX_SOCKET,
            "-C",
            "attach-session",
            "-t",
            session,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def wait_for_clients(expected: int):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = tmux(
            "list-clients",
            "-F",
            "#{client_name}\t#{client_session}\t#{pane_id}",
            capture=True,
            check=False,
        )
        lines = [line for line in result.stdout.splitlines() if line]
        if len(lines) == expected:
            return [line.split("\t") for line in lines]
        time.sleep(0.1)
    raise RuntimeError(f"Expected {expected} tmux clients")


class ClientPaneResolver:
    def __init__(self, allowed_panes):
        self.allowed_panes = set(allowed_panes)
        self.audit = []

    def get_active_pane(self, client_name: str):
        result = tmux(
            "list-clients",
            "-F",
            "#{client_name}\t#{client_session}\t#{pane_id}",
            capture=True,
            check=False,
        )
        match = None
        for line in result.stdout.splitlines():
            fields = line.split("\t")
            if len(fields) == 3 and fields[0] == client_name:
                match = fields
                break

        if match is None or not match[2]:
            self.audit.append(
                f"ACTIVE_DENY client={client_name} reason=CLIENT_NOT_FOUND"
            )
            return {
                "error": {
                    "code": "CLIENT_NOT_FOUND",
                    "client": client_name,
                }
            }

        client, session, pane = match
        response = {
            "client": client,
            "session": session,
            "pane": pane,
            "authorized": pane in self.allowed_panes,
        }
        self.audit.append(
            f"ACTIVE     client={client} pane={pane} "
            f"authorized={str(response['authorized']).lower()}"
        )
        return response


def main() -> int:
    tmux("kill-server", check=False)
    pane_a = create_session(SESSION_A)
    pane_b = create_session(SESSION_B)
    clients = []

    try:
        clients.append(start_control_client(SESSION_A))
        clients.append(start_control_client(SESSION_B))
        client_rows = wait_for_clients(2)

        by_session = {
            session: {"client": client, "pane": pane}
            for client, session, pane in client_rows
        }
        client_a = by_session[SESSION_A]["client"]
        client_b = by_session[SESSION_B]["client"]

        resolver = ClientPaneResolver({pane_a})
        result_a = resolver.get_active_pane(client_a)
        result_b = resolver.get_active_pane(client_b)
        missing = resolver.get_active_pane("missing-client")

        passed = (
            result_a.get("pane") == pane_a
            and result_a.get("authorized") is True
            and result_b.get("pane") == pane_b
            and result_b.get("authorized") is False
            and result_a.get("pane") != result_b.get("pane")
            and missing.get("error", {}).get("code") == "CLIENT_NOT_FOUND"
        )

        print("tmux clients:")
        print(
            json.dumps(
                [
                    {
                        "client": client,
                        "session": session,
                        "active_pane": pane,
                    }
                    for client, session, pane in client_rows
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        print()
        print("get_active_pane(client A):")
        print(json.dumps(result_a, ensure_ascii=False, indent=2))
        print()
        print("get_active_pane(client B):")
        print(json.dumps(result_b, ensure_ascii=False, indent=2))
        print()
        print("get_active_pane(unknown client):")
        print(json.dumps(missing, ensure_ascii=False, indent=2))
        print()
        print("Audit:")
        for entry in resolver.audit:
            print(entry)
        print()

        if passed:
            print("PASS: each client resolved to its own active pane.")
            print("PASS: pane authorization remained independent of resolution.")
            print("PASS: unknown client was rejected without fallback.")
            return 0

        print("FAIL: per-client active pane validation failed.")
        return 1
    finally:
        for process in clients:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        tmux("kill-server", check=False)


if __name__ == "__main__":
    raise SystemExit(main())
