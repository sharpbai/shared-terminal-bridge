"""Read-only named-session onboarding and context refresh for Agent CLI."""
import json
import shlex

from stb_cli.client import bridge_call
from stb_cli.discovery import discovery


def read_context(args):
    session = bridge_call(args.bridge_socket, "terminal_session_resolve", {"name": args.name})
    pane = session["pane"]
    state = bridge_call(args.bridge_socket, "terminal_state", {"pane": pane})
    terminal = bridge_call(args.bridge_socket, "terminal_read", {"pane": pane, "lines": args.lines})
    return dict(session=session, terminal_state=state, context=terminal)


def bootstrap(args):
    info = bridge_call(args.bridge_socket, "bridge_info")
    ready = (info.get("run_auto_request_id") is True
             and info.get("terminal_run") == "receipt-scoped-run-v1"
             and info.get("model_tasks") == "job-authority-v2")
    result = read_context(args)
    # Fresh onboarding does not carry the previous lease's interrupt history.
    # Leave ordinary context refresh and authoritative job results unchanged.
    result["context"].pop("execution", None)
    rules = discovery(args.bridge_socket)
    session = shlex.quote(args.name)
    templates = dict(context=f"stb context {session} --lines 40", info=f"stb info {session}",
                     job="stb job JOB_ID", wait="stb wait JOB_ID --seconds 60",
                     interrupt="stb interrupt JOB_ID")
    if ready:
        templates["run"] = {"direct": f"stb run {session} --text '命令正文'",
                            "base64": f"stb run {session} --base64-chunks CHUNK1 ... DIGEST16",
                            "encoding": "用本机工具按 UTF-8 生成标准 Base64 并解码回验，不折行、不添加首尾换行，禁止手算。长输入按 UTF-8 原文每 72 字节独立编码，末尾附原始字节 SHA-256 前 16 个小写十六进制字符，数组元素以空格分隔传给 --base64-chunks。",
                            "python_example": (
                                'import base64, hashlib, shlex\n'
                                'text = "printf \'%s\\\\n\' \'A read-only example for demonstrating short Base64 segments\'"\n'
                                'data = text.encode("utf-8")\n'
                                'parts = [base64.b64encode(data[i:i+72]).decode("ascii") for i in range(0, len(data), 72)]\n'
                                'parts.append(hashlib.sha256(data).hexdigest()[:16])\n'
                                f"print(shlex.join(['stb', 'run', {args.name!r}, '--base64-chunks', *parts]))"
                            ),
                            "segmented_example": f"stb run {session} --base64-chunks ZGYgLWggLw== 42197cbf85324c85"}
    result.update(
        protocol_revision="stb-cli-bootstrap-v1",
        bridge={key: info.get(key) for key in ("name", "version", "api_version")},
        instructions=rules["instructions"], cli_execution=rules["cli_execution"],
        commands=rules["commands"], workflow=rules["workflow"], request_templates=templates,
        bootstrap_result=dict(ready=ready, discovery_only=True, task_executed=False,
                              repeat_bootstrap="仅在环境变化或兼容错误后重新接入；刷新终端使用 context。",
                              next_step=("已完成发现和终端观察，无需再 discover 或重复 context；确认实际环境后执行 run。"
                                         if ready else "当前 Core 缺少能力，暂停执行；不要回退旧接口。")))
    return result


def handle_context_command(args):
    if args.command not in {"context", "bootstrap"}:
        return None
    result = bootstrap(args) if args.command == "bootstrap" else read_context(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
