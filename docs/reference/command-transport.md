# 无额外 Shell 的命令传输与重试

2026-10-18：已实现阶段一、二；真正的多行执行未开放。代码更新后需重启 Core 才会生效，`bridge_info.command_request_dedup=durable-submit-v1` 是运行时能力标志。

## 两条入口，同一个执行边界

| 路径 | 命令怎样传递 |
| --- | --- |
| Codex → STB MCP | `terminal_submit` 的 JSON `text` 原样传给 Core |
| ChatGPT → RDC → Adapter | 固定启动 `stb-rdc serve-stdio`，随后通过 RDC 标准输入传 JSONL；Adapter 经 Unix socket 将 `text` 原样传给 Core |

只有目标 Shell 解释命令。JSON 在每个协议边界只解析一次，不额外反转义、不替换 `\\n`、不展开 `$`、不 trim 命令。不通过本地 Shell 参数携带目标命令，不注入目标脚本或标记文件。复杂单行仍须是目标 Shell 的有效语法；无损传输不修复本身写错的命令。

`terminal_submit` 拒绝真实 CR/LF、NUL 和其他 ASCII 控制字符；字面量 `\n` 和 `\u0003` 不会变成换行或 Ctrl+C。中断使用 `terminal_interrupt`。现有 Task Block Runner 保持受限的逐步执行，不把多行字符串自动拆成命令。

## 请求身份与去重

提交时建议始终附带唯一 `request_id`（1–128 字符，例如 UUID）。旧调用不带 ID 仍兼容，但不具备这项重放保护。MCP JSON-RPC 请求 ID 与逻辑命令 ID 不同：运输重试可以有不同 RPC ID，但必须保留原来的 `request_id` 和全部参数。

Core 在续租和终端输入之前，持久化逻辑 ID 与完整参数的 SHA-256 指纹；指纹不另存原始命令。缓存的结果/拒绝沿用 Core 字段，审批拒绝等错误可能包含命令，应与原有私有状态文件同等保护。

- 同 ID、同参数：返回原提交结果或原拒绝；不续租、不再输入、不再消耗批准。
- 同 ID、不同参数：`COMMAND_REQUEST_CONFLICT`。
- 同 ID 正在处理，或崩溃只留下预留记录：`COMMAND_REQUEST_AMBIGUOUS`。查询 pane/job 或交给人工，不能换 ID 猜测重发。
- Human Ctrl+C 后重试旧 ID：仍返回原 job，不自动获得新授权；原 job 的最新状态通过 job/wait 查询。
- 真正的新决策使用新 ID，按 Core 本地接收顺序续授权；高风险批准仍独立生效。批准后改变参数也属于新请求。

结果落盘前会有崩溃窗口，因此只保证“不盲目重放”，不宣称跨崩溃 exactly-once。日志与 daemon 状态文件共同持久化，权限沿用 0600；不要删除状态来绕过去重。最多保留 10000 个 ID，达到容量时 `COMMAND_REQUEST_CAPACITY` 拒绝新增，不静默淘汰保护记录。现阶段尚无自动归档/清理入口。

收到提交结果只代表已提交，提示符返回只代表观测到命令结束，不等于退出码为零或业务成功。需要输出证据再判断。

## 验证入口

- `tests/test_command_transport.py`：真实 MCP 协议入口 → Core → 捕获后端；引号、awk `$1/$2`、反斜杠、Windows 路径、正则、Unicode、字面量转义；去重、人工中断、重启状态、真实换行拒绝。
- `tests/test_rdc_transport_integration.py`：复用同一语料，经分片 stdin JSONL → Adapter → 真实 Unix socket → Core → 捕获后端。需要相邻的 RDC 代码库；独立 Core CI 可跳过。沙箱禁止本地 socket 时在宿主运行。
- `tests/host_tmux/test_command_quoting.py`：隔离 tmux control stream → 真实 Shell，核对实际输出，不只核对命令回显。
- Adapter 自身 `tests/test_stdio.py`：独立运行，无需 Core、RDC 或 tmux。

代码定位：`bridge/runtime/command_requests.py` 管去重，`bridge/runtime/state.py` 管恢复，`bridge/execution/submit.py` 管命令校验。原有 lease、审批、事件流和任务状态机不搬入 Adapter。
