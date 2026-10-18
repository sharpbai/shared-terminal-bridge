# Terminal Run：一次授权、提交与等待

模型默认接口已收敛为 run/job ID，旧模型契约不再兼容，见[当前模型接口](model-tasks.md)。本文涉及的内部授权字段只用于解释 Core 实现，不是模型参数。

`terminal_run` 是 Core 的组合接口，也是 Codex MCP 与 STB-RDC 的默认执行入口。模型不管理内部授权计数；独立低层方法仅供 Core 和人工诊断，不作为模型兼容契约。普通执行以本地 receipt 决定权限，可信宿主回合信息仅用于风险批准证据。

## 接口与能力发现

运行 daemon 的 `bridge_info.terminal_run=receipt-scoped-run-v1` 和 `model_tasks=job-authority-v2` 才表示支持当前契约；仅更新源文件不够，需要重启 Bridge。该接口随 v0.16.0 发布，API 仍为 v9。

```json
{"method":"terminal_run","params":{"pane":"%0","request_id":"NEW_UNIQUE_COMMAND_ID","text":"df -h /","expected_duration_ms":1000,"resource_class":"normal","wait_ms":600000}}
```

`pane` 必须有 ACL 权限，`request_id` 必填。单行 `text`、耗时、资源类型与可选 `long_run_approval_id` 沿用 submit。`wait_ms` 为 1–600000 的整数，默认 600000；可选 `wait_id` 继续使用现有取消等待接口。首次接入或人工换机后，仍应先观察环境，run 不推断 SSH 对面的主机身份。

## Core 内部步骤

1. 持久化逻辑请求预留，防止重复提交。
2. 在同一本地请求 receipt 内，复用 ACTIVE generation；无租约或可重新取得授权时调用原 acquire。保留现有授权元信息，不用调用方时间戳。
3. 使用严格的 `terminal_submit` 直接方法，不经过自动续授权 dispatch。如果授权后、提交前发生有效人工撤权，该调用失败，不重新 acquire。
4. 将提交结果和 job ID 持久化，然后释放执行阶段，调用原 `terminal_wait_job` 等待。等待不持有 Bridge 全局锁。

没有逐条模型决策，也没有 Adapter 自行串联 API。高风险确认仍由原规则处理，`high_io/full_scan` 仍要求匹配的一次性批准；run 不自动批准。初次因缺少批准而拒绝后，按原审批流程处理，再用新逻辑 ID 携带批准执行。

## 去重与后续观察

同 ID、同命令重试只取得原 job，再观察它的最新状态；不续租、不重交命令、不再消耗批准。命令身份包括 pane、text、耗时、资源类型和批准 ID，并带 run 操作标识，避免与 submit ID 混用。`wait_ms` / `wait_id` 只是观察参数，可以更改后继续等待同一 job。

与独立 submit 返回缓存的首次提交结果不同，run 的执行部分去重、等待部分可重复。因此同一 ID 的返回状态可能从 WAIT_TIMEOUT 变成 COMPLETED，但始终是同一 job。

参数冲突、预留期间并发调用、崩溃只剩预留记录，继续使用 `COMMAND_REQUEST_CONFLICT` / `COMMAND_REQUEST_AMBIGUOUS`，不盲目重放。状态恢复后只要已有提交回执，就能继续观察原 job。若 job 已清理则报告找不到，不重新执行。

## 人工中断和等待

- 执行期间 Human Ctrl+C：仍按有序事件流撤销该 generation、唤醒 wait，返回 INTERRUPTED_BY_HUMAN。旧 ID 重试只观察中断结果。
- 中断后新逻辑请求按本地接收顺序续授权；中断前已接收的旧调用不能续授权。
- 取消 wait：只返回 WAIT_CANCELLED，不发送 Ctrl+C、不重提任务；观察超时、策略检查点和人工决策截止仍沿用原语义。
- 提示符完成识别仍是启发式，不代表退出码为零或业务成功。

## 回归与维护

`bridge/execution/run.py` 实现组合，`bridge/runtime/command_requests.py` 继续负责持久去重。`tests/test_terminal_run.py` 覆盖授权、旧 receipt、链内中断、批准、去重、取消等待；`tests/host_tmux/test_terminal_run.py` 在隔离 tmux 中验证完成、人工事件唤醒、旧 ID 重试与新调用续权。

该接口不注入脚本、不开放真正多行执行、不自动合并多个需判断的命令。首次 run 无需模型先拿 generation，后续交互/中断使用 job ID，审批使用请求 ID；内部授权计数不进入模型参数。
