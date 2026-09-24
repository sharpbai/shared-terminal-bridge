"""Argument definitions for execution-control commands."""


def add_execution_parsers(subparsers, configure_help):
    lease = configure_help(subparsers.add_parser("lease", help="明确授予会话面板的执行租约"))
    lease.add_argument("name", metavar="名称", help="会话名称")

    release = configure_help(subparsers.add_parser("release", help="主动释放执行租约"))
    release.add_argument("name", metavar="名称", help="会话名称")
    release.add_argument("generation", type=int, metavar="代次", help="lease 返回的 generation")

    approvals = configure_help(subparsers.add_parser("approvals", help="列出长任务待批准请求"))
    approvals.add_argument(
        "--status",
        choices=("PENDING", "APPROVED", "REJECTED", "CONSUMED", "EXPIRED"),
        metavar="状态",
        help="按状态筛选（默认显示全部）",
    )
    approvals.add_argument("--json", action="store_true", help="输出机器可读的 JSON")

    for command, help_text in (("approve", "批准一个长任务请求"), ("reject", "拒绝一个长任务请求")):
        item = configure_help(subparsers.add_parser(command, help=help_text))
        item.add_argument("request_id", metavar="请求ID", help="例如 lr_a1b2c3d4e5f6")

    jobs = configure_help(subparsers.add_parser("jobs", help="列出 Bridge 监测的终端任务"))
    jobs.add_argument("--json", action="store_true", help="输出机器可读的 JSON")
    jobs.add_argument(
        "--state",
        choices=("RUNNING", "COMPLETED", "INTERRUPTED_BY_HUMAN", "NEEDS_ATTENTION", "HUMAN_DECISION_REQUIRED"),
        metavar="状态",
        help="按任务状态筛选",
    )

    job = configure_help(subparsers.add_parser("job", help="查看一个终端任务的状态和增量输出"))
    job.add_argument("job_id", metavar="任务ID", help="例如 job_a1b2c3d4e5f6")

    for command, help_text in (("watch", "本地等待终端任务状态变化"), ("wait", "等待终端任务（watch 的同义命令）")):
        wait_parser = configure_help(subparsers.add_parser(command, help=help_text))
        wait_parser.add_argument("job_id", metavar="任务ID", help="例如 job_a1b2c3d4e5f6")
        wait_parser.add_argument(
            "--seconds", type=int, default=600, metavar="秒", help="最长等待秒数（1-600，默认 600）"
        )

    configure_help(subparsers.add_parser("waits", help="列出当前活动的等待请求"))

    cancel_wait = configure_help(subparsers.add_parser("cancel-wait", help="取消模型等待但不停止终端命令"))
    cancel_wait.add_argument("wait_id", metavar="等待ID", help="例如 wait_a1b2c3d4e5f6")

    interrupt = configure_help(subparsers.add_parser("interrupt", help="向终端任务发送 Agent Ctrl+C"))
    interrupt.add_argument("job_id", metavar="任务ID", help="例如 job_a1b2c3d4e5f6")


__all__ = ["add_execution_parsers"]
