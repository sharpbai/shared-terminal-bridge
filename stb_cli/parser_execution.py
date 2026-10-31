"""Argument definitions for execution-control commands."""


def add_execution_parsers(subparsers, configure_help):
    run = configure_help(subparsers.add_parser("run", help="执行一条命令并等待结果",
        description="执行一条命令并等待结果；输入方式与安全规则见 stb discover --json。"))
    run.add_argument("name", help="托管会话名称")
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="直接传入单行命令；注意启动 Shell 的转义")
    source.add_argument("--base64", metavar="PAYLOAD", help="UTF-8 原文的标准 Base64；用工具生成并回验，不折行")
    run.add_argument("--wait-ms", type=int, default=60000)
    run.add_argument("--expected-duration-ms", type=int, default=10000)
    run.add_argument("--resource-class", choices=("normal", "high_io", "full_scan"), default="normal")

    job = configure_help(subparsers.add_parser("job", help="查看一个终端任务的状态和增量输出"))
    job.add_argument("job_id", metavar="任务ID", help="例如 job_a1b2c3d4e5f6")

    for command, help_text in (("wait", "本地等待终端任务状态变化"),):
        wait_parser = configure_help(subparsers.add_parser(command, help=help_text))
        wait_parser.add_argument("job_id", metavar="任务ID", help="例如 job_a1b2c3d4e5f6")
        wait_parser.add_argument(
            "--seconds", type=int, default=60, metavar="秒", help="最长等待秒数（1-600，默认 60）"
        )

    interrupt = configure_help(subparsers.add_parser("interrupt", help="向终端任务发送 Agent Ctrl+C"))
    interrupt.add_argument("job_id", metavar="任务ID", help="例如 job_a1b2c3d4e5f6")
    interrupt.add_argument("--seconds", type=int, default=60, help="等待提示符返回，默认 60 秒")


__all__ = ["add_execution_parsers"]
