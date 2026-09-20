#!/usr/bin/env python3
"""Local JSON bridge for pane-scoped tmux observation and control."""

import argparse
import datetime
import fcntl
import hashlib
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
import time
import uuid

try:
    from bridge.context_policy import AIContextPolicy
except ModuleNotFoundError:  # Direct execution: ./bridge/local_bridge.py
    from context_policy import AIContextPolicy


MAX_LINES = 5000
CONTEXT_CAPTURE_LINES = 5000
JOB_CAPTURE_LINES = 1000
MAX_RETAINED_JOBS = 128
MANAGED_HISTORY_LIMIT = 100000
DEFAULT_CONTROL_SOCKET = pathlib.Path("/tmp/shared-terminal-bridge.sock")
DEFAULT_EVENT_SOCKET = pathlib.Path("/tmp/shared-terminal-events.sock")
DEFAULT_STATE_FILE = pathlib.Path("/tmp/shared-terminal-bridge-state.json")
BRIDGE_API_VERSION = 6
BRIDGE_VERSION = "0.10.0"
DEFAULT_WAIT_MS = 10_000
DEFAULT_IDLE_BUDGET_MS = 30_000
DEFAULT_TOTAL_BUDGET_MS = 60_000
MAX_WAIT_MS = 30_000
MAX_TOTAL_BUDGET_MS = 600_000
LONG_RUN_APPROVAL_MS = 120_000
HIGH_RESOURCE_CLASSES = {"high_io", "full_scan"}
LONG_RUN_REQUEST_TTL_MS = 60 * 60 * 1000
MAX_JOB_WAIT_MS = 600_000
JOB_POLL_INTERVAL_SECONDS = 0.5
JOB_PROMPT_STABLE_MS = 1_500
JOB_TERMINAL_STATES = {
    "COMPLETED",
    "INTERRUPTED_BY_HUMAN",
    "NEEDS_ATTENTION",
    "HUMAN_DECISION_REQUIRED",
}


class BridgeError(Exception):
    def __init__(self, code: str, **details):
        super().__init__(code)
        self.code = code
        self.details = details

    def response(self):
        return {"ok": False, "error": {"code": self.code, **self.details}}


def now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="milliseconds")


