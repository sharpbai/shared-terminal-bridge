"""Execution lease, approval, job, wait, and interrupt CLI commands."""

import json

from stb_cli.client import bridge_call, find_session


EXECUTION_COMMANDS = {
    "lease", "release", "approvals", "approve", "reject", "jobs", "job",
    "watch", "wait", "waits", "cancel-wait", "interrupt",
}


def _lease(args):
    session = find_session(args.tmux_socket, args.name)
    if session is None:
        raise RuntimeError(f"不是托管会话或会话不存在：{args.name}")
    params = {"pane": session["pane"]}
    method = "acquire_execution"
    if args.command == "release":
        params["generation"] = args.generation
        method = "release_execution"
    print(json.dumps(bridge_call(args.bridge_socket, method, params), ensure_ascii=False, indent=2))


def _approvals(args):
    params = {"status": args.status} if args.status else {}
    result = bridge_call(args.bridge_socket, "terminal_long_run_requests", params)
    requests = result.get("requests", [])
    if args.json:
        print(json.dumps(requests, ensure_ascii=False, indent=2))
    elif not requests:
        print("当前没有长任务批准请求。")
    else:
        print(f"长任务批准请求：{len(requests)} 个")
        for request in requests:
            print(f"\n  请求 ID：{request['request_id']}")
            print(f"  状态：{request['status']}")
            print(f"  面板：{request['pane']}")
            print(f"  资源类型：{request['resource_class']}")
            print(
                f"  预计/空闲/总预算：{request['expected_duration_ms']} / "
                f"{request['idle_budget_ms']} / {request['total_budget_ms']} ms"
            )
            print("  完整命令：")
            print(f"    {request['command']}")
        print("\n批准：stb approve <请求ID>")
        print("拒绝：stb reject <请求ID>")


def _decide(args):
    result = bridge_call(
        args.bridge_socket,
        "terminal_long_run_decide",
        {"request_id": args.request_id, "decision": args.command},
    )
    verb = "批准" if args.command == "approve" else "拒绝"
    print(f"已{verb}长任务请求：{args.request_id}")
    print("完整命令：")
    print(result["command"])


def _jobs(args):
    params = {"state": args.state} if args.state else {}
    jobs = bridge_call(args.bridge_socket, "terminal_job_list", params).get("jobs", [])
    if args.json:
        print(json.dumps(jobs, ensure_ascii=False, indent=2))
    elif not jobs:
        print("当前没有终端任务。")
    else:
        print(f"终端任务：{len(jobs)} 个")
        for item in jobs:
            elapsed = item.get("elapsed_ms", 0) // 1000
            progress = f"，进度 {item['progress']}" if item.get("progress") else ""
            print(
                f"  {item['job_id']}  {item['state']}  "
                f"pane={item['pane']}  已运行 {elapsed}s{progress}"
            )
        print("\n详情：stb job <任务ID>")


def _job_action(args):
    method = "terminal_job_status"
    params = {"job_id": args.job_id}
    if args.command in ("watch", "wait"):
        method = "terminal_wait_job"
        params["wait_ms"] = args.seconds * 1000
    result = bridge_call(args.bridge_socket, method, params)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def handle_execution_command(args):
    if args.command not in EXECUTION_COMMANDS:
        return None
    if args.command in ("lease", "release"):
        _lease(args)
    elif args.command == "approvals":
        _approvals(args)
    elif args.command in ("approve", "reject"):
        _decide(args)
    elif args.command == "jobs":
        _jobs(args)
    elif args.command in ("job", "watch", "wait"):
        _job_action(args)
    elif args.command == "waits":
        result = bridge_call(args.bridge_socket, "terminal_wait_list")
        print(json.dumps(result.get("waits", []), ensure_ascii=False, indent=2))
    elif args.command == "cancel-wait":
        result = bridge_call(
            args.bridge_socket, "terminal_cancel_wait", {"wait_id": args.wait_id}
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "interrupt":
        job = bridge_call(
            args.bridge_socket, "terminal_job_status", {"job_id": args.job_id}
        )
        result = bridge_call(
            args.bridge_socket,
            "terminal_interrupt",
            {"pane": job["pane"], "generation": job["generation"]},
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
