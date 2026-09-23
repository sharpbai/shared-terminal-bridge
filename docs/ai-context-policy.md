# AI Context Policy v0.2 与 Terminal Task Block

## 目标

完整 tmux scrollback 继续作为本地事实来源，但不再默认进入模型上下文。Bridge
先执行确定性的 admission control；会话自身的语义压缩仅作为最后一道保险。

## 数据分层

1. **Raw pane history**：由 tmux 保存，Bridge 不把它自动复制进对话。
2. **Observation cursor**：Bridge 保存上一次 snapshot，并只返回 suffix delta。
3. **Deterministic filter**：清理 ANSI/control、内部 task marker 和命令回显，折叠
   连续重复行。
4. **Context budget**：默认最多 200 行、16 KiB，硬上限 1000 行、64 KiB；
   超限时保留开头和最新输出，并明确报告省略量。
5. **Control events**：Human Override、lease state、exit code 不经过自然语言摘要，
   始终作为结构化字段返回。

## `terminal_read_delta`

第一次调用不传 `cursor`，返回当前有界 pane snapshot 和一个 opaque cursor。后续调用
必须传最近一次返回的 cursor。Bridge 使用 scrollback suffix overlap 计算新增内容，调用方
不能自行构造 offset。

```json
{
  "pane": "%3",
  "cursor": "opaque-previous-cursor",
  "max_bytes": 16384,
  "max_lines": 200
}
```

响应包含：

- `content`：允许进入模型上下文的文本；
- `no_change`：没有新增 pane 内容；
- `raw_delta_lines` / `returned_lines`；
- `omitted_lines` / `omitted_bytes`；
- `repeated_groups`、`dropped_echoes`（`dropped_markers` 仅为 v0.5 兼容字段，固定为 0）；
- `execution.human_override` 和 lease snapshot。

cursor 属于进程内短期状态，daemon 重启后旧 cursor fail closed。tmux 自身仍保留原始
scrollback，可从新 cursor 重新建立观察基线。

观察 API 不要求 execution lease。即使 pane 已有 `ACTIVE` generation，也可同时
执行 `terminal_read_delta`、`terminal_read` 和 `terminal_state`。`ACTIVE` 只表示
Agent 写权归属，不表示 tmux 或历史被独占。

tmux 鼠标滚屏/copy-mode 是 client 本地视图：pane 前台进程、新输出和经过
lease 的 Agent 写入仍可继续。人和 Agent 不应同时向同一 pane 键入普通命令；
人类 `Ctrl+C` 仍作为最高优先级 Human Override。

## `terminal_task_block`

一个 task block 是 Bridge daemon 内的本地任务范围，用于记录计划的步骤数、
generation 和增量观察起点。它不执行命令：

```json
{
  "pane": "%3",
  "generation": 7,
  "commands": ["df -h", "df -i"],
  "stop_on_error": true
}
```

Bridge 校验 lease，捕获当前 pane 快照并立即返回 `block_id`。它不向 pane
发送文本或按键，不创建文件，不改变 TTY 状态，也不假设 pane 中运行 shell。
列出的每条命令仍必须由调用方分别、显式调用 `terminal_submit`，并在步骤之间
用 `terminal_read_delta` 或 `terminal_task_observe` 观察结果。

`terminal_task_observe` 从 task block 上次本地快照开始返回经 AI Context Policy
裁剪的增量输出：

```json
{
  "block_id": "opaque-block-id",
  "max_bytes": 16384,
  "max_lines": 200
}
```

状态为 `ACTIVE`、`INACTIVE` 或 `INTERRUPTED`。Bridge 不推测 shell prompt、退出码或
任务完成，因此 `exit_code` 始终为 `null`。真人 Ctrl+C 会正常送达前台进程、
撤销 generation，并使 block 报告 `INTERRUPTED`；调用方必须停止本轮后续操作。

