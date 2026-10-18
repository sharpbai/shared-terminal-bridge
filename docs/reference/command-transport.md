# 命令传输、单行边界与重试

当前模型入口为 run/job ID。Core 提供 `command_request_dedup=durable-submit-v1` 和 `model_tasks=job-authority-v2` 能力；版本字符串或源文件存在不能代替运行能力检查。

## 命令只由目标 Shell 解释

| 路径 | 传递方式 |
| --- | --- |
| Codex → MCP → Core | terminal_run 的 JSON text |
| ChatGPT → RDC → Adapter → Core | 固定启动 serve-stdio，stdin JSONL 的 params.text；随后 Unix socket JSON |

每个协议边界只解析一次 JSON。不额外展开美元符、引号和反斜杠，不 trim 命令，不把目标命令拼入本地启动 Shell。无损传输只保证原文，不保证目标语法正确。

真正 CR/LF、NUL、Ctrl+C 等 ASCII 控制字符不作为 run 文本输入；字面量反斜杠转义不自动变成控制键。控制键用 job input 的 key 或 job interrupt。真正多行执行、自动拆分、目标脚本与 marker 注入均不提供。

## 逻辑请求身份

模型 run 必须提供唯一逻辑 request_id（RDC 来自 Envelope id）。JSON-RPC ID 是传输编号，不能代替命令身份。run 的观察窗口 wait_ms/wait_id 可以改变，命令身份参数必须保持一致。

| 情况 | 行为 |
| --- | --- |
| 相同 ID、相同命令身份 | 继续观察原 job，不续授权、不再次输入、不再次消费批准 |
| 相同 ID、不同命令身份 | COMMAND_REQUEST_CONFLICT |
| 处理中或崩溃仅留下预留 | COMMAND_REQUEST_AMBIGUOUS，查询证据或交人工，不换 ID 猜测重发 |
| 人工取消后重试旧 ID | 返回原任务状态，不重放取消的步骤 |
| 新的明确决策 | 新 ID，按本地接收顺序处理；高风险仍批准 |

Core 在执行前持久预留 ID 与参数指纹，再保存提交回执和 job。崩溃窗口存在，因此承诺“不盲目重放”，不是跨崩溃 exactly-once。若已提交但 job 被清理，报无法找到，不重新执行。

## 持久化与容量

去重记录随私有 daemon 状态持久化，文件权限 0600。虽然指纹不另存命令原文，缓存结果或审批错误可能包含命令，应按敏感运行状态保护。不要删状态来绕过去重。

最多保留 10000 个逻辑 ID，满后以 COMMAND_REQUEST_CAPACITY 拒绝新增，不静默淘汰保护记录；当前没有自动归档入口。

## 实现与回归

- `bridge/runtime/command_requests.py`：预留、指纹和结果；`state.py`：恢复。
- `bridge/execution/run.py`：执行去重、观察可重复；底层 submit 校验不属于模型兼容接口。
- `tests/test_command_transport.py`：MCP 特殊字符、去重、中断、恢复和控制字符拒绝。
- `tests/test_rdc_transport_integration.py`：相邻 Adapter 经分片 stdin、真实 Unix socket，验证逐字传输与响应丢失重试；独立仓库 CI 可跳过。
- `tests/host_tmux/test_command_quoting.py`：隔离真实 tmux/Shell 输出，不只核对回显。

内部步骤见 [Run](terminal-run.md)，模型调用见 [任务接口](model-tasks.md)，RDC 封装见 [JSONL 契约](../../../shared-terminal-bridge-rdc/docs/reference/stdio-transport.md)。
