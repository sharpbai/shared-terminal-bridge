"""Offline CLI discovery and copyable MCP registration guidance."""

import json
import shlex
import sys

from stb_cli.config import PROJECT_ROOT
from bridge.agent_instructions import INSTRUCTIONS


def discovery(bridge_socket, include_setup=False):
    argv = [sys.executable, str(PROJECT_ROOT / "mcp_server/server.py"),
            "--bridge-socket", str(bridge_socket), "--enable-actions",
            "--enable-session-management"]
    info = {
        "name": "shared-terminal-bridge",
        "discovery_version": 1,
        "discovery_only": True,
        "requires_skill": False,
        "instructions": INSTRUCTIONS,
        "agent_entrypoint": "通过 discover 获取执行与安全规则；MCP 使用 instructions 和 tools/list",
        "mcp": {
            "transport": "base64", "command": argv[0], "args": argv[1:],
            "codex_global_add": shlex.join([
                "codex", "mcp", "add", "shared-terminal-bridge", "--", *argv]),
            "tool_timeout_sec": 660,
            "timeout_guidance": "长等待请在全局 MCP 服务配置中设置 tool_timeout_sec = 660。",
            "activation": "注册后重连 MCP 或新建任务；终端操作需要 Bridge daemon 正常运行。",
        },
        "workflow": "已知会话名时首次用 bootstrap 获取规则和实际终端；它已包含 context，无需重复观察。已接入时用 context 确认环境再 run；结果完整时不额外读取，人工操作、环境变化或状态不明时再 context。Core 生成 ID，后续使用 job ID，超时不重提。MCP 使用对应的读取工具和 terminal_run。",
        "commands": {
            "bootstrap": "首次接入：stb bootstrap 会话名；返回规则、终端上下文和模板，只读不执行。",
            "list": "不知道会话名时：stb list。",
            "info": "查看面板或找回当前任务 ID：stb info 会话名。",
            "context": "执行前确认画面与实际环境，或人工操作后刷新：stb context 会话名 --lines 40。",
            "run": "提交命令：stb run 会话名 --text '命令正文' 或 --base64 PAYLOAD；输入规则见 cli_execution。",
            "job": "立即查询已有任务：stb job JOB_ID。",
            "wait": "继续观察已有任务：stb wait JOB_ID --seconds 60；--seconds 可设 1–600 秒，默认 60，可能提前返回；超时不停止命令，不重交。",
            "interrupt": "中断并等待提示符返回：stb interrupt JOB_ID。",
        },
        "cli_execution": "执行命令使用 stb run 会话名，并选择一种输入参数：命令不超过 200 个 Unicode 字符，且不含单引号、双引号、反斜杠、反引号或 $ 时，使用 stb run 会话名 --text '命令正文'；其他情况调用本机编码工具按 UTF-8 生成无折行标准 Base64 并解码回验，随后 stb run 会话名 --base64 PAYLOAD。禁止手算 Base64，不添加首尾换行。--text 与 --base64 PAYLOAD 二选一，都是 run 的参数。这是入口选择规则，不是终端长度限制，不影响 MCP 直接传 text；超时不重放。",
        "human_commands": ["stb list", "stb-manage enter SESSION", "stb-manage daemon status"],
    }
    if not include_setup:
        info.pop("mcp")
        info.pop("human_commands")
    return info


def handle_discovery_command(args):
    if args.command not in {"discover", "mcp"}:
        return None
    info = discovery(args.bridge_socket, include_setup=args.command == "mcp")
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        if args.command == "discover":
            print("STB Agent：先按会话名观察，再 run；后续使用返回的 job ID。")
            print(info["workflow"])
            for guidance in info["commands"].values():
                print(guidance)
            print(info["cli_execution"])
            print(info["instructions"])
            return 0
        print("STB 自发现 / MCP 接入（只读说明，无需 skill）")
        print("Agent：连接 MCP 后，按 instructions 和工具 schema 使用；无需预读仓库文档。")
        print("Codex 全局注册命令（已有同名配置时先检查，勿覆盖定制参数）：")
        print(info["mcp"]["codex_global_add"])
        print("长等待：在全局配置 [mcp_servers.shared-terminal-bridge] 设置 tool_timeout_sec = 660。")
        print("注册后重新连接 MCP 或新建任务；终端操作需要 Bridge daemon 在线。")
        print("人工入口：stb list / stb-manage enter <会话名> / stb-manage daemon status")
        print("机器可读说明：stb discover --json；实际能力以运行中的 MCP schema 为准。")
        print("安全：执行期间人工 Ctrl+C 停止旧执行链；高风险仍需批准，不绕过 STB。")
    return 0
