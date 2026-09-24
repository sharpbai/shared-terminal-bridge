#!/usr/bin/env python3
"""Local JSON bridge for pane-scoped tmux observation and control."""

import argparse
import json
import pathlib
import signal
import socket
import sys
import threading

if __package__ in (None, ""):  # Direct execution: ./bridge/local_bridge.py
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

try:
    from bridge.common import BridgeError, now, unix_ms
except ModuleNotFoundError:  # Direct execution: ./bridge/local_bridge.py
    from common import BridgeError, now, unix_ms


try:
    from bridge.config import *  # noqa: F403 - compatibility re-exports
except ModuleNotFoundError:  # Direct execution: ./bridge/local_bridge.py
    from config import *  # noqa: F403 - compatibility re-exports


try:
    from bridge.tmux.backend import TmuxBackend
    from bridge.execution.authority import AuthorityService
    from bridge.execution.jobs import JobService
    from bridge.execution.job_wait import JobWaitService
    from bridge.execution.long_run import LongRunService
    from bridge.execution.read_only_policy import ReadOnlyPolicy
    from bridge.execution.submit import SubmitService
    from bridge.execution.task_blocks import TaskBlockService
    from bridge.observation.service import ObservationService
    from bridge.protocol.registry import resolve_handler
    from bridge.runtime.audit import AuditService
    from bridge.runtime.human_events import HumanEventService
    from bridge.runtime.socket_server import SocketServerService
    from bridge.runtime.state import StateService
    from bridge.service import ServiceMethod
    from bridge.sessions.service import SessionService
except ModuleNotFoundError:  # Direct execution: ./bridge/local_bridge.py
    from tmux.backend import TmuxBackend
    from execution.authority import AuthorityService
    from execution.jobs import JobService
    from execution.job_wait import JobWaitService
    from execution.long_run import LongRunService
    from execution.read_only_policy import ReadOnlyPolicy
    from execution.submit import SubmitService
    from execution.task_blocks import TaskBlockService
    from observation.service import ObservationService
    from protocol.registry import resolve_handler
    from runtime.audit import AuditService
    from runtime.human_events import HumanEventService
    from runtime.socket_server import SocketServerService
    from runtime.state import StateService
    from service import ServiceMethod
    from sessions.service import SessionService


