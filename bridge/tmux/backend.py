"""tmux-specific backend used by the local Bridge."""

import os
import pathlib
import shlex
import subprocess
import sys
import tempfile
import uuid
from bridge.tmux.pane_input import text_commands, key_commands

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
        if text:
            self._input_commands(text_commands(pane, text))

    def pager_at_end(self, pane, lines, raw='', command=''):
        from bridge.tmux.pager import at_pager_end
        tty = self.run('display-message', '-p', '-t', pane, '#{pane_tty}').stdout.strip()
        return at_pager_end(lines, tty, raw, command)

    def send_key(self, pane: str, key: str):
        commands = key_commands(pane, key)
        if commands[0][0] == 'send-keys' and self.run(
                'display-message', '-p', '-t', pane, '#{pane_in_mode}').stdout.strip() == '1':
            raise BridgeError('TERMINAL_KEY_UNSUPPORTED_IN_COPY_MODE', key=key)
        self._input_commands(commands)

    def _input_commands(self, commands):
        arguments = []
        for command in commands:
            if arguments:
                arguments.append(';')
            arguments.extend(command)
        self.run(*arguments)

    def submit(self, pane: str, text: str):
        """Queue literal text and Enter in one ordered tmux invocation."""
        self._input_commands(text_commands(pane, text + '\r'))

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
        # history-limit is captured when a pane is created on some tmux
        # versions. Run server bootstrap, the global option, and new-session
        # in one command queue so the initial pane and future windows agree.
        self.run(
            "start-server",
            ";",
            "set-option",
            "-g",
            "history-limit",
            str(MANAGED_HISTORY_LIMIT),
            ";",
            "new-session",
            "-d",
            "-s",
            name,
            "-c",
            cwd,
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
                "--tmux-socket", shlex.quote(self.socket_name),
                "--snapshot-buffer", shlex.quote("stb-interrupt-#{pane_id}"),
            ]
        )
        # Expand the pane-specific buffer name before parsing the command list.
        # The synchronous emitter consumes the snapshot before another key from
        # this client runs; C-c itself is delivered before launching Python.
        # tmux parses the quoted octal escape; keep binding text printable so
        # list-keys / restoration round-trips do not change a literal control.
        human_key = ('set-buffer -b stb-human-interrupt -- "\\003"'
                     ' ; paste-buffer -d -r -b stb-human-interrupt')
        fallback = (
            "capture-pane -S -30 -b stb-interrupt-#{pane_id} ; "
            + human_key + " ; run-shell " + shlex.quote(emit_command)
        )
        ordered = (
            'display-message -l -c "#{@stb_event_client}" '
            '"STB_INTERRUPT #{pane_id} #{client_name}" ; ' + human_key
        )
        commands = ('if-shell -F "#{@stb_event_client}" '
                    + shlex.quote(ordered) + ' ' + shlex.quote(fallback))
        self.run("bind-key", "-T", "root", "C-c", "run-shell", "-C", commands)
        for table in ('copy-mode', 'copy-mode-vi'):
            option = '@stb-original-' + table + '-ctrl-c'
            snapshot = self.run('show-options', '-gqv', option, check=False).stdout.strip()
            if not snapshot:
                original = self.run('list-keys', '-T', table, 'C-c', check=False).stdout.strip()
                self.run('set-option', '-g', option, original or 'UNBOUND')
            self.run('bind-key', '-T', table, 'C-c', 'run-shell', '-C', commands)

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
        for table in ('copy-mode', 'copy-mode-vi'):
            option = '@stb-original-' + table + '-ctrl-c'
            original = self.run('show-options', '-gqv', option, check=False).stdout.strip()
            if original:
                self._restore_ctrl_c_binding(None if original == 'UNBOUND' else original, table)
                self.run('set-option', '-gu', option)
        self._restore_ctrl_c_binding(binding, 'root')

    def _restore_ctrl_c_binding(self, binding, table):
        if binding is None:
            self.run("unbind-key", "-T", table, "C-c", check=False)
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
