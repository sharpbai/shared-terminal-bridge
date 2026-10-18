"""Offline CLI discovery and copyable MCP registration guidance."""

import json
import shlex
import sys

from stb_cli.config import PROJECT_ROOT


def discovery(bridge_socket):
    argv = [sys.executable, str(PROJECT_ROOT / "mcp_server/server.py"),
            "--bridge-socket", str(bridge_socket), "--enable-actions",
            "--enable-session-management"]
    return {
        "name": "shared-terminal-bridge",
        "discovery_version": 1,
        "discovery_only": True,
        "requires_skill": False,
        "agent_entrypoint": "MCP instructions + tools/list",
        "mcp": {
            "transport": "stdio", "command": argv[0], "args": argv[1:],
            "codex_global_add": shlex.join([
                "codex", "mcp", "add", "shared-terminal-bridge", "--", *argv]),
            "tool_timeout_sec": 660,
            "timeout_guidance": "Set tool_timeout_sec = 660 in the global MCP server configuration for long waits.",
            "activation": "Reconnect MCP or open a new task after registration. Bridge daemon must be running for terminal operations.",
        },
        "workflow": "Observe the exact named session; use terminal_run with a unique request_id. Continue using returned job IDs. Read runtime schemas for parameters.",
        "safety": "Authorization stays inside Bridge. Human Ctrl+C during execution stops the old chain; never replay it automatically. High-risk operations require approval. Do not bypass STB using independent SSH or hidden shells.",
        "human_commands": ["stb list", "stb enter SESSION", "stb daemon status"],
    }


def handle_discovery_command(args):
    if args.command not in {"discover", "mcp"}:
        return None
    info = discovery(args.bridge_socket)
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        print("STB 自发现 / MCP 接入（只读说明，无需 skill）")
        print("Agent：连接 MCP 后，按 instructions 和工具 schema 使用；无需预读仓库文档。")
        print("Codex 全局注册命令（已有同名配置时先检查，勿覆盖定制参数）：")
        print(info["mcp"]["codex_global_add"])
        print("长等待：在全局配置 [mcp_servers.shared-terminal-bridge] 设置 tool_timeout_sec = 660。")
        print("注册后重新连接 MCP 或新建任务；终端操作需要 Bridge daemon 在线。")
        print("人工入口：stb list / stb enter <会话名> / stb daemon status")
        print("机器可读说明：stb discover --json；实际能力以运行中的 MCP schema 为准。")
        print("安全：执行期间人工 Ctrl+C 停止旧执行链；高风险仍需批准，不绕过 STB。")
    return 0