class LocalBridge:
    _service_types = {
        "state": StateService,
        "audit": AuditService,
        "human_events": HumanEventService,
        "socket_server": SocketServerService,
        "sessions": SessionService,
        "observation": ObservationService,
        "authority": AuthorityService,
        "long_run": LongRunService,
        "jobs": JobService,
        "job_wait": JobWaitService,
        "submit": SubmitService,
        "task_blocks": TaskBlockService,
    }

    def _service(self, name):
        cache = self.__dict__.setdefault("_service_cache", {})
        if name not in cache:
            cache[name] = self._service_types[name](self)
        return cache[name]

    @classmethod
    def _validate_read_only_command(cls, text):
        """Compatibility entry point for the stateless Runner policy."""
        return ReadOnlyPolicy.validate(text)

    # bridge/runtime/state.py
    acquire_instance_lock = ServiceMethod("state")
    release_instance_lock = ServiceMethod("state")
    persistent_state = ServiceMethod("state")
    persist_state = ServiceMethod("state")
    load_state = ServiceMethod("state")

    # bridge/runtime/audit.py
    record = ServiceMethod("audit")
    terminal_history = ServiceMethod("audit")
    audit_log = ServiceMethod("audit")

    # bridge/runtime/human_events.py
    handle_human_event = ServiceMethod("human_events")

    # bridge/runtime/socket_server.py
    prepare_socket = ServiceMethod("socket_server")
    event_loop = ServiceMethod("socket_server")
    handle_connection = ServiceMethod("socket_server")
    serve = ServiceMethod("socket_server")
    stop = ServiceMethod("socket_server")

    # bridge/sessions/service.py
    bridge_info = ServiceMethod("sessions")
    terminal_list = ServiceMethod("sessions")
    terminal_program_profile = ServiceMethod("sessions")
    require_session_management = ServiceMethod("sessions")
    terminal_session_list = ServiceMethod("sessions")
    terminal_session_resolve = ServiceMethod("sessions")
    terminal_session_read_delta = ServiceMethod("sessions")
    terminal_session_wait_delta = ServiceMethod("sessions")
    terminal_session_state = ServiceMethod("sessions")
    terminal_session_create = ServiceMethod("sessions")
    terminal_session_stop = ServiceMethod("sessions")
    get_active_pane = ServiceMethod("sessions")
    terminal_state = ServiceMethod("sessions")
    install_human_binding = ServiceMethod("sessions")
    restore_human_binding = ServiceMethod("sessions")
    human_binding_status = ServiceMethod("sessions")

    # bridge/observation/service.py
    terminal_read = ServiceMethod("observation")
    terminal_read_delta = ServiceMethod("observation")
    _replace_observation_cursor = ServiceMethod("observation")
    _interrupt_source = ServiceMethod("observation")
    terminal_wait_delta = ServiceMethod("observation")

    # bridge/execution/authority.py
    authorize = ServiceMethod("authority")
    require_lease = ServiceMethod("authority")
    acquire_execution = ServiceMethod("authority")
    release_execution = ServiceMethod("authority")
    execution_status = ServiceMethod("authority")
    terminal_type = ServiceMethod("authority")

    # bridge/execution/long_run.py
    _command_fingerprint = ServiceMethod("long_run")
    _history_command = ServiceMethod("long_run")
    _validate_long_run_budget = ServiceMethod("long_run")
    _long_run_request = ServiceMethod("long_run")
    terminal_long_run_request = ServiceMethod("long_run")
    terminal_long_run_requests = ServiceMethod("long_run")
    terminal_long_run_decide = ServiceMethod("long_run")
    terminal_long_run_approve = ServiceMethod("long_run")

    # bridge/execution/jobs.py
    _last_nonempty_line = ServiceMethod("jobs")
    _job_hard_deadline_ms = ServiceMethod("jobs")
    _create_job = ServiceMethod("jobs")
    _interaction_prompt = ServiceMethod("jobs")
    _notify_job = ServiceMethod("jobs")
    _refresh_job = ServiceMethod("jobs")
    _job_result = ServiceMethod("jobs")
    job_monitor_loop = ServiceMethod("jobs")

    # bridge/execution/job_wait.py
    _signal_job_waits = ServiceMethod("job_wait")
    terminal_job_list = ServiceMethod("job_wait")
    terminal_job_status = ServiceMethod("job_wait")
    terminal_wait_list = ServiceMethod("job_wait")
    terminal_cancel_wait = ServiceMethod("job_wait")
    terminal_wait_job = ServiceMethod("job_wait")

    # bridge/execution/submit.py
    _command_completeness = ServiceMethod("submit")
    terminal_submit = ServiceMethod("submit")

    # bridge/execution/task_blocks.py
    terminal_task_block = ServiceMethod("task_blocks")
    _task_assertion = ServiceMethod("task_blocks")
    _compact_task_excerpt = ServiceMethod("task_blocks")
    terminal_task_block_execute = ServiceMethod("task_blocks")
    terminal_task_observe = ServiceMethod("task_blocks")
    terminal_key = ServiceMethod("task_blocks")
    terminal_interrupt = ServiceMethod("task_blocks")

    def __init__(
        self,
        tmux_socket: str,
        control_socket: pathlib.Path,
        event_socket: pathlib.Path,
        allowed_panes,
        state_file: pathlib.Path,
        history_file: pathlib.Path = DEFAULT_HISTORY_FILE,
        allow_session_management: bool = False,
    ):
        self.tmux = TmuxBackend(tmux_socket)
        self.control_socket = control_socket
        self.event_socket = event_socket
        self.allowed_panes = set(allowed_panes)
        self.allow_session_management = allow_session_management
        self.managed_sessions = {}
        self.state_file = state_file
        self.history_file = history_file
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


    def dispatch(self, method: str, params):
        handler = resolve_handler(self, method)
        if handler is None:
            raise BridgeError("METHOD_NOT_FOUND", method=method)
        return handler(**params)


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
    serve_parser.add_argument(
        "--history-file",
        type=pathlib.Path,
        default=DEFAULT_HISTORY_FILE,
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
            history_file=args.history_file,
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
