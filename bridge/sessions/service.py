"""Session discovery, lifecycle, and human-binding APIs."""

import pathlib
import re

try:
    from bridge.common import BridgeError, now
    from bridge.config import BRIDGE_API_VERSION, BRIDGE_VERSION, PROGRAM_CAPABILITY_PROFILES
except ModuleNotFoundError:
    from common import BridgeError, now
    from config import BRIDGE_API_VERSION, BRIDGE_VERSION, PROGRAM_CAPABILITY_PROFILES


class SessionService:
    def __init__(self, bridge):
        self.bridge = bridge

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
            "terminal_history",
            "terminal_task_block",
            "terminal_task_block_execute",
            "terminal_task_observe",
            "terminal_program_profile",
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
        for pane in self.bridge.tmux.list_panes():
            panes.append(
                {
                    **pane,
                    "authorized": pane["pane"] in self.bridge.allowed_panes,
                }
            )
        self.bridge.record("LIST", panes=len(panes))
        return {"panes": panes}

    def terminal_program_profile(self, program=None):
        """Return local guidance without reading or writing a terminal pane."""
        if program is None:
            return {
                "profiles": [
                    {
                        "program": name,
                        "preferred_interface": profile["preferred_interface"],
                        "tui_policy": profile["tui_policy"],
                    }
                    for name, profile in sorted(PROGRAM_CAPABILITY_PROFILES.items())
                ]
            }
        normalized = pathlib.PurePath(str(program).strip()).name.lower()
        profile = PROGRAM_CAPABILITY_PROFILES.get(normalized)
        if profile is None:
            raise BridgeError("PROGRAM_PROFILE_NOT_FOUND", program=normalized)
        return {"profile": dict(profile)}

    def require_session_management(self):
        if not self.bridge.allow_session_management:
            raise BridgeError("SESSION_MANAGEMENT_DISABLED")

    def terminal_session_list(self):
        self.bridge.require_session_management()
        sessions = self.bridge.tmux.list_managed_sessions()
        self.bridge.record("SESSION_LIST", sessions=len(sessions))
        return {"sessions": sessions}

    def terminal_session_resolve(self, name: str):
        self.bridge.require_session_management()
        session = next(
            (item for item in self.bridge.tmux.list_managed_sessions() if item["name"] == name),
            None,
        )
        if session is None:
            raise BridgeError("SESSION_NOT_MANAGED", session=name)
        self.bridge.authorize(session["pane"])
        self.bridge.record("SESSION_RESOLVE", session=name, pane=session["pane"])
        return session

    def terminal_session_read_delta(self, name: str, **params):
        session = self.bridge.terminal_session_resolve(name)
        result = self.bridge.terminal_read_delta(session["pane"], **params)
        result["session"] = name
        return result

    def terminal_session_wait_delta(self, name: str, **params):
        session = self.bridge.terminal_session_resolve(name)
        result = self.bridge.terminal_wait_delta(session["pane"], **params)
        result["session"] = name
        return result

    def terminal_session_state(self, name: str):
        session = self.bridge.terminal_session_resolve(name)
        result = self.bridge.terminal_state(session["pane"])
        result["session"] = name
        return result

    def terminal_session_create(self, name: str, cwd: str):
        self.bridge.require_session_management()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name):
            raise BridgeError("INVALID_SESSION_NAME", session=name)
        cwd_path = pathlib.Path(cwd).expanduser()
        if not cwd_path.is_absolute() or not cwd_path.is_dir():
            raise BridgeError("INVALID_SESSION_CWD", cwd=cwd)
        session = self.bridge.tmux.create_managed_session(name, str(cwd_path))
        with self.bridge.lock:
            self.bridge.allowed_panes.add(session["pane"])
            self.bridge.managed_sessions[session["managed_id"]] = session
            self.bridge.persist_state()
        self.bridge.record(
            "SESSION_CREATE",
            session=name,
            pane=session["pane"],
            managed_id=session["managed_id"],
        )
        return session

    def terminal_session_stop(self, name: str):
        self.bridge.require_session_management()
        session = next(
            (
                item
                for item in self.bridge.tmux.list_managed_sessions()
                if item["name"] == name
            ),
            None,
        )
        if session is None:
            raise BridgeError("SESSION_NOT_MANAGED", session=name)
        pane = session["pane"]
        self.bridge.tmux.stop_managed_session(name)
        with self.bridge.lock:
            self.bridge.allowed_panes.discard(pane)
            lease = self.bridge.leases.get(pane)
            if lease and lease.get("state") == "ACTIVE":
                lease["state"] = "REVOKED"
                lease["revoked_at"] = now()
                lease["revoke_reason"] = "session_stopped"
            self.bridge.managed_sessions.pop(session["managed_id"], None)
            self.bridge.persist_state()
        self.bridge.record("SESSION_STOP", session=name, pane=pane)
        return {"stopped": True, "name": name, "pane": pane}

    def get_active_pane(self, client: str):
        result = self.bridge.tmux.active_pane(client)
        result["authorized"] = result["pane"] in self.bridge.allowed_panes
        self.bridge.record(
            "ACTIVE",
            client=client,
            pane=result["pane"],
            authorized=result["authorized"],
        )
        return result

    def terminal_state(self, pane: str):
        self.bridge.authorize(pane)
        state = self.bridge.tmux.state(pane)
        self.bridge.record("STATE", pane=pane)
        return state

    def install_human_binding(self):
        with self.bridge.lock:
            if self.bridge.human_binding_installed:
                return {
                    "installed": True,
                    "already_installed": True,
                    "original_binding_present": (
                        self.bridge.original_human_binding is not None
                    ),
                }
            self.bridge.original_human_binding = (
                self.bridge.tmux.get_root_ctrl_c_binding()
            )
            self.bridge.binding_snapshot_taken = True
        self.bridge.tmux.install_human_binding(
            self.bridge.event_socket,
            pathlib.Path(__file__).resolve(),
        )
        with self.bridge.lock:
            self.bridge.human_binding_installed = True
            self.bridge.persist_state()
        self.bridge.record("BINDING_INSTALL")
        return {
            "installed": True,
            "already_installed": False,
            "original_binding_present": (
                self.bridge.original_human_binding is not None
            ),
        }

    def restore_human_binding(self):
        with self.bridge.lock:
            if not self.bridge.binding_snapshot_taken:
                raise BridgeError("BINDING_SNAPSHOT_NOT_FOUND")
            original = self.bridge.original_human_binding
        self.bridge.tmux.restore_root_ctrl_c_binding(original)
        with self.bridge.lock:
            self.bridge.original_human_binding = None
            self.bridge.binding_snapshot_taken = False
            self.bridge.human_binding_installed = False
            self.bridge.persist_state()
        self.bridge.record(
            "BINDING_RESTORE",
            restored_original=original is not None,
        )
        return {
            "restored": True,
            "restored_original": original is not None,
        }

    def human_binding_status(self):
        with self.bridge.lock:
            return {
                "installed": self.bridge.human_binding_installed,
                "snapshot_available": self.bridge.binding_snapshot_taken,
                "original_binding_present": (
                    self.bridge.original_human_binding is not None
                ),
            }
