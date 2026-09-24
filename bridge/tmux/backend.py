"""tmux-specific backend used by the local Bridge."""

import os
import pathlib
import shlex
import subprocess
import sys
import tempfile
import uuid

try:
    from bridge.common import BridgeError, now
except ModuleNotFoundError:  # Direct execution support
    from common import BridgeError, now

try:
    from bridge.config import MANAGED_HISTORY_LIMIT
except ModuleNotFoundError:  # Direct execution support
    from config import MANAGED_HISTORY_LIMIT

class TmuxBackend:
    LIST_FORMAT = "\t".join(
        [
            "#{session_name}",
            "#{window_id}",
            "#{pane_id}",
            "#{pane_index}",
            "#{pane_active}",
        ]
    )
    STATE_FORMAT = "\t".join(
        [
            "#{session_name}",
            "#{window_id}",
            "#{pane_id}",
            "#{pane_index}",
            "#{pane_active}",
            "#{pane_current_command}",
            "#{pane_current_path}",
            "#{pane_pid}",
            "#{pane_tty}",
            "#{pane_dead}",
        ]
    )
    CLIENT_FORMAT = "#{client_name}\t#{client_session}\t#{pane_id}"
    MANAGED_SESSION_FORMAT = "\t".join(
        [
            "#{session_name}",
            "#{session_id}",
            "#{session_windows}",
            "#{session_attached}",
            "#{@shared_terminal_managed}",
            "#{@shared_terminal_id}",
            "#{@shared_terminal_created_at}",
            "#{history_limit}",
            "#{mouse}",
        ]
    )

    def __init__(self, socket_name: str):
        self.socket_name = socket_name

    def run(self, *arguments: str, check: bool = True):
        try:
            return subprocess.run(
                ["tmux", "-L", self.socket_name, *arguments],
                check=check,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as error:
            raise BridgeError("TMUX_UNAVAILABLE") from error
        except subprocess.CalledProcessError as error:
            raise BridgeError(
                "TMUX_COMMAND_FAILED",
                stderr=(error.stderr or "").strip(),
            ) from error

    def list_panes(self):
        result = self.run("list-panes", "-a", "-F", self.LIST_FORMAT)
        panes = []
        for line in result.stdout.splitlines():
            session, window, pane, index, active = line.split("\t")
            panes.append(
                {
                    "server": self.socket_name,
                    "session": session,
                    "window": window,
                    "pane": pane,
                    "pane_index": int(index),
                    "active": active == "1",
                }
            )
        return panes

    def read(self, pane: str, lines: int):
        return self.run(
            "capture-pane",
            "-p",
            "-t",
            pane,
            "-S",
            f"-{lines}",
        ).stdout

    def state(self, pane: str):
        result = self.run(
            "display-message",
            "-p",
            "-t",
            pane,
            self.STATE_FORMAT,
        )
        fields = result.stdout.rstrip("\n").split("\t")
        if len(fields) != 10 or not fields[2]:
            raise BridgeError("PANE_NOT_FOUND", pane=pane)
        (
            session,
            window,
            pane_id,
            index,
            active,
            command,
            cwd,
            pid,
            tty,
            dead,
        ) = fields
        return {
            "server": self.socket_name,
            "session": session,
            "window": window,
            "pane": pane_id,
            "pane_index": int(index),
            "active": active == "1",
            "current_command": command,
            "cwd": cwd,
            "pid": int(pid),
            "tty": tty,
            "dead": dead == "1",
        }

    def active_pane(self, client_name: str):
        result = self.run("list-clients", "-F", self.CLIENT_FORMAT, check=False)
        for line in result.stdout.splitlines():
            fields = line.split("\t")
            if len(fields) == 3 and fields[0] == client_name and fields[2]:
                return {
                    "client": fields[0],
                    "session": fields[1],
                    "pane": fields[2],
                }
        raise BridgeError("CLIENT_NOT_FOUND", client=client_name)

    def send_text(self, pane: str, text: str):
        self.run("send-keys", "-t", pane, "-l", text)

    def send_key(self, pane: str, key: str):
        self.run("send-keys", "-t", pane, key)

    def submit(self, pane: str, text: str):
        """Queue literal text and Enter in one ordered tmux invocation."""
        self.run(
            "send-keys", "-t", pane, "-l", text,
            ";", "send-keys", "-t", pane, "Enter",
        )

    def list_managed_sessions(self):
        result = self.run(
            "list-sessions",
            "-F",
            self.MANAGED_SESSION_FORMAT,
            check=False,
        )
        sessions = []
        for line in result.stdout.splitlines():
            fields = line.split("\t")
            if len(fields) != 9 or fields[4] != "1":
                continue
            (
                name,
                session_id,
                windows,
                attached,
                _,
                managed_id,
                created,
                history_limit,
                mouse,
            ) = fields
            pane = self.run(
                "display-message",
                "-p",
                "-t",
                name,
                "#{pane_id}",
            ).stdout.strip()
            sessions.append(
                {
                    "name": name,
                    "session_id": session_id,
                    "pane": pane,
                    "windows": int(windows),
                    "attached": int(attached),
                    "managed_id": managed_id,
                    "created_at": created,
                    "history_limit": int(history_limit),
                    "mouse": mouse == "1",
                }
            )
        return sessions

    def create_managed_session(self, name: str, cwd: str):
        exists = self.run("has-session", "-t", name, check=False)
        if exists.returncode == 0:
            raise BridgeError("SESSION_ALREADY_EXISTS", session=name)
        # A fresh named tmux socket has no server yet. new-session is the
        # operation that starts it; global options cannot be set beforehand.
        self.run("new-session", "-d", "-s", name, "-c", cwd)
        self.run(
            "set-option",
            "-g",
            "history-limit",
            str(MANAGED_HISTORY_LIMIT),
        )
        managed_id = str(uuid.uuid4())
        created_at = now()
        self.run("set-option", "-t", name, "@shared_terminal_managed", "1")
        self.run("set-option", "-t", name, "@shared_terminal_id", managed_id)
        self.run(
            "set-option",
            "-t",
            name,
            "@shared_terminal_created_at",
            created_at,
        )
        self.run("set-option", "-t", name, "mouse", "on")
        self.run(
            "set-window-option",
            "-t",
            name,
            "history-limit",
            str(MANAGED_HISTORY_LIMIT),
        )
        self.run(
            "set-option",
            "-t",
            name,
            "@shared_terminal_history_limit",
            str(MANAGED_HISTORY_LIMIT),
        )
        self.run(
            "set-option",
            "-t",
            name,
            "@shared_terminal_mouse",
            "on",
        )
        pane = self.run(
            "display-message",
            "-p",
            "-t",
            name,
            "#{pane_id}",
        ).stdout.strip()
        actual_history_limit = int(
            self.run(
                "display-message",
                "-p",
                "-t",
                pane,
                "#{history_limit}",
            ).stdout.strip()
        )
        return {
            "name": name,
            "pane": pane,
            "managed_id": managed_id,
            "created_at": created_at,
            "cwd": cwd,
            "history_limit": actual_history_limit,
            "mouse": True,
        }

    def stop_managed_session(self, name: str):
        managed = self.run(
            "show-options",
            "-qv",
            "-t",
            name,
            "@shared_terminal_managed",
            check=False,
        )
        if managed.returncode != 0 or managed.stdout.strip() != "1":
            raise BridgeError("SESSION_NOT_MANAGED", session=name)
        self.run("kill-session", "-t", name)

    def install_human_binding(
        self,
        event_socket: pathlib.Path,
        script_path: pathlib.Path,
    ):
        emit_command = " ".join(
            [
                shlex.quote(sys.executable),
                shlex.quote(str(script_path)),
                "emit-event",
                "--socket-path",
                shlex.quote(str(event_socket)),
                "--pane",
                shlex.quote("#{pane_id}"),
                "--client",
                shlex.quote("#{client_name}"),
                "--session",
                shlex.quote("#{session_name}"),
            ]
        )
        self.run(
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

    def ensure_server_identity(self):
        variable = "SHARED_TERMINAL_BRIDGE_SERVER_ID"
        result = self.run(
            "show-environment",
            "-g",
            variable,
            check=False,
        )
        if result.returncode == 0 and "=" in result.stdout:
            return result.stdout.strip().split("=", 1)[1]
        identity = str(uuid.uuid4())
        self.run("set-environment", "-g", variable, identity)
        return identity

    def get_root_ctrl_c_binding(self):
        result = self.run(
            "list-keys",
            "-T",
            "root",
            "C-c",
            check=False,
        )
        if result.returncode != 0:
            return None
        binding = result.stdout.strip()
        return binding or None

    def restore_root_ctrl_c_binding(self, binding):
        if binding is None:
            self.run("unbind-key", "-T", "root", "C-c", check=False)
            return

        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix="shared-terminal-binding-",
                suffix=".conf",
                delete=False,
            ) as temporary:
                temporary.write(binding + "\n")
                temporary_path = pathlib.Path(temporary.name)
            os.chmod(temporary_path, 0o600)
            self.run("source-file", str(temporary_path))
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
