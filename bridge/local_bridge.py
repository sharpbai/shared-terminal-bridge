#!/usr/bin/env python3
"""Local JSON bridge for pane-scoped tmux observation and control."""

import argparse
import datetime
import fcntl
import json
import os
import pathlib
import re
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import uuid


MAX_LINES = 5000
MANAGED_HISTORY_LIMIT = 100000
DEFAULT_CONTROL_SOCKET = pathlib.Path("/tmp/shared-terminal-bridge.sock")
DEFAULT_EVENT_SOCKET = pathlib.Path("/tmp/shared-terminal-events.sock")
DEFAULT_STATE_FILE = pathlib.Path("/tmp/shared-terminal-bridge-state.json")


class BridgeError(Exception):
    def __init__(self, code: str, **details):
        super().__init__(code)
        self.code = code
        self.details = details

    def response(self):
        return {"ok": False, "error": {"code": self.code, **self.details}}


def now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="milliseconds")


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
        self.run("new-session", "-d", "-s", name, "-c", cwd)
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
            "set-hook",
            "-t",
            name,
            "after-new-window",
            "set-window-option history-limit " + str(MANAGED_HISTORY_LIMIT),
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
        return {
            "name": name,
            "pane": pane,
            "managed_id": managed_id,
            "created_at": created_at,
            "cwd": cwd,
            "history_limit": MANAGED_HISTORY_LIMIT,
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


class LocalBridge:
    def __init__(
        self,
        tmux_socket: str,
        control_socket: pathlib.Path,
        event_socket: pathlib.Path,
        allowed_panes,
        state_file: pathlib.Path,
        allow_session_management: bool = False,
    ):
        self.tmux = TmuxBackend(tmux_socket)
        self.control_socket = control_socket
        self.event_socket = event_socket
        self.allowed_panes = set(allowed_panes)
        self.allow_session_management = allow_session_management
        self.managed_sessions = {}
        self.state_file = state_file
        self.instance_lock_path = pathlib.Path(f"{state_file}.lock")
        self.instance_lock_file = None
        self.acquire_instance_lock()
        self.tmux_server_id = self.tmux.ensure_server_identity()
        self.leases = {}
        self.generations = {}
        self.event_sequence = 0
        self.original_human_binding = None
        self.binding_snapshot_taken = False
        self.human_binding_installed = False
        self.audit = []
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.control_listener = None
        self.event_listener = None
        self.load_state()

    def acquire_instance_lock(self):
        self.instance_lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self.instance_lock_path.open("a+", encoding="utf-8")
        os.chmod(self.instance_lock_path, 0o600)
        try:
            fcntl.flock(
                lock_file.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError as error:
            lock_file.close()
            raise BridgeError(
                "INSTANCE_ALREADY_RUNNING",
                state_file=str(self.state_file),
            ) from error
        self.instance_lock_file = lock_file

    def release_instance_lock(self):
        if self.instance_lock_file is not None:
            fcntl.flock(self.instance_lock_file.fileno(), fcntl.LOCK_UN)
            self.instance_lock_file.close()
            self.instance_lock_file = None

    def persistent_state(self):
        return {
            "schema_version": 1,
            "tmux_socket": self.tmux.socket_name,
            "tmux_server_id": self.tmux_server_id,
            "generations": self.generations,
            "leases": self.leases,
            "managed_sessions": self.managed_sessions,
            "binding": {
                "snapshot_taken": self.binding_snapshot_taken,
                "installed": self.human_binding_installed,
                "original": self.original_human_binding,
            },
        }

    def persist_state(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.state_file.parent,
                prefix=f".{self.state_file.name}.",
                delete=False,
            ) as temporary:
                json.dump(
                    self.persistent_state(),
                    temporary,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = pathlib.Path(temporary.name)
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, self.state_file)
            os.chmod(self.state_file, 0o600)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def load_state(self):
        if not self.state_file.exists():
            return
        state = json.loads(self.state_file.read_text(encoding="utf-8"))
        if state.get("schema_version") != 1:
            raise BridgeError("STATE_SCHEMA_UNSUPPORTED")
        if state.get("tmux_socket") != self.tmux.socket_name:
            raise BridgeError(
                "STATE_TMUX_SOCKET_MISMATCH",
                expected=self.tmux.socket_name,
                actual=state.get("tmux_socket"),
            )
        if state.get("tmux_server_id") != self.tmux_server_id:
            raise BridgeError(
                "STATE_TMUX_SERVER_MISMATCH",
                expected=self.tmux_server_id,
                actual=state.get("tmux_server_id"),
            )
        self.generations = {
            pane: int(generation)
            for pane, generation in state.get("generations", {}).items()
        }
        self.leases = state.get("leases", {})
        self.managed_sessions = state.get("managed_sessions", {})
        if self.allow_session_management:
            live_managed = {
                session["managed_id"]: session
                for session in self.tmux.list_managed_sessions()
            }
            self.managed_sessions = {
                managed_id: session
                for managed_id, session in self.managed_sessions.items()
                if managed_id in live_managed
            }
            for session in self.managed_sessions.values():
                self.allowed_panes.add(session["pane"])
        binding = state.get("binding", {})
        self.binding_snapshot_taken = bool(
            binding.get("snapshot_taken", False)
        )
        self.human_binding_installed = bool(
            binding.get("installed", False)
        )
        self.original_human_binding = binding.get("original")

        recovered = False
        for lease in self.leases.values():
            if lease.get("state") == "ACTIVE":
                lease["state"] = "REVOKED"
                lease["revoked_at"] = now()
                lease["revoke_reason"] = "daemon_restart"
                recovered = True
        if recovered:
            self.persist_state()

    def record(self, action: str, **fields):
        entry = {
            "timestamp": now(),
            "action": action,
            **fields,
        }
        with self.lock:
            self.audit.append(entry)

    def authorize(self, pane: str):
        if pane not in self.allowed_panes:
            self.record("ACCESS_DENY", pane=pane)
            raise BridgeError("PANE_ACCESS_DENIED", pane=pane)

    def require_lease(self, pane: str, generation: int):
        self.authorize(pane)
        with self.lock:
            lease = self.leases.get(pane)
            if (
                lease is None
                or lease["state"] != "ACTIVE"
                or lease["generation"] != generation
            ):
                self.record(
                    "ACTION_DENY",
                    pane=pane,
                    generation=generation,
                    lease=lease,
                )
                raise BridgeError(
                    "EXECUTION_LEASE_INVALID",
                    pane=pane,
                    generation=generation,
                    lease=lease,
                )
            return dict(lease)

    def dispatch(self, method: str, params):
        handlers = {
            "terminal_list": self.terminal_list,
            "get_active_pane": self.get_active_pane,
            "terminal_read": self.terminal_read,
            "terminal_state": self.terminal_state,
            "install_human_binding": self.install_human_binding,
            "restore_human_binding": self.restore_human_binding,
            "human_binding_status": self.human_binding_status,
            "acquire_execution": self.acquire_execution,
            "release_execution": self.release_execution,
            "execution_status": self.execution_status,
            "terminal_type": self.terminal_type,
            "terminal_key": self.terminal_key,
            "terminal_interrupt": self.terminal_interrupt,
            "audit_log": self.audit_log,
            "terminal_session_list": self.terminal_session_list,
            "terminal_session_create": self.terminal_session_create,
            "terminal_session_stop": self.terminal_session_stop,
        }
        handler = handlers.get(method)
        if handler is None:
            raise BridgeError("METHOD_NOT_FOUND", method=method)
        return handler(**params)

    def terminal_list(self):
        panes = []
        for pane in self.tmux.list_panes():
            panes.append(
                {
                    **pane,
                    "authorized": pane["pane"] in self.allowed_panes,
                }
            )
        self.record("LIST", panes=len(panes))
        return {"panes": panes}

    def require_session_management(self):
        if not self.allow_session_management:
            raise BridgeError("SESSION_MANAGEMENT_DISABLED")

    def terminal_session_list(self):
        self.require_session_management()
        sessions = self.tmux.list_managed_sessions()
        self.record("SESSION_LIST", sessions=len(sessions))
        return {"sessions": sessions}

    def terminal_session_create(self, name: str, cwd: str):
        self.require_session_management()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name):
            raise BridgeError("INVALID_SESSION_NAME", session=name)
        cwd_path = pathlib.Path(cwd).expanduser()
        if not cwd_path.is_absolute() or not cwd_path.is_dir():
            raise BridgeError("INVALID_SESSION_CWD", cwd=cwd)
        session = self.tmux.create_managed_session(name, str(cwd_path))
        with self.lock:
            self.allowed_panes.add(session["pane"])
            self.managed_sessions[session["managed_id"]] = session
            self.persist_state()
        self.record(
            "SESSION_CREATE",
            session=name,
            pane=session["pane"],
            managed_id=session["managed_id"],
        )
        return session

    def terminal_session_stop(self, name: str):
        self.require_session_management()
        session = next(
            (
                item
                for item in self.tmux.list_managed_sessions()
                if item["name"] == name
            ),
            None,
        )
        if session is None:
            raise BridgeError("SESSION_NOT_MANAGED", session=name)
        pane = session["pane"]
        self.tmux.stop_managed_session(name)
        with self.lock:
            self.allowed_panes.discard(pane)
            lease = self.leases.get(pane)
            if lease and lease.get("state") == "ACTIVE":
                lease["state"] = "REVOKED"
                lease["revoked_at"] = now()
                lease["revoke_reason"] = "session_stopped"
            self.managed_sessions.pop(session["managed_id"], None)
            self.persist_state()
        self.record("SESSION_STOP", session=name, pane=pane)
        return {"stopped": True, "name": name, "pane": pane}

    def get_active_pane(self, client: str):
        result = self.tmux.active_pane(client)
        result["authorized"] = result["pane"] in self.allowed_panes
        self.record(
            "ACTIVE",
            client=client,
            pane=result["pane"],
            authorized=result["authorized"],
        )
        return result

    def terminal_read(self, pane: str, lines: int = 100):
        if not 1 <= lines <= MAX_LINES:
            raise BridgeError("INVALID_LINE_LIMIT", lines=lines)
        self.authorize(pane)
        content = self.tmux.read(pane, lines)
        self.record("READ", pane=pane, lines=lines)
        return {
            "pane": pane,
            "lines_requested": lines,
            "content": content,
            "truncated": False,
        }

    def terminal_state(self, pane: str):
        self.authorize(pane)
        state = self.tmux.state(pane)
        self.record("STATE", pane=pane)
        return state

    def install_human_binding(self):
        with self.lock:
            if self.human_binding_installed:
                return {
                    "installed": True,
                    "already_installed": True,
                    "original_binding_present": (
                        self.original_human_binding is not None
                    ),
                }
            self.original_human_binding = (
                self.tmux.get_root_ctrl_c_binding()
            )
            self.binding_snapshot_taken = True
        self.tmux.install_human_binding(
            self.event_socket,
            pathlib.Path(__file__).resolve(),
        )
        with self.lock:
            self.human_binding_installed = True
            self.persist_state()
        self.record("BINDING_INSTALL")
        return {
            "installed": True,
            "already_installed": False,
            "original_binding_present": (
                self.original_human_binding is not None
            ),
        }

    def restore_human_binding(self):
        with self.lock:
            if not self.binding_snapshot_taken:
                raise BridgeError("BINDING_SNAPSHOT_NOT_FOUND")
            original = self.original_human_binding
        self.tmux.restore_root_ctrl_c_binding(original)
        with self.lock:
            self.original_human_binding = None
            self.binding_snapshot_taken = False
            self.human_binding_installed = False
            self.persist_state()
        self.record(
            "BINDING_RESTORE",
            restored_original=original is not None,
        )
        return {
            "restored": True,
            "restored_original": original is not None,
        }

    def human_binding_status(self):
        with self.lock:
            return {
                "installed": self.human_binding_installed,
                "snapshot_available": self.binding_snapshot_taken,
                "original_binding_present": (
                    self.original_human_binding is not None
                ),
            }

    def acquire_execution(self, pane: str):
        self.authorize(pane)
        with self.lock:
            generation = self.generations.get(pane, 0) + 1
            self.generations[pane] = generation
            lease = {
                "pane": pane,
                "generation": generation,
                "state": "ACTIVE",
                "issued_at": now(),
            }
            self.leases[pane] = lease
            self.persist_state()
        self.record("LEASE_ACQUIRE", pane=pane, generation=generation)
        return dict(lease)

    def release_execution(self, pane: str, generation: int):
        self.require_lease(pane, generation)
        with self.lock:
            self.leases[pane]["state"] = "RELEASED"
            lease = dict(self.leases[pane])
            self.persist_state()
        self.record("LEASE_RELEASE", pane=pane, generation=generation)
        return lease

    def execution_status(self, pane: str):
        self.authorize(pane)
        with self.lock:
            lease = self.leases.get(pane)
            return {"lease": dict(lease) if lease else None}

    def terminal_type(self, pane: str, generation: int, text: str):
        self.require_lease(pane, generation)
        self.tmux.send_text(pane, text)
        self.record(
            "TYPE",
            pane=pane,
            generation=generation,
            bytes=len(text.encode()),
        )
        return {"accepted": True, "bytes": len(text.encode())}

    def terminal_key(self, pane: str, generation: int, key: str):
        self.require_lease(pane, generation)
        self.tmux.send_key(pane, key)
        self.record("KEY", pane=pane, generation=generation, key=key)
        return {"accepted": True, "key": key}

    def terminal_interrupt(self, pane: str, generation: int):
        self.require_lease(pane, generation)
        self.tmux.send_key(pane, "C-c")
        self.record("AGENT_INTERRUPT", pane=pane, generation=generation)
        return {"accepted": True, "source": "agent"}

    def audit_log(self):
        with self.lock:
            return {"entries": list(self.audit)}

    def handle_human_event(self, event):
        pane = event.get("pane")
        if event.get("type") != "human_interrupt" or not pane:
            return
        with self.lock:
            self.event_sequence += 1
            event["seq"] = self.event_sequence
            lease = self.leases.get(pane)
            if lease and lease["state"] == "ACTIVE":
                lease["state"] = "REVOKED"
                lease["revoked_at"] = now()
                lease["event_seq"] = event["seq"]
                generation = lease["generation"]
                self.persist_state()
            else:
                generation = None
        self.record(
            "HUMAN_INTERRUPT",
            pane=pane,
            client=event.get("client", ""),
            event_seq=event["seq"],
        )
        if generation is not None:
            self.record(
                "LEASE_REVOKE",
                pane=pane,
                generation=generation,
                event_seq=event["seq"],
            )

    @staticmethod
    def prepare_socket(path: pathlib.Path):
        if path.exists():
            path.unlink()

    def event_loop(self):
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.event_listener = listener
        listener.settimeout(0.2)
        listener.bind(str(self.event_socket))
        os.chmod(self.event_socket, 0o600)
        while not self.stop_event.is_set():
            try:
                payload = listener.recv(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                event = json.loads(payload)
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.record("EVENT_REJECT", reason="INVALID_JSON")
                continue
            self.handle_human_event(event)

    def handle_connection(self, connection):
        with connection:
            reader = connection.makefile("r", encoding="utf-8")
            writer = connection.makefile("w", encoding="utf-8")
            line = reader.readline()
            try:
                request = json.loads(line)
                result = self.dispatch(
                    request.get("method", ""),
                    request.get("params") or {},
                )
                response = {"ok": True, "result": result}
            except BridgeError as error:
                response = error.response()
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                response = {
                    "ok": False,
                    "error": {
                        "code": "INVALID_REQUEST",
                        "message": str(error),
                    },
                }
            writer.write(json.dumps(response, ensure_ascii=False) + "\n")
            writer.flush()

    def serve(self):
        self.prepare_socket(self.control_socket)
        self.prepare_socket(self.event_socket)
        event_thread = threading.Thread(target=self.event_loop, daemon=True)
        event_thread.start()

        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.control_listener = listener
        listener.settimeout(0.2)
        listener.bind(str(self.control_socket))
        os.chmod(self.control_socket, 0o600)
        listener.listen()
        self.record(
            "SERVER_START",
            control_socket=str(self.control_socket),
            event_socket=str(self.event_socket),
        )

        while not self.stop_event.is_set():
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(
                target=self.handle_connection,
                args=(connection,),
                daemon=True,
            ).start()

        self.stop_event.set()
        listener.close()
        if self.event_listener:
            self.event_listener.close()
        event_thread.join(timeout=1)
        for path in (self.control_socket, self.event_socket):
            if path.exists():
                path.unlink()
        self.release_instance_lock()

    def stop(self):
        self.stop_event.set()
        if self.control_listener:
            self.control_listener.close()


def request(socket_path: pathlib.Path, method: str, params):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(str(socket_path))
    with client:
        writer = client.makefile("w", encoding="utf-8")
        reader = client.makefile("r", encoding="utf-8")
        writer.write(
            json.dumps({"method": method, "params": params}, ensure_ascii=False)
            + "\n"
        )
        writer.flush()
        return json.loads(reader.readline())


def emit_event(args):
    event = {
        "type": "human_interrupt",
        "source": "tmux_client",
        "key": "C-c",
        "pane": args.pane,
        "client": args.client,
        "session": args.session,
        "timestamp": now(),
    }
    producer = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        producer.sendto(
            json.dumps(event, separators=(",", ":")).encode(),
            str(args.socket_path),
        )
    except OSError:
        return 0
    finally:
        producer.close()
    return 0


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--tmux-socket", required=True)
    serve_parser.add_argument(
        "--control-socket",
        type=pathlib.Path,
        default=DEFAULT_CONTROL_SOCKET,
    )
    serve_parser.add_argument(
        "--event-socket",
        type=pathlib.Path,
        default=DEFAULT_EVENT_SOCKET,
    )
    serve_parser.add_argument("--allow-pane", action="append", default=[])
    serve_parser.add_argument(
        "--allow-session-management",
        action="store_true",
        help="allow creation and stopping of marked managed tmux sessions",
    )
    serve_parser.add_argument(
        "--state-file",
        type=pathlib.Path,
        default=DEFAULT_STATE_FILE,
    )

    call_parser = subparsers.add_parser("call")
    call_parser.add_argument("method")
    call_parser.add_argument("--params", default="{}")
    call_parser.add_argument(
        "--control-socket",
        type=pathlib.Path,
        default=DEFAULT_CONTROL_SOCKET,
    )

    emit_parser = subparsers.add_parser("emit-event")
    emit_parser.add_argument("--socket-path", type=pathlib.Path, required=True)
    emit_parser.add_argument("--pane", required=True)
    emit_parser.add_argument("--client", default="")
    emit_parser.add_argument("--session", default="")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.command == "emit-event":
        return emit_event(args)
    if args.command == "call":
        response = request(
            args.control_socket,
            args.method,
            json.loads(args.params),
        )
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return 0 if response.get("ok") else 1

    try:
        bridge = LocalBridge(
            tmux_socket=args.tmux_socket,
            control_socket=args.control_socket,
            event_socket=args.event_socket,
            allowed_panes=args.allow_pane,
            state_file=args.state_file,
            allow_session_management=args.allow_session_management,
        )
    except BridgeError as error:
        print(
            json.dumps(error.response(), ensure_ascii=False),
            file=sys.stderr,
        )
        return 1

    def stop_server(_signum, _frame):
        bridge.stop()

    signal.signal(signal.SIGTERM, stop_server)
    signal.signal(signal.SIGINT, stop_server)
    bridge.serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