def unix_ms() -> int:
    return time.time_ns() // 1_000_000


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
        self.run(
            "set-option",
            "-g",
            "history-limit",
            str(MANAGED_HISTORY_LIMIT),
        )
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
        self.observation_cursors = {}
        self.task_blocks = {}
        self.long_run_requests = {}
        self.long_run_approvals = {}
        self.jobs = {}
        self.wait_handles = {}
        self.cancelled_wait_ids = set()
        self.interrupt_sources = {}
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
            "long_run_requests": self.long_run_requests,
            "jobs": self.jobs,
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
        self.long_run_requests = state.get("long_run_requests", {})
        self.jobs = state.get("jobs", {})
        for job in self.jobs.values():
            # v0.9 inferred arbitrary percentages (for example df usage) as
            # progress. Progress is now unknown unless a command-specific
            # parser supplies evidence.
            job["progress"] = None
            job.setdefault("last_evidence_lines", [])
            job.setdefault("last_meaningful_activity_at", None)
            submitted_at_ms = int(job.get("submitted_at_ms", unix_ms()))
            expected_duration_ms = int(
                job.get("expected_duration_ms", DEFAULT_TOTAL_BUDGET_MS)
            )
            job["strategy_review_at_ms"] = submitted_at_ms + 10 * 60 * 1000
            job["hard_deadline_ms"] = self._job_hard_deadline_ms(
                submitted_at_ms, expected_duration_ms
            )
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
            "bridge_info": self.bridge_info,
            "terminal_list": self.terminal_list,
            "get_active_pane": self.get_active_pane,
            "terminal_read": self.terminal_read,
            "terminal_read_delta": self.terminal_read_delta,
            "terminal_wait_delta": self.terminal_wait_delta,
            "terminal_state": self.terminal_state,
            "install_human_binding": self.install_human_binding,
            "restore_human_binding": self.restore_human_binding,
            "human_binding_status": self.human_binding_status,
            "acquire_execution": self.acquire_execution,
            "release_execution": self.release_execution,
            "execution_status": self.execution_status,
            "terminal_type": self.terminal_type,
            "terminal_submit": self.terminal_submit,
            "terminal_long_run_request": self.terminal_long_run_request,
            "terminal_long_run_approve": self.terminal_long_run_approve,
            "terminal_long_run_requests": self.terminal_long_run_requests,
            "terminal_long_run_decide": self.terminal_long_run_decide,
            "terminal_job_list": self.terminal_job_list,
            "terminal_job_status": self.terminal_job_status,
            "terminal_wait_job": self.terminal_wait_job,
            "terminal_wait_list": self.terminal_wait_list,
            "terminal_cancel_wait": self.terminal_cancel_wait,
            "terminal_task_block": self.terminal_task_block,
            "terminal_task_observe": self.terminal_task_observe,
            "terminal_key": self.terminal_key,
            "terminal_interrupt": self.terminal_interrupt,
            "audit_log": self.audit_log,
            "terminal_session_list": self.terminal_session_list,
            "terminal_session_resolve": self.terminal_session_resolve,
            "terminal_session_read_delta": self.terminal_session_read_delta,
            "terminal_session_wait_delta": self.terminal_session_wait_delta,
            "terminal_session_state": self.terminal_session_state,
            "terminal_session_create": self.terminal_session_create,
            "terminal_session_stop": self.terminal_session_stop,
        }
        handler = handlers.get(method)
        if handler is None:
            raise BridgeError("METHOD_NOT_FOUND", method=method)
        return handler(**params)

    def bridge_info(self):
        """Advertise the live daemon's API, not merely the installed source."""
        methods = [
            "bridge_info",
            "terminal_list",
            "get_active_pane",
            "terminal_read",
            "terminal_read_delta",
            "terminal_wait_delta",
            "terminal_state",
            "install_human_binding",
            "restore_human_binding",
            "human_binding_status",
            "acquire_execution",
            "release_execution",
            "execution_status",
            "terminal_type",
            "terminal_submit",
            "terminal_long_run_request",
            "terminal_long_run_approve",
            "terminal_long_run_requests",
            "terminal_long_run_decide",
            "terminal_job_list",
            "terminal_job_status",
            "terminal_wait_job",
            "terminal_wait_list",
            "terminal_cancel_wait",
            "terminal_task_block",
            "terminal_task_observe",
            "terminal_key",
            "terminal_interrupt",
            "audit_log",
            "terminal_session_list",
            "terminal_session_resolve",
            "terminal_session_read_delta",
            "terminal_session_wait_delta",
            "terminal_session_state",
            "terminal_session_create",
            "terminal_session_stop",
        ]
        return {
            "name": "shared-terminal-bridge",
            "version": BRIDGE_VERSION,
            "api_version": BRIDGE_API_VERSION,
            "methods": methods,
        }

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

    def terminal_session_resolve(self, name: str):
        self.require_session_management()
        session = next(
            (item for item in self.tmux.list_managed_sessions() if item["name"] == name),
            None,
        )
        if session is None:
            raise BridgeError("SESSION_NOT_MANAGED", session=name)
        self.authorize(session["pane"])
        self.record("SESSION_RESOLVE", session=name, pane=session["pane"])
        return session

    def terminal_session_read_delta(self, name: str, **params):
        session = self.terminal_session_resolve(name)
        result = self.terminal_read_delta(session["pane"], **params)
        result["session"] = name
        return result

    def terminal_session_wait_delta(self, name: str, **params):
        session = self.terminal_session_resolve(name)
        result = self.terminal_wait_delta(session["pane"], **params)
        result["session"] = name
        return result

    def terminal_session_state(self, name: str):
        session = self.terminal_session_resolve(name)
        result = self.terminal_state(session["pane"])
        result["session"] = name
        return result

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
        with self.lock:
            lease = self.leases.get(pane)
            lease_snapshot = dict(lease) if lease else None
        self.record("READ", pane=pane, lines=lines)
        return {
            "pane": pane,
            "lines_requested": lines,
            "content": content,
            "truncated": False,
            "execution": {
                "lease": lease_snapshot,
                "human_override": bool(
                    lease_snapshot
                    and lease_snapshot.get("state") == "REVOKED"
                    and lease_snapshot.get("event_seq") is not None
                ),
                "interrupt_source": self._interrupt_source(pane, lease_snapshot),
            },
        }

    def terminal_read_delta(
        self,
        pane: str,
        cursor: str = None,
        max_bytes: int = AIContextPolicy.DEFAULT_MAX_BYTES,
        max_lines: int = AIContextPolicy.DEFAULT_MAX_LINES,
        command_echo: str = None,
    ):
        """Return only output added after an opaque Bridge-owned cursor."""
        self.authorize(pane)
        try:
            max_bytes = int(max_bytes)
            max_lines = int(max_lines)
            if not 1 <= max_bytes <= AIContextPolicy.MAX_BYTES:
                raise ValueError
            if not 1 <= max_lines <= AIContextPolicy.MAX_LINES:
                raise ValueError
        except (TypeError, ValueError) as error:
            raise BridgeError(
                "INVALID_CONTEXT_BUDGET",
                max_bytes=max_bytes,
                max_lines=max_lines,
            ) from error

        current = self.tmux.read(pane, CONTEXT_CAPTURE_LINES)
        clock = time.monotonic()
        with self.lock:
            previous = ""
            budget = {
                "started_monotonic": clock,
                "last_change_monotonic": clock,
                "consecutive_quiet": 0,
                "idle_budget_ms": DEFAULT_IDLE_BUDGET_MS,
                "total_budget_ms": DEFAULT_TOTAL_BUDGET_MS,
            }
            if cursor is not None:
                saved = self.observation_cursors.get(cursor)
                if saved is None or saved["pane"] != pane:
                    raise BridgeError("OBSERVATION_CURSOR_INVALID", pane=pane)
                previous = saved["content"]
                budget.update(
                    {
                        key: saved[key]
                        for key in budget
                        if key in saved
                    }
                )

        observation = AIContextPolicy.apply(
            previous,
            current,
            max_bytes=max_bytes,
            max_lines=max_lines,
            command_echo=command_echo,
        )
        if not observation["no_change"]:
            budget["last_change_monotonic"] = clock
            budget["consecutive_quiet"] = 0
        with self.lock:
            next_cursor = self._replace_observation_cursor(
                cursor, pane, current, budget
            )
            lease = self.leases.get(pane)
            lease_snapshot = dict(lease) if lease else None
        human_override = bool(
            lease_snapshot
            and lease_snapshot.get("state") == "REVOKED"
            and lease_snapshot.get("event_seq") is not None
        )
        self.record(
            "READ_DELTA",
            pane=pane,
            cursor=next_cursor,
            raw_delta_lines=observation["raw_delta_lines"],
            returned_lines=observation["returned_lines"],
        )
        return {
            "pane": pane,
            "cursor": next_cursor,
            **observation,
            "execution": {
                "lease": lease_snapshot,
                "human_override": human_override,
                "interrupt_source": self._interrupt_source(pane, lease_snapshot),
            },
        }

    def _replace_observation_cursor(self, old_cursor, pane, content, budget):
        next_cursor = uuid.uuid4().hex
        self.observation_cursors[next_cursor] = {
            "pane": pane,
            "content": content,
            "created_at": now(),
            **budget,
        }
        if old_cursor is not None:
            self.observation_cursors.pop(old_cursor, None)
        while len(self.observation_cursors) > 256:
            oldest = next(iter(self.observation_cursors))
            self.observation_cursors.pop(oldest, None)
        return next_cursor

    def _interrupt_source(self, pane, lease_snapshot=None):
        if (
            lease_snapshot
            and lease_snapshot.get("state") == "REVOKED"
            and lease_snapshot.get("event_seq") is not None
        ):
            return "human"
        event = getattr(self, "interrupt_sources", {}).get(pane)
        return event.get("source") if event else None

    def terminal_wait_delta(
        self,
        pane: str,
        cursor: str,
        wait_ms: int = DEFAULT_WAIT_MS,
        idle_budget_ms: int = DEFAULT_IDLE_BUDGET_MS,
        total_budget_ms: int = DEFAULT_TOTAL_BUDGET_MS,
        max_bytes: int = AIContextPolicy.DEFAULT_MAX_BYTES,
        max_lines: int = AIContextPolicy.DEFAULT_MAX_LINES,
        command_echo: str = None,
    ):
        """Wait locally for pane output without writing or inferring completion."""
        self.authorize(pane)
        try:
            wait_ms = int(wait_ms)
            idle_budget_ms = int(idle_budget_ms)
            total_budget_ms = int(total_budget_ms)
            max_bytes = int(max_bytes)
            max_lines = int(max_lines)
            if not 1 <= wait_ms <= MAX_WAIT_MS:
                raise ValueError
            if not 1 <= idle_budget_ms <= MAX_TOTAL_BUDGET_MS:
                raise ValueError
            if not 1 <= total_budget_ms <= MAX_TOTAL_BUDGET_MS:
                raise ValueError
            if idle_budget_ms > total_budget_ms:
                raise ValueError
            if not 1 <= max_bytes <= AIContextPolicy.MAX_BYTES:
                raise ValueError
            if not 1 <= max_lines <= AIContextPolicy.MAX_LINES:
                raise ValueError
        except (TypeError, ValueError) as error:
            raise BridgeError("INVALID_WAIT_BUDGET") from error

        with self.lock:
            saved = self.observation_cursors.get(cursor)
            if saved is None or saved["pane"] != pane:
                raise BridgeError("OBSERVATION_CURSOR_INVALID", pane=pane)
            previous = saved["content"]
            started = saved.get("started_monotonic", time.monotonic())
            last_change = saved.get("last_change_monotonic", started)
            consecutive_quiet = saved.get("consecutive_quiet", 0)

        wait_started = time.monotonic()
        deadline = wait_started + wait_ms / 1000
        current = previous
        changed = False
        human_override = False
        lease_snapshot = None
        while True:
            current = self.tmux.read(pane, CONTEXT_CAPTURE_LINES)
            changed = current != previous
            with self.lock:
                lease = self.leases.get(pane)
                lease_snapshot = dict(lease) if lease else None
            human_override = bool(
                lease_snapshot
                and lease_snapshot.get("state") == "REVOKED"
                and lease_snapshot.get("event_seq") is not None
            )
            if changed or human_override or time.monotonic() >= deadline:
                break
            time.sleep(0.25)

        clock = time.monotonic()
        observation = AIContextPolicy.apply(
            previous,
            current,
            max_bytes=max_bytes,
            max_lines=max_lines,
            command_echo=command_echo,
        )
        if changed:
            last_change = clock
            consecutive_quiet = 0
            state = "CHANGED"
        else:
            consecutive_quiet += 1
            state = "QUIET"
        total_elapsed_ms = int((clock - started) * 1000)
        idle_elapsed_ms = int((clock - last_change) * 1000)
        if human_override:
            state = "INTERRUPTED"
        elif (
            consecutive_quiet >= 2
            or idle_elapsed_ms >= idle_budget_ms
            or total_elapsed_ms >= total_budget_ms
        ):
            state = "BUDGET_EXHAUSTED"

        budget = {
            "started_monotonic": started,
            "last_change_monotonic": last_change,
            "consecutive_quiet": consecutive_quiet,
            "idle_budget_ms": idle_budget_ms,
            "total_budget_ms": total_budget_ms,
        }
        with self.lock:
            next_cursor = self._replace_observation_cursor(
                cursor, pane, current, budget
            )
        self.record(
            "WAIT_DELTA",
            pane=pane,
            state=state,
            waited_ms=int((clock - wait_started) * 1000),
            consecutive_quiet=consecutive_quiet,
        )
        return {
            "pane": pane,
            "cursor": next_cursor,
            "state": state,
            "waited_ms": int((clock - wait_started) * 1000),
            "budget": {
                "idle_budget_ms": idle_budget_ms,
                "total_budget_ms": total_budget_ms,
                "idle_elapsed_ms": idle_elapsed_ms,
                "total_elapsed_ms": total_elapsed_ms,
                "consecutive_quiet": consecutive_quiet,
            },
            **observation,
            "execution": {
                "lease": lease_snapshot,
                "human_override": human_override,
                "interrupt_source": self._interrupt_source(pane, lease_snapshot),
            },
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

    def acquire_execution(
        self,
        pane: str,
        thread_id: str = None,
        turn_id: str = None,
        turn_started_at_ms: int = None,
    ):
        self.authorize(pane)
        turn_values = (thread_id, turn_id, turn_started_at_ms)
        if any(value is not None for value in turn_values) and not all(
            value is not None for value in turn_values
        ):
            raise BridgeError("INCOMPLETE_TURN_IDENTITY")
        with self.lock:
            previous = self.leases.get(pane)
            if previous and previous.get("state") == "ACTIVE" and thread_id:
                previous_auth = previous.get("authorization") or {}
                if (
                    previous_auth.get("thread_id") != thread_id
                    or not previous_auth.get("turn_started_at_ms")
                    or turn_started_at_ms <= previous_auth["turn_started_at_ms"]
                ):
                    raise BridgeError(
                        "EXECUTION_LEASE_ALREADY_ACTIVE",
                        pane=pane,
                        generation=previous.get("generation"),
                    )
            if previous and previous.get("state") == "REVOKED" and thread_id:
                previous_auth = previous.get("authorization") or {}
                revoked_at_ms = previous.get("revoked_at_ms")
                if (
                    previous_auth.get("thread_id") == thread_id
                    and (
                        previous_auth.get("turn_id") == turn_id
                        or revoked_at_ms is None
                        or turn_started_at_ms <= revoked_at_ms
                    )
                ):
                    raise BridgeError(
                        "NEW_USER_TURN_REQUIRED",
                        pane=pane,
                        thread_id=thread_id,
                        turn_id=turn_id,
                        turn_started_at_ms=turn_started_at_ms,
                        revoked_at_ms=revoked_at_ms,
                    )
            generation = self.generations.get(pane, 0) + 1
            self.generations[pane] = generation
            lease = {
                "pane": pane,
                "generation": generation,
                "state": "ACTIVE",
                "issued_at": now(),
            }
            if thread_id:
                lease["authorization"] = {
                    "thread_id": thread_id,
                    "turn_id": turn_id,
                    "turn_started_at_ms": turn_started_at_ms,
                }
            self.leases[pane] = lease
            self.persist_state()
        if previous and previous.get("state") == "ACTIVE":
            self.record(
                "LEASE_SUPERSEDE",
                pane=pane,
                previous_generation=previous.get("generation"),
                generation=generation,
            )
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

    @staticmethod
    def _command_fingerprint(text: str):
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_long_run_budget(
        expected_duration_ms, idle_budget_ms, total_budget_ms
    ):
        try:
            expected_duration_ms = int(expected_duration_ms)
            idle_budget_ms = int(idle_budget_ms)
            total_budget_ms = int(total_budget_ms)
            if expected_duration_ms < 1 or not 1 <= idle_budget_ms <= total_budget_ms:
                raise ValueError
            if (
                expected_duration_ms > MAX_TOTAL_BUDGET_MS
                or total_budget_ms > MAX_TOTAL_BUDGET_MS
                or total_budget_ms < expected_duration_ms
            ):
                raise ValueError
        except (TypeError, ValueError) as error:
            raise BridgeError("INVALID_LONG_RUN_BUDGET") from error
        return expected_duration_ms, idle_budget_ms, total_budget_ms

    def _long_run_request(self, request_id: str):
        with self.lock:
            request = self.long_run_requests.get(request_id)
        if request is None:
            raise BridgeError("LONG_RUN_REQUEST_NOT_FOUND", request_id=request_id)
        if request.get("expires_at_ms", 0) <= unix_ms():
            with self.lock:
                request["status"] = "EXPIRED"
                self.persist_state()
            raise BridgeError("LONG_RUN_REQUEST_EXPIRED", request_id=request_id)
        return request

    def terminal_long_run_request(
        self,
        pane: str,
        generation: int,
        text: str,
        expected_duration_ms: int,
        resource_class: str,
        idle_budget_ms: int,
        total_budget_ms: int,
    ):
        """Create a durable, non-executing approval request for one command."""
        lease = self.require_lease(pane, generation)
        if not text or "\x00" in text:
            raise BridgeError("INVALID_LONG_RUN_COMMAND")
        (
            expected_duration_ms,
            idle_budget_ms,
            total_budget_ms,
        ) = self._validate_long_run_budget(
            expected_duration_ms, idle_budget_ms, total_budget_ms
        )
        if resource_class not in {"normal", "high_io", "full_scan"}:
            raise BridgeError("INVALID_RESOURCE_CLASS", resource_class=resource_class)
        fingerprint = self._command_fingerprint(text)
        with self.lock:
            existing = next(
                (
                    item for item in self.long_run_requests.values()
                    if item.get("pane") == pane
                    and item.get("command_fingerprint") == fingerprint
                    and item.get("expected_duration_ms") == expected_duration_ms
                    and item.get("resource_class") == resource_class
                    and item.get("status") in {"PENDING", "APPROVED"}
                    and item.get("expires_at_ms", 0) > unix_ms()
                ),
                None,
            )
            if existing is not None:
                return {
                    **existing,
                    "interaction": "input_required",
                    "prompt": (
                        "请向用户展示完整命令和资源影响；收到后续明确批准消息前不要执行。"
                    ),
                }
            request_id = f"lr_{uuid.uuid4().hex[:12]}"
            requested_at_ms = unix_ms()
            request = {
                "request_id": request_id,
                "status": "PENDING",
                "pane": pane,
                "requested_generation": generation,
                "command": text,
                "command_fingerprint": fingerprint,
                "expected_duration_ms": expected_duration_ms,
                "resource_class": resource_class,
                "idle_budget_ms": idle_budget_ms,
                "total_budget_ms": total_budget_ms,
                "authorization": dict(lease.get("authorization") or {}),
                "requested_at": now(),
                "requested_at_ms": requested_at_ms,
                "expires_at_ms": requested_at_ms + LONG_RUN_REQUEST_TTL_MS,
            }
            self.long_run_requests[request_id] = request
            self.persist_state()
        self.record(
            "LONG_RUN_REQUEST",
            pane=pane,
            generation=generation,
            request_id=request_id,
            command_fingerprint=fingerprint,
            resource_class=resource_class,
        )
        return {
            **request,
            "interaction": "input_required",
            "prompt": "请向用户展示完整命令和资源影响；收到后续明确批准消息前不要执行。",
        }

    def terminal_long_run_requests(self, status: str = None):
        """List approval requests for the local administrative CLI."""
        if status is not None and status not in {
            "PENDING", "APPROVED", "REJECTED", "CONSUMED", "EXPIRED"
        }:
            raise BridgeError("INVALID_LONG_RUN_STATUS", status=status)
        current_ms = unix_ms()
        changed = False
        with self.lock:
            for request in self.long_run_requests.values():
                if (
                    request.get("status") in {"PENDING", "APPROVED"}
                    and request.get("expires_at_ms", 0) <= current_ms
                ):
                    request["status"] = "EXPIRED"
                    changed = True
            if changed:
                self.persist_state()
            requests = [
                dict(request) for request in self.long_run_requests.values()
                if status is None or request.get("status") == status
            ]
        requests.sort(key=lambda item: item.get("requested_at_ms", 0), reverse=True)
        return {"requests": requests}

    def terminal_long_run_decide(self, request_id: str, decision: str):
        """Record a trusted local administrator's approve/reject decision."""
        if decision not in {"approve", "reject"}:
            raise BridgeError("INVALID_LONG_RUN_DECISION", decision=decision)
        request = self._long_run_request(request_id)
        if request.get("status") not in {"PENDING", "APPROVED"}:
            raise BridgeError(
                "LONG_RUN_REQUEST_NOT_PENDING",
                request_id=request_id,
                status=request.get("status"),
            )
        with self.lock:
            request["status"] = "APPROVED" if decision == "approve" else "REJECTED"
            request["decision_source"] = "local_cli"
            request["decided_at"] = now()
            self.persist_state()
        self.record(
            "LONG_RUN_DECIDE",
            pane=request["pane"],
            request_id=request_id,
            decision=decision,
            source="local_cli",
        )
        return dict(request)

    def terminal_long_run_approve(
        self,
        pane: str,
        generation: int,
        text: str = None,
        expected_duration_ms: int = None,
        resource_class: str = None,
        idle_budget_ms: int = None,
        total_budget_ms: int = None,
        request_id: str = None,
    ):
        """Record explicit, one-command long-run consent in local state."""
        self.require_lease(pane, generation)
        if request_id is not None:
            pending = self._long_run_request(request_id)
        else:
            if text is None:
                raise BridgeError("LONG_RUN_REQUEST_ID_REQUIRED")
            fingerprint = self._command_fingerprint(text)
            with self.lock:
                pending = next(
                    (
                        item for item in self.long_run_requests.values()
                        if item.get("pane") == pane
                        and item.get("command_fingerprint") == fingerprint
                        and item.get("status") == "PENDING"
                    ),
                    None,
                )
            if pending is None:
                raise BridgeError("LONG_RUN_REQUEST_NOT_FOUND")
            request_id = pending["request_id"]
        if pending.get("pane") != pane:
            raise BridgeError("LONG_RUN_REQUEST_PANE_MISMATCH", request_id=request_id)
        text = pending["command"]
        fingerprint = pending["command_fingerprint"]
        expected_duration_ms = pending["expected_duration_ms"]
        resource_class = pending["resource_class"]
        idle_budget_ms = pending["idle_budget_ms"]
        total_budget_ms = pending["total_budget_ms"]
        with self.lock:
            lease = self.leases.get(pane) or {}
            authorization = lease.get("authorization") or {}
        pending_authorization = (pending or {}).get("authorization") or {}
        locally_approved = (
            pending.get("status") == "APPROVED"
            and pending.get("decision_source") == "local_cli"
        )
        later_user_turn = bool(
            authorization.get("turn_id")
            and pending_authorization.get("turn_id")
            and authorization.get("thread_id") == pending_authorization.get("thread_id")
            and authorization.get("turn_id") != pending_authorization.get("turn_id")
            and authorization.get("turn_started_at_ms", 0)
            > pending_authorization.get("turn_started_at_ms", 0)
        )
        if pending.get("status") == "REJECTED":
            raise BridgeError("LONG_RUN_REQUEST_REJECTED", request_id=request_id)
        if not locally_approved and not later_user_turn:
            raise BridgeError(
                "LONG_RUN_APPROVAL_NEW_USER_TURN_REQUIRED",
                pane=pane,
                request_id=request_id,
                command_fingerprint=fingerprint,
            )
        approval_id = uuid.uuid4().hex
        approval = {
            "approval_id": approval_id,
            "request_id": request_id,
            "pane": pane,
            "generation": generation,
            "command": text,
            "command_fingerprint": fingerprint,
            "expected_duration_ms": expected_duration_ms,
            "resource_class": resource_class,
            "idle_budget_ms": idle_budget_ms,
            "total_budget_ms": total_budget_ms,
            "created_at": now(),
            "consumed": False,
        }
        with self.lock:
            self.long_run_approvals[approval_id] = approval
            pending["status"] = "CONSUMED"
            pending["consumed_at"] = now()
            self.persist_state()
        self.record(
            "LONG_RUN_APPROVE",
            pane=pane,
            generation=generation,
            approval_id=approval_id,
            request_id=request_id,
            command_fingerprint=approval["command_fingerprint"],
            resource_class=resource_class,
            total_budget_ms=total_budget_ms,
        )
        return dict(approval)

    @staticmethod
    def _last_nonempty_line(content: str):
        return next(
            (line.strip() for line in reversed(AIContextPolicy.normalize(content)) if line.strip()),
            "",
        )

    @staticmethod
    def _job_hard_deadline_ms(submitted_at_ms: int, expected_duration_ms: int):
        allowance = max(expected_duration_ms * 3, 20 * 60 * 1000)
        return submitted_at_ms + allowance

    def _create_job(self, pane, generation, text, expected_duration_ms, resource_class, baseline):
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        submitted_at_ms = unix_ms()
        job = {
            "job_id": job_id,
            "pane": pane,
            "generation": generation,
            "command": text,
            "command_fingerprint": self._command_fingerprint(text),
            "expected_duration_ms": expected_duration_ms,
            "resource_class": resource_class,
            "state": "RUNNING",
            "completion_confidence": None,
            "submitted_at": now(),
            "submitted_at_ms": submitted_at_ms,
            "hard_deadline_ms": self._job_hard_deadline_ms(
                submitted_at_ms, expected_duration_ms
            ),
            "strategy_review_at_ms": submitted_at_ms + 10 * 60 * 1000,
            "baseline_content": baseline,
            "baseline_prompt": self._last_nonempty_line(baseline),
            "last_content": baseline,
            "last_change_ms": submitted_at_ms,
            "last_activity_at": now(),
            "progress": None,
            "last_evidence_lines": [],
            "last_meaningful_activity_at": None,
            "notification_sent": False,
        }
        with self.lock:
            self.jobs[job_id] = job
            while len(self.jobs) > MAX_RETAINED_JOBS:
                removable = next(
                    (
                        existing_id for existing_id, existing in self.jobs.items()
                        if existing_id != job_id and existing.get("state") != "RUNNING"
                    ),
                    None,
                )
                if removable is None:
                    break
                self.jobs.pop(removable, None)
            self.persist_state()
        self.record("JOB_CREATE", pane=pane, generation=generation, job_id=job_id)
        return job

    @staticmethod
    def _interaction_prompt(delta_content: str):
        lines = [line for line in AIContextPolicy.normalize(delta_content) if line.strip()]
        tail = "\n".join(lines[-6:]).lower()
        patterns = (
            "password for ", "password:", "[y/n]", "[y/n]:", "(y/n)",
            "press enter", "are you sure you want to continue connecting",
        )
        return next((pattern for pattern in patterns if pattern in tail), None)

    def _notify_job(self, job):
        if (
            sys.platform != "darwin"
            or job.get("notification_sent")
            or (
                job.get("expected_duration_ms", 0) <= 30_000
                and job.get("resource_class") not in HIGH_RESOURCE_CLASSES
            )
        ):
            return
        title = "Shared Terminal Bridge"
        elapsed = max(0, unix_ms() - job["submitted_at_ms"]) // 1000
        message = f"{job['job_id']} {job['state']}，已运行 {elapsed} 秒"
        escape = lambda value: value.replace("\\", "\\\\").replace('"', '\\"')
        script = (
            f'display notification "{escape(message)}" '
            f'with title "{escape(title)}"'
        )
        try:
            subprocess.run(
                ["osascript", "-e", script],
                check=False,
                capture_output=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        with self.lock:
            job["notification_sent"] = True
            self.persist_state()

    def _refresh_job(self, job_id: str):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise BridgeError("TERMINAL_JOB_NOT_FOUND", job_id=job_id)
            if job["state"] in JOB_TERMINAL_STATES:
                return job
            pane = job["pane"]
            previous = job["last_content"]
            baseline = job["baseline_content"]
            lease = self.leases.get(pane)
            lease_snapshot = dict(lease) if lease else None
        try:
            current = self.tmux.read(pane, JOB_CAPTURE_LINES)
        except BridgeError as error:
            current_ms = unix_ms()
            state = job["state"]
            if current_ms >= job["hard_deadline_ms"]:
                with self.lock:
                    job["state"] = "HUMAN_DECISION_REQUIRED"
                    job["completion_confidence"] = "deadline"
                    job["attention_reason"] = "pane_unavailable_at_hard_deadline"
                    self.persist_state()
                    state = job["state"]
                self.record(
                    "JOB_STATE",
                    pane=pane,
                    job_id=job_id,
                    state=state,
                    reason=error.code,
                )
                self._signal_job_waits(job_id, state)
                self._notify_job(job)
            return job
        current_ms = unix_ms()
        changed = current != previous
        observation = AIContextPolicy.apply(
            baseline,
            current,
            max_bytes=AIContextPolicy.DEFAULT_MAX_BYTES,
            max_lines=AIContextPolicy.DEFAULT_MAX_LINES,
            command_echo=job["command"],
        )
        delta_content = observation["content"]
        human_override = bool(
            lease_snapshot
            and lease_snapshot.get("state") == "REVOKED"
            and lease_snapshot.get("event_seq") is not None
            and lease_snapshot.get("generation") == job["generation"]
        )
        prompt = self._interaction_prompt(delta_content)
        last_line = self._last_nonempty_line(current)
        evidence_lines = [
            line for line in AIContextPolicy.normalize(delta_content)
            if line.strip() and not line.strip().endswith(job["command"].strip())
        ][-5:]
        with self.lock:
            if changed:
                job["last_content"] = current
                job["last_change_ms"] = current_ms
                job["last_activity_at"] = now()
                if evidence_lines:
                    job["last_evidence_lines"] = evidence_lines
                    job["last_meaningful_activity_at"] = now()
            if human_override:
                job["state"] = "INTERRUPTED_BY_HUMAN"
                job["completion_confidence"] = "authoritative"
            elif prompt:
                job["state"] = "NEEDS_ATTENTION"
                job["attention_reason"] = prompt
                job["completion_confidence"] = "heuristic"
            elif (
                job["baseline_prompt"]
                and last_line == job["baseline_prompt"]
                and current != baseline
                and current_ms - job["last_change_ms"] >= JOB_PROMPT_STABLE_MS
            ):
                job["state"] = "COMPLETED"
                job["completion_confidence"] = "prompt_returned"
                job["completed_at"] = now()
            elif current_ms >= job["hard_deadline_ms"]:
                job["state"] = "HUMAN_DECISION_REQUIRED"
                job["completion_confidence"] = "deadline"
            state = job["state"]
            if state in JOB_TERMINAL_STATES:
                self.persist_state()
        if state in JOB_TERMINAL_STATES:
            self.record("JOB_STATE", pane=pane, job_id=job_id, state=state)
            self._signal_job_waits(job_id, state)
            self._notify_job(job)
        return job

    def _job_result(self, job, include_output=True):
        current_ms = unix_ms()
        result = {
            key: job.get(key) for key in (
                "job_id", "pane", "generation", "command", "command_fingerprint",
                "expected_duration_ms", "resource_class", "state",
                "completion_confidence", "submitted_at", "hard_deadline_ms",
                "strategy_review_at_ms", "last_activity_at", "progress",
                "last_meaningful_activity_at", "last_evidence_lines",
                "attention_reason", "completed_at",
            )
        }
        result["elapsed_ms"] = max(0, current_ms - job["submitted_at_ms"])
        result["hard_deadline_remaining_ms"] = max(
            0, job["hard_deadline_ms"] - current_ms
        )
        if include_output:
            result["observation"] = AIContextPolicy.apply(
                job["baseline_content"],
                job["last_content"],
                max_bytes=AIContextPolicy.DEFAULT_MAX_BYTES,
                max_lines=AIContextPolicy.DEFAULT_MAX_LINES,
                command_echo=job["command"],
            )
        return result

    def _signal_job_waits(self, job_id: str, reason: str):
        with self.lock:
            handles = [
                handle for handle in self.wait_handles.values()
                if handle["job_id"] == job_id
            ]
            for handle in handles:
                handle["wake_reason"] = reason
                handle["event"].set()

    def terminal_job_list(self, state: str = None):
        with self.lock:
            ids = list(self.jobs)
        jobs = [self._job_result(self._refresh_job(job_id), include_output=False) for job_id in ids]
        if state is not None:
            jobs = [job for job in jobs if job["state"] == state]
        jobs.sort(key=lambda item: item["submitted_at"], reverse=True)
        return {"jobs": jobs}

    def terminal_job_status(self, job_id: str):
        return self._job_result(self._refresh_job(job_id))

    def terminal_wait_list(self):
        with self.lock:
            waits = [
                {
                    "wait_id": wait_id,
                    "job_id": handle["job_id"],
                    "created_at": handle["created_at"],
                    "cancelled": handle["cancelled"],
                    "wake_reason": handle.get("wake_reason"),
                }
                for wait_id, handle in self.wait_handles.items()
            ]
        return {"waits": waits}

    def terminal_cancel_wait(self, wait_id: str):
        with self.lock:
            handle = self.wait_handles.get(wait_id)
            if handle is None:
                self.cancelled_wait_ids.add(wait_id)
                while len(self.cancelled_wait_ids) > 256:
                    self.cancelled_wait_ids.pop()
                return {"wait_id": wait_id, "cancelled": True, "pending_registration": True}
            handle["cancelled"] = True
            handle["wake_reason"] = "WAIT_CANCELLED"
            handle["event"].set()
        self.record("WAIT_CANCEL", wait_id=wait_id, job_id=handle["job_id"])
        return {"wait_id": wait_id, "job_id": handle["job_id"], "cancelled": True}

    def terminal_wait_job(
        self,
        job_id: str,
        wait_ms: int = MAX_JOB_WAIT_MS,
        wait_id: str = None,
    ):
        try:
            wait_ms = int(wait_ms)
            if not 1 <= wait_ms <= MAX_JOB_WAIT_MS:
                raise ValueError
        except (TypeError, ValueError) as error:
            raise BridgeError("INVALID_JOB_WAIT", wait_ms=wait_ms) from error
        wait_id = wait_id or f"wait_{uuid.uuid4().hex[:12]}"
        event = threading.Event()
        handle = {
            "job_id": job_id,
            "event": event,
            "created_at": now(),
            "cancelled": False,
            "wake_reason": None,
        }
        with self.lock:
            if wait_id in self.wait_handles:
                raise BridgeError("WAIT_ID_ALREADY_EXISTS", wait_id=wait_id)
            self.wait_handles[wait_id] = handle
            if wait_id in self.cancelled_wait_ids:
                self.cancelled_wait_ids.discard(wait_id)
                handle["cancelled"] = True
                handle["wake_reason"] = "WAIT_CANCELLED"
                event.set()
        try:
            job = self._refresh_job(job_id)
            if job["state"] in JOB_TERMINAL_STATES:
                result = self._job_result(job)
                result["wait_id"] = wait_id
                return result
            event.wait(wait_ms / 1000)
            job = self._refresh_job(job_id)
            result = self._job_result(job)
            result["wait_id"] = wait_id
            if job["state"] in JOB_TERMINAL_STATES:
                return result
            if handle["cancelled"]:
                result["state"] = "WAIT_CANCELLED"
                result["guidance"] = "Only the model wait was cancelled; the terminal job is still running."
            elif unix_ms() >= job["strategy_review_at_ms"]:
                result["state"] = "STRATEGY_REVIEW_REQUIRED"
                result["guidance"] = (
                    "Compare continued waiting with alternative approaches. Do not infer "
                    "progress from arbitrary percentages and do not interrupt automatically."
                )
            else:
                result["state"] = "WAIT_TIMEOUT"
            return result
        finally:
            with self.lock:
                self.wait_handles.pop(wait_id, None)

    def job_monitor_loop(self):
        while not self.stop_event.is_set():
            with self.lock:
                running = [
                    job_id for job_id, job in self.jobs.items()
                    if job.get("state") == "RUNNING"
                ]
            for job_id in running:
                try:
                    self._refresh_job(job_id)
                except BridgeError:
                    continue
            self.stop_event.wait(JOB_POLL_INTERVAL_SECONDS)

    def terminal_submit(
        self,
        pane: str,
        generation: int,
        text: str,
        expected_duration_ms: int = DEFAULT_TOTAL_BUDGET_MS,
        resource_class: str = "normal",
        long_run_approval_id: str = None,
    ):
        """Type one literal command and press Enter under the same lease check."""
        self.require_lease(pane, generation)
        try:
            expected_duration_ms = int(expected_duration_ms)
            if expected_duration_ms < 1:
                raise ValueError
        except (TypeError, ValueError) as error:
            raise BridgeError("INVALID_EXPECTED_DURATION") from error
        if resource_class not in {"normal", "high_io", "full_scan"}:
            raise BridgeError("INVALID_RESOURCE_CLASS", resource_class=resource_class)
        requires_approval = (
            expected_duration_ms > LONG_RUN_APPROVAL_MS
            or resource_class in HIGH_RESOURCE_CLASSES
        )
        if requires_approval:
            with self.lock:
                approval = self.long_run_approvals.get(long_run_approval_id)
                valid = bool(
                    approval
                    and not approval["consumed"]
                    and approval["pane"] == pane
                    and approval["generation"] == generation
                    and approval["command_fingerprint"]
                    == self._command_fingerprint(text)
                    and approval["expected_duration_ms"] == expected_duration_ms
                    and approval["resource_class"] == resource_class
                )
                if valid:
                    approval["consumed"] = True
            if not valid:
                total_budget_ms = min(
                    MAX_TOTAL_BUDGET_MS,
                    max(expected_duration_ms, DEFAULT_TOTAL_BUDGET_MS),
                )
                request = self.terminal_long_run_request(
                    pane,
                    generation,
                    text,
                    expected_duration_ms,
                    resource_class,
                    min(DEFAULT_IDLE_BUDGET_MS, total_budget_ms),
                    total_budget_ms,
                )
                raise BridgeError(
                    "LONG_RUN_APPROVAL_REQUIRED",
                    pane=pane,
                    generation=generation,
                    request_id=request["request_id"],
                    interaction="input_required",
                    command=text,
                    command_fingerprint=request["command_fingerprint"],
                    expected_duration_ms=expected_duration_ms,
                    resource_class=resource_class,
                    idle_budget_ms=request["idle_budget_ms"],
                    total_budget_ms=request["total_budget_ms"],
                    prompt=(
                        "请向用户展示完整命令和资源影响；收到后续明确批准消息前不要执行。"
                    ),
                )
        baseline = self.tmux.read(pane, JOB_CAPTURE_LINES)
        self.tmux.send_text(pane, text)
        self.tmux.send_key(pane, "Enter")
        job = self._create_job(
            pane, generation, text, expected_duration_ms, resource_class, baseline
        )
        byte_count = len(text.encode())
        self.record(
            "SUBMIT",
            pane=pane,
            generation=generation,
            bytes=byte_count,
        )
        return {
            "accepted": True,
            "bytes": byte_count,
            "key": "Enter",
            "expected_duration_ms": expected_duration_ms,
            "resource_class": resource_class,
            "long_running_notice": expected_duration_ms > 30_000,
            "approval_id": long_run_approval_id if requires_approval else None,
            "job_id": job["job_id"],
            "job_state": job["state"],
        }

    def terminal_task_block(
        self,
        pane: str,
        generation: int,
        commands,
        stop_on_error: bool = True,
    ):
        """Create local task metadata without writing anything to the pane.

        Commands are retained only as a count.  Callers must submit every
        visible terminal action separately through terminal_submit/key/type.
        """
        self.require_lease(pane, generation)
        if not isinstance(commands, list) or not 1 <= len(commands) <= 32:
            raise BridgeError("INVALID_TASK_BLOCK", reason="commands must contain 1..32 items")
        if any(not isinstance(command, str) or not command.strip() for command in commands):
            raise BridgeError("INVALID_TASK_BLOCK", reason="commands must be non-empty strings")
        if any("\x00" in command for command in commands):
            raise BridgeError("INVALID_TASK_BLOCK", reason="commands must not contain NUL")
        total_bytes = sum(len(command.encode()) for command in commands)
        if total_bytes > 16_384:
            raise BridgeError("INVALID_TASK_BLOCK", reason="command bytes exceed 16384")

        block_id = uuid.uuid4().hex
        baseline = self.tmux.read(pane, CONTEXT_CAPTURE_LINES)
        with self.lock:
            self.task_blocks[block_id] = {
                "block_id": block_id,
                "pane": pane,
                "generation": generation,
                "commands": len(commands),
                "stop_on_error": bool(stop_on_error),
                "transport": "none",
                "last_content": baseline,
                "cursor": None,
                "state": "PLANNED",
                "created_at": now(),
            }
        self.record(
            "TASK_BLOCK_CREATE",
            pane=pane,
            generation=generation,
            block_id=block_id,
            commands=len(commands),
            bytes=total_bytes,
        )
        return {
            "accepted": True,
            "block_id": block_id,
            "pane": pane,
            "generation": generation,
            "commands": len(commands),
            "transport": "none",
            "writes_to_pane": False,
            "explicit_submits_required": True,
            "state": "PLANNED",
        }

    def terminal_task_observe(
        self,
        block_id: str,
        max_bytes: int = AIContextPolicy.DEFAULT_MAX_BYTES,
        max_lines: int = AIContextPolicy.DEFAULT_MAX_LINES,
    ):
        try:
            max_bytes = int(max_bytes)
            max_lines = int(max_lines)
            if not 1 <= max_bytes <= AIContextPolicy.MAX_BYTES:
                raise ValueError
            if not 1 <= max_lines <= AIContextPolicy.MAX_LINES:
                raise ValueError
        except (TypeError, ValueError) as error:
            raise BridgeError(
                "INVALID_CONTEXT_BUDGET",
                max_bytes=max_bytes,
                max_lines=max_lines,
            ) from error
        with self.lock:
            block = self.task_blocks.get(block_id)
            if block is None:
                raise BridgeError("TASK_BLOCK_NOT_FOUND", block_id=block_id)
            pane = block["pane"]
            previous = block["last_content"]
            generation = block["generation"]
        self.authorize(pane)
        current = self.tmux.read(pane, CONTEXT_CAPTURE_LINES)
        result = AIContextPolicy.apply(
            previous,
            current,
            max_bytes=max_bytes,
            max_lines=max_lines,
        )
        with self.lock:
            next_cursor = uuid.uuid4().hex
            block["cursor"] = next_cursor
            block["last_content"] = current
            lease = self.leases.get(pane)
            lease_snapshot = dict(lease) if lease else None
        human_override = bool(
            lease_snapshot
            and lease_snapshot.get("state") == "REVOKED"
            and lease_snapshot.get("event_seq") is not None
        )
        if human_override:
            state = "INTERRUPTED"
        elif (
            lease_snapshot
            and lease_snapshot.get("state") == "ACTIVE"
            and lease_snapshot.get("generation") == generation
        ):
            state = "ACTIVE"
        else:
            state = "INACTIVE"
        with self.lock:
            block["state"] = state
        self.record("TASK_BLOCK_OBSERVE", pane=pane, block_id=block_id, state=state)
        return {
            "block_id": block_id,
            "pane": pane,
            "state": state,
            "exit_code": None,
            "cursor": next_cursor,
            **result,
            "execution": {"lease": lease_snapshot, "human_override": human_override},
        }

    def terminal_key(self, pane: str, generation: int, key: str):
        self.require_lease(pane, generation)
        self.tmux.send_key(pane, key)
        self.record("KEY", pane=pane, generation=generation, key=key)
        return {"accepted": True, "key": key}

    def terminal_interrupt(self, pane: str, generation: int):
        self.require_lease(pane, generation)
        self.tmux.send_key(pane, "C-c")
        interrupt_id = uuid.uuid4().hex
        with self.lock:
            self.interrupt_sources[pane] = {
                "source": "agent",
                "interrupt_id": interrupt_id,
                "generation": generation,
                "timestamp": now(),
            }
        self.record(
            "AGENT_INTERRUPT",
            pane=pane,
            generation=generation,
            interrupt_id=interrupt_id,
        )
        return {"accepted": True, "source": "agent", "interrupt_id": interrupt_id}

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
            self.interrupt_sources[pane] = {
                "source": "human",
                "event_seq": event["seq"],
                "timestamp": event.get("timestamp") or now(),
            }
            lease = self.leases.get(pane)
            if lease and lease["state"] == "ACTIVE":
                lease["state"] = "REVOKED"
                lease["revoked_at"] = now()
                lease["revoked_at_ms"] = unix_ms()
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
        job_thread = threading.Thread(target=self.job_monitor_loop, daemon=True)
        job_thread.start()

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
        job_thread.join(timeout=1)
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
