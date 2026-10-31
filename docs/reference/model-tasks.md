# 模型任务接口：只传任务，不管理授权计数

这是一次不保留旧模型接口的调整。Core 内部仍保留执行授权、单增计数、事件顺序、严格校验与审计；只是模型不再申请、读取或传递这些内部状态。

## 默认调用

已知会话首次用 `stb bootstrap 会话名 --lines 20` 一次取得规则、实际终端上下文和模板，不再追加 discover/context。已经接入时用 `stb context 会话名 --lines 20` 确认环境再 run；人工操作、环境变化或状态不明时再刷新，结果完整时不补读。context 只返回会话、状态和有界终端画面，不授权、不执行；info 只查看面板和任务 ID。未知会话先 list。命令默认返回 JSON。

仅需离线查看规则时执行 `stb discover --json`，它返回完整执行/安全 instructions 和 200 字符输入方式选择规则；bootstrap 已含这些内容，不再重复发现。默认帮助及 run 帮助不重复该规则。instructions 与 MCP 同源，唯一维护位置是 `bridge/agent_instructions.py`。

通用 instructions 不含任何 RDC 专属内容；传输、PID 和旁路策略由 STB-RDC 的 bootstrap 自行说明，不进入 STB 核心提示。

| 意图 | Codex MCP | STB-RDC 操作 |
| --- | --- | --- |
| 执行并等待 | terminal_run | run |
| 继续观察 | terminal_wait_job / terminal_job_status | wait / job |
| Agent 中断该任务 | terminal_interrupt_job | interrupt |

run 传 pane（CLI/RDC 可传会话名）、单行命令、耗时/资源类别和可选观察窗口。未提供 request_id 时由 Core 自动生成；模型无需生成。返回 job ID、状态和有界结果。内部显式同 ID 重试仍去重，但新 run 不代表重试；超时先读取原进程或查询 job，不能盲目重交。interrupt 只传 job ID。风险确认由模型在对话中取得，不再有审批 API 或凭证。

## CLI 文本与 Base64

简单命令用 `stb run SESSION --text 'df -h /'`；长或易转义命令用 `--base64 PAYLOAD`。选择标准：命令不超过 200 个 Unicode 字符且不含引号、反斜杠、反引号或美元符时优先 --text；否则 --base64。用可靠工具按 UTF-8 编码为无折行标准 Base64 并解码回验，不添加首尾换行，不手算。

input CLI 与 terminal_input_job MCP 工具已移除，模型仅提交 CLI 任务；遇到交互提示或 TUI 交人工处理，不用新 run 伪装回复。stdio/stdin 参数已删除。解码内容仍须非空、单行、无控制字符且最多 65536 UTF-8 字节。MCP 直接传原文 text，无需编码；Base64 仅在 CLI 解码后交给 Core。RDC 同样一次启动提交并收集原 PID，不发送 stdin。

## 已移除的模型契约

不再发布 acquire、submit、type、key、基于 pane/计数的 interrupt 或带授权参数的 Task Block 工具。RDC 不再接受 lease/submit 或原有审批传参；CLI lease/send 移除。旧调用报错，不偷偷补参数，也不降级兼容。CLI 已删除 lease/release/watch，STB-RDC 已删除 serve-stdio；不保留 stdio 参数。

既有只读观察、session 管理和程序 profile 保留。需要多项独立轻量查询时可提交一条明确、可见的安全命令；不自动拆分多行，不注入远端脚本。

## Core 强制的安全边界

- 新 run 按本地接收顺序自动授权，包括 daemon 重启后的新调用；不需要模型先调用 lease。
- 同一逻辑 ID 重试只观察原任务，不重新授权或重复输入。崩溃只剩预留记录时 fail closed。
- 有效人工 Ctrl+C 取消执行中的旧链；同一调用内部不能恢复。之后的新明确 run 可以继续，高风险仍单独批准。
- interrupt 从原 job 解析内部权限，旧 job 不能影响新任务；底层内部输入能力不再向 Agent 暴露。
- 取消 wait 仅取消观察，不发送 Ctrl+C、不重交命令。
- high_io/full_scan 仅作为资源监控标签，不触发强制审批；模型仍须对高风险操作通过对话取得人工同意。
- 只读看历史不需要授权，不因其他任务占用而抢占终端。

## 加载与验证

Core 能力标志为 `model_tasks=job-authority-v2`、`run_auto_request_id=true`。升级后重启 Bridge；Codex 已连接的 MCP 需重新连接刷新 schema。STB-RDC bootstrap 返回当前引导，不进行版本协商。

回归包括 MCP 无内部字段、RDC 拒绝旧参数、CLI/MCP 输入入口拒绝、旧 job 隔离、资源类别无审批门槛、重启后自动授权，以及真实 MCP stdio → socket → 隔离 tmux 的人工事件检查。实现入口为 `bridge/execution/run.py`、`job_actions.py` 和 `bridge/protocol/model_view.py`。