### API v8：只读 `terminal_task_block_execute`

原有 `terminal_task_block` 的“只记录、不执行”语义保持不变。需要压缩确定性只读
步骤的模型往返时，调用独立的 `terminal_task_block_execute`：

- 一块最多 8 步、总运行预算最多 120 秒；
- Runner 位于本地 daemon，不向目标环境传输脚本；
- 每一步仍产生独立、可查询、可审计的 terminal job；
- 每一步发送前重新校验 pane、lease、generation 和 Human Override；
- 支持 `contains`、`not_contains`、`regex` 三种确定性断言；
- 返回每步最多 2 KiB 摘要和 `job://` 输出引用；
- Human Ctrl+C、交互提示、job 非正常完成或断言失败时停止；
- v1 只允许保守白名单内的单个只读命令，禁止 shell 控制符、重定向和展开。

Runner 不判断业务语义。需要依据输出选择路径、需要审批或涉及修改时，仍应回到
模型或使用单步 `terminal_submit`。

### API v9：程序能力画像

`terminal_program_profile` 仅返回 Bridge 本地的已知能力指引，不读写 pane。
全屏程序按“官方 CLI/CMD/batch → 人类辅助 TUI → Agent 受限 TUI”选路。
画像不代表目标机安装版本必然支持，必须先用安全版本探测确认。

## 明确边界

- v0.2 的增量算法基于 tmux snapshot suffix overlap，不是字节级 PTY journal。
- daemon 重启会丢失 cursor 和运行中 block metadata，但 lease 已按既有规则撤销。
- task block 只是本地元数据；命令风险与每次写入仍由正常授权链路处理。
- Bridge 不在执行环境注入包装脚本、临时文件、marker 或环境探测。
- 文件传输、标准输入管道或其他环境相关操作必须是显式的目标环境命令。
- 不使用 LLM 对 terminal output 做第一层过滤，确保预算和控制事件不可被提示词影响。

## 本地等待与长任务预算

`terminal_wait_delta` 只在 Bridge 主机轮询 tmux 快照，不向 pane 发送内容。
默认单次等待 10 秒、无变化预算 30 秒、总预算 60 秒；连续两次空增量
返回 `BUDGET_EXHAUSTED`，调用方必须停止模型轮询。Bridge 不会因预算耗尽
而自动发送 Ctrl+C。

预计超过 120 秒或标记为 `high_io` / `full_scan` 的命令必须先通过
`terminal_long_run_request` 建立不执行命令的待批准请求。模型展示完整命令、
预计耗时、资源类型和时间预算后结束当前轮；用户在后续消息中回复普通的
“批准”或“确认执行”即可。Bridge 以 request ID、可信 task/turn 顺序和命令
SHA-256 绑定批准，不要求用户复述命令。`terminal_long_run_approve` 生成绑定
新 generation 的一次性 approval ID，且只能由一次 `terminal_submit` 消费。

待批准请求也可通过 `stb approvals` 查看，并由本机管理员用 `stb approve` 或
`stb reject` 处理。管理入口不会向目标 pane 注入提示或控制数据。

等待结果只能报告 `CHANGED`、`QUIET`、`BUDGET_EXHAUSTED` 或 `INTERRUPTED`；
不推测命令是否完成。仅 `human_override=true` 可表述为真人 Ctrl+C；Agent 中断
返回 `interrupt_source=agent` 和独立 `interrupt_id`。

## 长任务 Job 等待

`terminal_submit` 为每次显式命令返回 `job_id`。`terminal_wait_job` 默认通过
一次调用在 Bridge 本地等待最多 10 分钟，期间不按分钟重复调用模型；命令完成、Human Ctrl+C、出现
密码/确认提示或到达人工决策点时立即返回。10 分钟仍无结论返回
`STRATEGY_REVIEW_REQUIRED`，调用方必须比较继续等待与替代方案；只有存在可信、
有意义的活动证据时才继续下一段等待。

