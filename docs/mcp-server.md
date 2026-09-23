# 最小 MCP Server

## Codex deferred tool discovery

Codex Desktop 可能使用 `ToolSearchAlwaysDeferMcpTools`：MCP 已成功初始化，但其
工具不一定全部预先放入模型的直接工具列表。这种情况下，“当前列表未显示”
不等于 MCP 不可用，模型必须先搜索 deferred tool catalog。

项目级 routing skill 位于：

```text
/Users/sharpbai/Documents/ChatGPT/IT网管/.agents/skills/shared-terminal-bridge/SKILL.md
```

它覆盖 `shared-terminal-bridge`、`stb`、`verify33`和“托管交互终端”等路由词，
并要求模型在宣告工具不可用之前：

1. 在 `ALL_TOOLS` 搜索 `shared_terminal_bridge` 和 managed tmux 描述；
2. 调用 `terminal_session_list` 进行真实可用性检查；
3. 只有搜索无结果或实际调用返回连接/启动错误时，才报告不可用。

2026-09-20 的“检查 local-33 磁盘占用05”日志显示：MCP Server
`0.5.1` 已完成初始化，但模型未搜索 deferred tools 就误报“没有可用
工具”。该 routing skill 用于防止同类误判。

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
terminal_read_delta
terminal_wait_delta
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
terminal_submit
terminal_key
terminal_interrupt
terminal_long_run_request
terminal_long_run_approve
terminal_task_block
terminal_task_observe
terminal_task_block_execute
terminal_program_profile
terminal_session_acquire
terminal_execution_status
terminal_session_read_delta
terminal_session_wait_delta
terminal_session_state
terminal_job_list
terminal_job_status
terminal_wait_job
```

完整命令优先使用 `terminal_submit`。它在一次 Bridge 请求内完成 literal text
输入和 Enter，既少一次 MCP 往返，也避免调用方自行拼接 `terminal_type` 与
`terminal_key` 时出现转义错误。随后用 `terminal_read_delta` 获取结果。

`terminal_task_block` 只在 Bridge daemon 内建立本地计划与观察范围，不会把
`commands` 写入 pane。每条实际命令都必须另行调用 `terminal_submit`。Bridge
不注入 shell 包装脚本、marker、临时文件、TTY 设置或环境探测。文件传输和
标准输入管道必须作为可见、可审计的目标环境命令显式提交。

API v8 的 `terminal_task_block_execute` 是独立的只读 Runner，不改变上述旧接口。
它接受 1–8 个简单步骤，在本地逐步复用 `terminal_submit`、job 和 wait；每一步发送前
重新校验 lease/generation，Human Ctrl+C、交互提示、断言失败或上下文变化都会停止
后续步骤。Runner v1 禁止管道、重定向、shell 展开和未知可执行文件，并对白名单工具
的子命令做保守限制。它不会生成脚本、临时文件或目标环境控制协议。

API v9 的 `terminal_program_profile` 仅返回本地指引：可列出或读取已知
程序的 CLI/CMD/batch 能力和 TUI fallback 策略，不要求 lease，不向 pane
发送任何字节。

已知精确会话名时，`terminal_session_acquire(name)` 由 Bridge 直接解析 pane，无需
先 `terminal_session_list`。纯观察直接使用 `terminal_session_read_delta`、
`terminal_session_wait_delta` 和 `terminal_session_state`，同样不需要 lease。

`terminal_wait_delta` 把最多 30 秒的本地等待和增量读取合并为一次调用。
连续两次空增量或时间预算耗尽时返回 `BUDGET_EXHAUSTED`，模型必须停止
轮询，Bridge 不会自动 Ctrl+C。

`terminal_submit` 还会返回 `job_id`。长任务优先使用 `terminal_wait_job`，单次可在
本地等待最多 10 分钟，完成、Human Ctrl+C、交互提示或硬评估点会提前返回。
10 分钟没有结论时返回 `STRATEGY_REVIEW_REQUIRED`，模型必须比较替代方案；
只有存在可信活动证据时才继续等待。`HUMAN_DECISION_REQUIRED` 只要求向人工报告，
不授权自动中断。项目级 MCP
配置将 `tool_timeout_sec` 设为 660 秒，为十分钟等待保留协议余量。

MCP stdio adapter 并发处理工具请求，并将 Codex 的
`notifications/cancelled(requestId)` 映射到 Bridge `wait_id`。Bridge 用 Event
即时取消等待；该事件不会停止终端命令，新用户消息也不再被旧 wait 阻塞。

预计超过 120 秒或 `high_io` / `full_scan` 命令需要用户在后续消息中明确
批准。先调用 `terminal_long_run_request` 创建不执行命令的待批准请求，并将返回的
完整命令、预计耗时、资源类型和预算展示给用户后结束当前轮。用户在后续消息中回复
“批准”或“确认执行”即可，不需要复述命令。随后用 request ID 调用
`terminal_long_run_approve` 生成一次性 approval ID，再传给 `terminal_submit`。
批准与请求 ID、命令指纹、pane、generation、资源类型和预算完全绑定。

本地管理员也可以使用 `stb approvals` 查看完整请求，使用
`stb approve REQUEST_ID` 或 `stb reject REQUEST_ID` 作出决定。

每个新 Codex 任务会启动独立的 MCP server 进程。首次写入前，先调用
`terminal_session_acquire`，按托管会话名称获得该任务自己的新 generation。
人类按下 `Ctrl+C` 后，`terminal_read` 会返回 `human_override=true`，当前用户
回合必须在最多再读取一次已有输出后立即结束，不能继续写入或重新申请。
如果用户随后在同一 Codex 任务里发出新的操作请求，可以再次调用
`terminal_session_acquire` 获取新 generation。不得从终端历史复用 generation。

## Codex Turn Identity

重新授权不接受模型传入的时间戳。MCP 进程从 Codex 注入的
`CODEX_THREAD_ID` 确定当前任务。当前 Codex Desktop 版本不会把该变量继续
传给项目级 MCP 子进程，因此适配器会在进程启动时，将自身启动时间与 Codex
session JSONL 的 `session_meta.timestamp` 做最近邻匹配（最大偏差 60 秒），
绑定一次后不再改变。随后从这个已绑定 thread 的记录中读取最近一条真实
`UserMessage`，得到：

```text
(thread_id, turn_id, turn_started_at_ms)
```

`turn_started_at_ms` 是 Unix 毫秒时间，用于严格单增比较；唯一 `turn_id`
用于排除同一毫秒碰撞和同一回合重放。Bridge 将该三元组写入 Lease。
Human Override 同时记录 `revoked_at_ms`。同一任务重新申请时必须满足：

- `turn_id` 与被撤销 Lease 的授权回合不同；
- `turn_started_at_ms > revoked_at_ms`。

因此 Agent 在同一回合里等待、重试或伪造一个更晚的工具参数都不能重新
授权；只有新的用户消息被 Codex 落盘后，才会产生可接受的新授权纪元。

MCP 不直接暴露原始 `acquire_execution`，而是提供有任务生命周期约束的
`terminal_session_acquire`。它只解析带托管标记的会话，并且每个 MCP 进程对
已有 ACTIVE Lease 时拒绝重复申请；REVOKED/RELEASED 后，仅允许在后续用户
消息明确要求继续操作时申请新 generation。缺少、失效或已被物理 `Ctrl+C`
撤销的 generation 仍会在 tmux 写入前被 Bridge 拒绝。

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
