"""Canonical mapping from Bridge protocol methods to implementation methods.

Start here when locating the code behind a public Bridge operation.
"""

METHOD_HANDLERS = {
    "bridge_info": ("sessions/service.py", "bridge_info"),
    "terminal_list": ("sessions/service.py", "terminal_list"),
    "get_active_pane": ("sessions/service.py", "get_active_pane"),
    "terminal_read": ("observation/service.py", "terminal_read"),
    "terminal_read_delta": ("observation/service.py", "terminal_read_delta"),
    "terminal_wait_delta": ("observation/service.py", "terminal_wait_delta"),
    "terminal_state": ("sessions/service.py", "terminal_state"),
    "install_human_binding": ("sessions/service.py", "install_human_binding"),
    "restore_human_binding": ("sessions/service.py", "restore_human_binding"),
    "human_binding_status": ("sessions/service.py", "human_binding_status"),
    "acquire_execution": ("execution/authority.py", "acquire_execution"),
    "release_execution": ("execution/authority.py", "release_execution"),
    "execution_status": ("execution/authority.py", "execution_status"),
    "terminal_type": ("execution/authority.py", "terminal_type"),
    "terminal_submit": ("execution/submit.py", "terminal_submit"),
    "terminal_long_run_request": ("execution/long_run.py", "terminal_long_run_request"),
    "terminal_long_run_approve": ("execution/long_run.py", "terminal_long_run_approve"),
    "terminal_long_run_requests": ("execution/long_run.py", "terminal_long_run_requests"),
    "terminal_long_run_decide": ("execution/long_run.py", "terminal_long_run_decide"),
    "terminal_job_list": ("execution/job_wait.py", "terminal_job_list"),
    "terminal_job_status": ("execution/job_wait.py", "terminal_job_status"),
    "terminal_wait_job": ("execution/job_wait.py", "terminal_wait_job"),
    "terminal_wait_list": ("execution/job_wait.py", "terminal_wait_list"),
    "terminal_cancel_wait": ("execution/job_wait.py", "terminal_cancel_wait"),
    "terminal_history": ("runtime/audit.py", "terminal_history"),
    "terminal_task_block": ("execution/task_blocks.py", "terminal_task_block"),
    "terminal_task_block_execute": ("execution/task_blocks.py", "terminal_task_block_execute"),
    "terminal_task_observe": ("execution/task_blocks.py", "terminal_task_observe"),
    "terminal_program_profile": ("sessions/service.py", "terminal_program_profile"),
    "terminal_key": ("execution/task_blocks.py", "terminal_key"),
    "terminal_interrupt": ("execution/task_blocks.py", "terminal_interrupt"),
    "audit_log": ("runtime/audit.py", "audit_log"),
    "terminal_session_list": ("sessions/service.py", "terminal_session_list"),
    "terminal_session_resolve": ("sessions/service.py", "terminal_session_resolve"),
    "terminal_session_read_delta": ("sessions/service.py", "terminal_session_read_delta"),
    "terminal_session_wait_delta": ("sessions/service.py", "terminal_session_wait_delta"),
    "terminal_session_state": ("sessions/service.py", "terminal_session_state"),
    "terminal_session_create": ("sessions/service.py", "terminal_session_create"),
    "terminal_session_stop": ("sessions/service.py", "terminal_session_stop"),
}


def resolve_handler(bridge, method):
    target = METHOD_HANDLERS.get(method)
    return getattr(bridge, target[1]) if target else None
