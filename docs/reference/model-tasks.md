# 模型任务接口：只传任务，不管理授权计数

这是一次不保留旧模型接口的调整。Core 内部仍保留执行授权、单增计数、事件顺序、严格校验与审计；只是模型不再申请、读取或传递这些内部状态。

## 默认调用

| 意图 | Codex MCP | STB-RDC JSON op |
| --- | --- | --- |
| 执行并等待 | terminal_run | run |
| 继续观察 | terminal_wait_job / terminal_job_status | wait / job |
| 回答执行中的交互 | terminal_input_job | input |
| Agent 中断该任务 | terminal_interrupt_job | interrupt |
| 批准已展示的风险请求 | terminal_approve_request | approve |

run 传 pane（RDC 可传 session）、唯一逻辑请求 ID、单行命令、耗时/资源类别和可选观察窗口。返回 job ID、状态和有界结果。input 传 job ID、唯一输入请求 ID，以及 text 或 key 二选一；interrupt 只传 job ID。approve 只传审批请求 ID，不自动执行。

默认响应和错误会隐藏内部授权元数据，但不改写命令和输出字符串。raw Core socket、人工管理 CLI 与审计属于内部诊断面，不是模型契约。

## 已移除的模型契约

不再发布 acquire、submit、type、key、基于 pane/计数的 interrupt 或带授权参数的 Task Block 工具。RDC 不再接受 lease/submit 或原有审批传参；CLI lease/send 移除。旧调用报错，不偷偷补参数，也不降级兼容。

既有只读观察、session 管理和程序 profile 保留。需要多项独立轻量查询时可提交一条明确、可见的安全命令；不自动拆分多行，不注入远端脚本。

## Core 强制的安全边界

- 新 run 按本地接收顺序自动授权，包括 daemon 重启后的新调用；不需要模型先调用 lease。
- 同一逻辑 ID 重试只观察原任务，不重新授权或重复输入。崩溃只剩预留记录时 fail closed。
- 有效人工 Ctrl+C 取消执行中的旧链；同一调用内部不能恢复。之后的新明确 run 可以继续，高风险仍单独批准。
- input/interrupt 从原 job 解析内部权限；旧 job 不能影响新的任务。输入重试同样去重。
- 取消 wait 仅取消观察，不发送 Ctrl+C、不重交命令。
- high_io/full_scan 审批校验不放宽：仍要求可信后续人工批准或本地明确决定。Codex 宿主身份由服务端读取，不是模型参数；RDC 不伪造身份。
- 只读看历史不需要授权，不因其他任务占用而抢占终端。

## 加载与验证

新 Core 能力标志为 `model_tasks=job-authority-v2`。升级后重启 Bridge；Codex 已连接的 MCP 需重新连接刷新工具列表，旧会话缓存的工具不会自动变成新接口。STB-RDC bootstrap revision 为 `model-tasks-v2`，返回新请求模板。

回归包括 MCP 无内部字段、RDC 拒绝旧参数、job 输入去重、旧 job 隔离、审批保护、重启后自动授权，以及真实 MCP stdio → socket → 隔离 tmux 的人工事件检查。实现入口为 `bridge/execution/run.py`、`job_actions.py` 和 `bridge/protocol/model_view.py`。
