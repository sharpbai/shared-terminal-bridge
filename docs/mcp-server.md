# 最小 MCP Server

## 边界

`mcp_server/server.py` 是 Local Bridge 的 stdio MCP 适配层。它不直接调用
tmux，而是把 MCP tool 请求转发给 Bridge 的 Unix control socket。Pane ACL、
execution lease、generation 和 Human Override 仍由 Bridge 强制。

适配器无第三方 Python 依赖，同时支持：

- MCP `2026-07-28`：`server/discover` 和每请求 `_meta`。
- MCP `2025-11-25`：`initialize` / `notifications/initialized`。
- stdio 的换行分隔 JSON-RPC framing。

## 默认工具

MCP server 默认只注册 Observation：

```text
terminal_list
get_active_pane
terminal_read
terminal_state
```

这些工具不能改变 tmux pane，且内容读取仍受 Bridge `--allow-pane` ACL
约束。

## 启动

先启动 Bridge daemon，仅授权明确 pane：

```bash
python3 bridge/local_bridge.py serve \
  --tmux-socket default \
  --allow-pane %3
```

然后 MCP host 以以下 command/args 启动 stdio server：

```json
{
  "command": "python3",
  "args": [
    "/Users/sharpbai/Documents/ChatGPT/IT网管/shared-terminal-bridge/mcp_server/server.py",
    "--bridge-socket",
    "/tmp/shared-terminal-bridge.sock"
  ]
}
```

stdio 是协议通道；服务器不得向 stdout 打印日志。

## Action 模式

Action 必须在 MCP server 启动时显式开启：

```bash
python3 mcp_server/server.py \
  --bridge-socket /tmp/shared-terminal-bridge.sock \
  --enable-actions \
  --enable-session-management
```

此时额外注册：

```text
terminal_type
terminal_key
terminal_interrupt
```

MCP 层故意不暴露 `acquire_execution`。调用方无法通过 MCP 给自己授权；
generation 必须由人类明确授权的本地控制流程预先创建。即使 Action 工具
可见，缺少、失效或已被物理 `Ctrl+C` 撤销的 generation 仍会在 tmux 写入前
被 Bridge 拒绝。

`--enable-session-management` 额外注册托管 session 的 list/create/stop 工具。
完整用法见 [托管 tmux Session 与 stb 快捷命令](managed-sessions.md)。

人类或本地授权控制器可通过非 MCP 通道创建 lease：

```bash
python3 bridge/local_bridge.py call acquire_execution \
  --params '{"pane":"%3"}'
```

返回的 `generation` 才能传给 MCP Action tool。主动释放时同样使用本地控制
通道：

```bash
python3 bridge/local_bridge.py call release_execution \
  --params '{"pane":"%3","generation":1}'
```

## 错误语义

- JSON-RPC / schema 错误使用 MCP JSON-RPC error。
- Bridge 业务拒绝使用 tool result：`isError=true`。
- tool result 同时返回 JSON text content 和 `structuredContent`。
- Bridge socket 不可达时返回 `BRIDGE_UNAVAILABLE`，不回退到直接 tmux 操作。

## 验证

```bash
python3 -m unittest tests/test_mcp_server.py
./poc/mcp_end_to_end.py
```

端到端测试同时验证：

- 默认只读工具目录和 Action 默认拒绝。
- 显式 Action 模式下的 leased `terminal_type` / `terminal_key` 真实到达 pane。
- Agent `C-c` 不撤销 lease。
- Human Event 撤销 lease 后 stale MCP 写入被拒绝且不进入 pane。
- READ/STATE/TYPE/KEY/INTERRUPT/REVOKE/DENY 审计链完整。
