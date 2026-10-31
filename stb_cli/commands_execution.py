"""Run, input, job, wait and interrupt CLI commands."""

import json

from stb_cli.client import bridge_call
from stb_cli.command_input import decode_command, validate_command


EXECUTION_COMMANDS = {
    "job",
    "wait", "interrupt", "run",
}


def _job_action(args):
    method = "terminal_job_status"
    params = {"job_id": args.job_id}
    if args.command == "wait":
        method = "terminal_wait_job"
        params["wait_ms"] = args.seconds * 1000
    result = bridge_call(args.bridge_socket, method, params)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def handle_execution_command(args):
    if args.command not in EXECUTION_COMMANDS:
        return None
    if args.command == "run":
        text = decode_command(args.base64) if args.base64 is not None else validate_command(args.text)
        session = bridge_call(args.bridge_socket, "terminal_session_resolve", {"name": args.name})
        info = bridge_call(args.bridge_socket, "bridge_info")
        if not info.get("run_auto_request_id"):
            raise RuntimeError("请重启/升级 Bridge 加载自动请求 ID 能力；不会回退执行")
        params = dict(pane=session["pane"], text=text, wait_ms=args.wait_ms,
                      expected_duration_ms=args.expected_duration_ms, resource_class=args.resource_class)
        print(json.dumps(bridge_call(args.bridge_socket, "terminal_run", params), ensure_ascii=False))
    elif args.command in ("job", "wait"):
        _job_action(args)
    elif args.command == "interrupt":
        result = bridge_call(args.bridge_socket, "terminal_interrupt_job",
                             {"job_id": args.job_id, "wait_ms": args.seconds * 1000})
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
