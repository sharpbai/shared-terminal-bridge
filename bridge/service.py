"""Explicit service dependencies and compatibility facade descriptors."""


SERVICE_DEPENDENCIES = {
    "state": {
        "_job_hard_deadline_ms", "allow_session_management", "allowed_panes",
        "binding_snapshot_taken", "generations", "human_binding_installed",
        "instance_lock_file", "instance_lock_path", "jobs", "leases",
        "long_run_requests", "managed_sessions", "original_human_binding",
        "persist_state", "persistent_state", "state_file", "tmux",
        "tmux_server_id",
    },
    "audit": {"audit", "history_file", "lock", "managed_sessions"},
    "human_events": {
        "event_sequence", "interrupt_sources", "leases", "lock",
        "persist_state", "record",
    },
    "socket_server": {
        "control_listener", "control_socket", "dispatch", "event_listener",
        "event_loop", "event_socket", "handle_connection",
        "handle_human_event", "job_monitor_loop", "prepare_socket", "record",
        "release_instance_lock", "stop_event",
    },
    "sessions": {
        "allow_session_management", "allowed_panes", "authorize",
        "binding_snapshot_taken", "event_socket", "human_binding_installed",
        "leases", "lock", "managed_sessions", "original_human_binding",
        "persist_state", "record", "require_session_management",
        "terminal_read_delta", "terminal_session_resolve", "terminal_state",
        "terminal_wait_delta", "tmux",
    },
    "observation": {
        "_interrupt_source", "_replace_observation_cursor", "authorize",
        "interrupt_sources", "leases", "lock", "observation_cursors",
        "record", "tmux",
    },
    "authority": {
        "allowed_panes", "authorize", "generations", "leases", "lock",
        "persist_state", "record", "require_lease", "tmux",
    },
    "long_run": {
        "_command_fingerprint", "_long_run_request", "_validate_long_run_budget",
        "leases", "lock", "long_run_approvals", "long_run_requests",
        "persist_state", "record", "require_lease",
    },
    "jobs": {
        "_command_fingerprint", "_history_command", "_interaction_prompt",
        "_job_hard_deadline_ms", "_last_nonempty_line", "_notify_job",
        "_refresh_job", "_signal_job_waits", "jobs", "leases", "lock",
        "persist_state", "record", "stop_event", "tmux",
    },
    "job_wait": {
        "_job_result", "_refresh_job", "cancelled_wait_ids", "jobs", "lock",
        "record", "wait_handles",
    },
    "submit": {
        "_command_completeness", "_command_fingerprint", "_create_job",
        "_history_command", "lock", "long_run_approvals", "record",
        "require_lease", "terminal_long_run_request", "tmux",
    },
    "task_blocks": {
        "_compact_task_excerpt", "_task_assertion", "_validate_read_only_command",
        "authorize", "interrupt_sources", "leases", "lock", "record",
        "require_lease", "task_blocks", "terminal_submit", "terminal_wait_job",
        "tmux",
    },
}


class ServiceContext:
    """Expose only the owner capabilities declared for one domain service."""

    def __init__(self, owner, service_name):
        object.__setattr__(self, "_owner", owner)
        object.__setattr__(self, "_service_name", service_name)
        object.__setattr__(self, "_allowed", SERVICE_DEPENDENCIES[service_name])

    def __getattr__(self, name):
        if name not in self._allowed:
            raise AttributeError(
                f"{self._service_name} service dependency is not declared: {name}"
            )
        return getattr(self._owner, name)

    def __setattr__(self, name, value):
        if name not in self._allowed:
            raise AttributeError(
                f"{self._service_name} service dependency is not declared: {name}"
            )
        setattr(self._owner, name, value)


class ServiceMethod:
    """Bind one facade attribute to one named domain service method."""

    def __init__(self, service_name, method_name=None):
        self.service_name = service_name
        self.method_name = method_name

    def __set_name__(self, owner, name):
        if self.method_name is None:
            self.method_name = name

    def __get__(self, instance, owner):
        if instance is None:
            return self
        service = instance._service(self.service_name)
        return getattr(service, self.method_name)