完成判定不向目标环境注入 marker 或 wrapper，而是结合提交前提示符、提示符回归、
1.5 秒稳定期、tmux 增量与结构化 Human Override。它是启发式判定，因此返回
`completion_confidence`；明显超过合理预期时进入 `HUMAN_DECISION_REQUIRED`，
绝不自动发送 Ctrl+C。人工决策点为 `max(预计时间 × 3, 20 分钟)`。

MCP adapter 并发处理 stdio 请求。每次等待分配独立 `wait_id`；Codex 发出
`notifications/cancelled(requestId)` 时，adapter 通过独立 Unix socket 调用
`terminal_cancel_wait`，Bridge 直接设置对应 Event 唤醒等待线程。取消等待返回
`WAIT_CANCELLED`，不会改变 job 状态，也不会向 pane 发送 Ctrl+C。后续用户消息
可以越过旧 wait，立即查询或中断 job。

wait 和普通 status 默认只返回状态、耗时与最近证据行，不回传完整 pane 历史。
job 完成时 wait 同时返回由命令回显锚定的、有界 `output_excerpt`，正常路径无需
追加 status 调用。只有显式诊断调用 `terminal_job_status(include_output=true)` 才返回
更大的受预算约束 observation。

若提交时 tmux 前台命令是 `ssh`、`mosh` 或 `telnet`，而等待期间前台命令发生
变化，Bridge 立即返回 `NEEDS_ATTENTION/session_context_changed`。这用于识别
Broken pipe 等远程上下文退出，避免继续等满 10 分钟。

独立、轻量、只读的探测应组合为一条可见命令，以减少模型往返；修改操作、存在
依赖关系的步骤及修改后的验证保持独立。性能回归目标是常规命令使用
`submit + wait` 两次 MCP 调用完成，不再追加 status。

## 持久交互历史

Bridge 将租约、审批、显式提交、job 状态、Human/Agent 中断及有界 job 输出摘要
追加到 `~/.local/state/shared-terminal-bridge/history.jsonl`。文件权限固定为 0600，
daemon 重启后仍保留。普通 `terminal_type` 只记录字节数；密码输入不会落盘，命令中
明显的 password/token/secret 赋值会整体脱敏。

可通过 `terminal_history` 或以下命令查询：

```bash
stb history verify33 --limit 100
stb history verify33 --action SUBMIT --json
```

未知命令不再从任意百分号推断进度。`progress` 默认为 null，仅保留有界的
`last_evidence_lines`、`last_meaningful_activity_at` 和提示符状态；未来只有带证据的
命令专用解析器可以填写结构化进度。

daemon 会在完成、人工中断、需要输入或需要重新评估时发送 macOS 本地通知。
`stb jobs`、`stb job` 和 `stb watch` 提供不经过模型的人工管理入口。

## MCP 与 daemon 版本协商

Bridge 提供 `bridge_info`，返回运行中进程的 `version`、`api_version` 和 methods。
MCP 在 discovery/tool listing 时读取这一信息：

- API v2 及以上才发布 `terminal_read_delta`、`terminal_task_block` 和
  `terminal_task_observe`；
- API v3 及以上才发布本地 wait、长任务批准和按会话名观察工具；
- API v4 及以上才发布结构化长任务待批准请求；
- API v5 及以上发布终端 job 状态，API v6 及以上发布可事件取消的本地等待工具；
- API v7 及以上发布持久历史，API v8 及以上发布只读 TaskBlockRunner，API v9 及以上发布程序能力画像；
- 旧 daemon 不认识 `bridge_info` 时隐藏上述工具，并报告
  `bridgeCompatibility.status=restart_required`；
- 客户端若缓存了旧工具目录并继续调用，MCP 返回 `BRIDGE_RESTART_REQUIRED`，不再
  暴露含义模糊的 `METHOD_NOT_FOUND`。
