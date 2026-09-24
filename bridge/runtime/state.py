"""Persistent daemon state and single-instance ownership."""

import fcntl
import json
import os
import pathlib
import tempfile

from bridge.common import BridgeError, now, unix_ms
from bridge.config import DEFAULT_TOTAL_BUDGET_MS

class StateService:
    def __init__(self, bridge):
        self.bridge = bridge

    def acquire_instance_lock(self):
        self.bridge.instance_lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self.bridge.instance_lock_path.open("a+", encoding="utf-8")
        os.chmod(self.bridge.instance_lock_path, 0o600)
        try:
            fcntl.flock(
                lock_file.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError as error:
            lock_file.close()
            raise BridgeError(
                "INSTANCE_ALREADY_RUNNING",
                state_file=str(self.bridge.state_file),
            ) from error
        self.bridge.instance_lock_file = lock_file

    def release_instance_lock(self):
        if self.bridge.instance_lock_file is not None:
            fcntl.flock(self.bridge.instance_lock_file.fileno(), fcntl.LOCK_UN)
            self.bridge.instance_lock_file.close()
            self.bridge.instance_lock_file = None

    def persistent_state(self):
        return {
            "schema_version": 1,
            "tmux_socket": self.bridge.tmux.socket_name,
            "tmux_server_id": self.bridge.tmux_server_id,
            "generations": self.bridge.generations,
            "leases": self.bridge.leases,
            "managed_sessions": self.bridge.managed_sessions,
            "long_run_requests": self.bridge.long_run_requests,
            "jobs": self.bridge.jobs,
            "binding": {
                "snapshot_taken": self.bridge.binding_snapshot_taken,
                "installed": self.bridge.human_binding_installed,
                "original": self.bridge.original_human_binding,
            },
        }

    def persist_state(self):
        self.bridge.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.bridge.state_file.parent,
                prefix=f".{self.bridge.state_file.name}.",
                delete=False,
            ) as temporary:
                json.dump(
                    self.bridge.persistent_state(),
                    temporary,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = pathlib.Path(temporary.name)
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, self.bridge.state_file)
            os.chmod(self.bridge.state_file, 0o600)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def load_state(self):
        if not self.bridge.state_file.exists():
            return
        state = json.loads(self.bridge.state_file.read_text(encoding="utf-8"))
        if state.get("schema_version") != 1:
            raise BridgeError("STATE_SCHEMA_UNSUPPORTED")
        if state.get("tmux_socket") != self.bridge.tmux.socket_name:
            raise BridgeError(
                "STATE_TMUX_SOCKET_MISMATCH",
                expected=self.bridge.tmux.socket_name,
                actual=state.get("tmux_socket"),
            )
        if state.get("tmux_server_id") != self.bridge.tmux_server_id:
            raise BridgeError(
                "STATE_TMUX_SERVER_MISMATCH",
                expected=self.bridge.tmux_server_id,
                actual=state.get("tmux_server_id"),
            )
        self.bridge.generations = {
            pane: int(generation)
            for pane, generation in state.get("generations", {}).items()
        }
        self.bridge.leases = state.get("leases", {})
        self.bridge.managed_sessions = state.get("managed_sessions", {})
        self.bridge.long_run_requests = state.get("long_run_requests", {})
        self.bridge.jobs = state.get("jobs", {})
        for job in self.bridge.jobs.values():
            # v0.9 inferred arbitrary percentages (for example df usage) as
            # progress. Progress is now unknown unless a command-specific
            # parser supplies evidence.
            job["progress"] = None
            job.setdefault("last_evidence_lines", [])
            job.setdefault("output_excerpt", None)
            job.setdefault("baseline_pane_command", None)
            job.setdefault("last_meaningful_activity_at", None)
            submitted_at_ms = int(job.get("submitted_at_ms", unix_ms()))
            expected_duration_ms = int(
                job.get("expected_duration_ms", DEFAULT_TOTAL_BUDGET_MS)
            )
            job["strategy_review_at_ms"] = submitted_at_ms + 10 * 60 * 1000
            job["hard_deadline_ms"] = self.bridge._job_hard_deadline_ms(
                submitted_at_ms, expected_duration_ms
            )
        if self.bridge.allow_session_management:
            live_managed = {
                session["managed_id"]: session
                for session in self.bridge.tmux.list_managed_sessions()
            }
            self.bridge.managed_sessions = {
                managed_id: session
                for managed_id, session in self.bridge.managed_sessions.items()
                if managed_id in live_managed
            }
            for session in self.bridge.managed_sessions.values():
                self.bridge.allowed_panes.add(session["pane"])
        binding = state.get("binding", {})
        self.bridge.binding_snapshot_taken = bool(
            binding.get("snapshot_taken", False)
        )
        self.bridge.human_binding_installed = bool(
            binding.get("installed", False)
        )
        self.bridge.original_human_binding = binding.get("original")

        recovered = False
        for lease in self.bridge.leases.values():
            if lease.get("state") == "ACTIVE":
                lease["state"] = "REVOKED"
                lease["revoked_at"] = now()
                lease["revoke_reason"] = "daemon_restart"
                recovered = True
        if recovered:
            self.bridge.persist_state()
