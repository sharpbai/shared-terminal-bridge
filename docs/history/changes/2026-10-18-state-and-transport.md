# STB 调整记录：执行状态、授权与命令传输（2026-10-18）

> 历史阶段记录：下文保留当时版本、测试数量及跨日追加过程，不作为当前接口说明。最终任务契约、自发现和发布结论见 [2026-10-19 整理记录](2026-10-19-model-api-release.md)；本轮内容已随 v0.16.0 发布。

本记录汇总本轮在本地完成的调整及当天验证结果，不代表已发布新版本。Core 版本号仍为 `0.15.1`，API 为 v9；运行能力以 `bridge_info` 为准。当前接口说明见[命令传输与重试](../../reference/command-transport.md)和[架构说明](../../reference/architecture.md)。

## 问题与调整

| 问题 | 本轮处理 |
| --- | --- |
| 返回提示符后仍一直 wait | 补充动态提示符识别与输出边界处理，避免 cwd 等变化导致旧基线无法匹配，减少旧历史混入当前命令结果 |
| 持有 lease 时任意人工 Ctrl+C 都撤权，范围过大 | 由任务执行状态机判断：仅同 pane、同 generation 的执行中任务被人工 Ctrl+C 中断时撤权；空闲或已结束不撤权 |
| 周期 capture 与按键事件可能顺序不一致 | 将命令开始、终端输出、人工中断纳入 pane 独立的 tmux control-mode 有序流，以 epoch/sequence/job/generation 关联 |
| 中断后继续工作反复要求授权 | 以 Bridge 本地接收顺序判断：中断后新收到的调用可自动续新 generation；旧调用的排队步骤不能恢复，不依赖模型自报时间 |
| 自动续授权可能使超时重试变成新执行 | 给 `terminal_submit` 增加可选逻辑 `request_id`，由 Core 持久去重；同 ID 重试不再次输入、不再次续租 |
| 复杂命令在上游 Shell 被提前展开 | Codex 保持 MCP 结构化参数路径；与 RDC JSONL 通道共用 Core 接口和回归语料，Core 不额外解释命令文本 |

此外，本轮修正 Human Event binding 的重构后入口路径，恢复 `local_bridge.py emit-event`，避免 Ctrl+C 触发 tmux 错误显示。

## 执行与授权边界

- 提示符先返回、人工 Ctrl+C 后到：已结束任务不因该按键撤权。人工中断先到：后续输出不能把中断结果改回正常完成。
- 有序流断开或缺序时，进入需人工检查状态，并拒绝该 pane 的新提交；不凭缺失证据猜测命令成功或人工接管。
- 新调用可以续授权，不等于可以重放旧调用内部步骤，也不扩大用户原任务范围。
- 高风险操作仍需人工确认；`high_io` / `full_scan` 仍由 Core 的一次性批准机制约束。耗时长本身不再单独要求批准。
- 提示符监测仍是完成启发式，不是可信退出码，也不能直接证明业务成功。

## 去重与单行契约

Core 在输入终端前持久化请求 ID 与参数指纹。同 ID、同参数返回原结果或拒绝；不同参数报冲突；处理中或崩溃后只有预留记录时拒绝重放，交由查询/人工处理。不是跨崩溃 exactly-once 承诺。

JSON 文本只在协议边界解析，不额外展开 `$`、反斜杠或引号。真正的 CR/LF、NUL 和其他 ASCII 控制字符不允许作为 submit 命令；字面量 `\n` / `\u0003` 不转成控制键。Agent Ctrl+C 使用独立中断接口。真正多行执行未实现，也不自动拆分执行、不注入目标脚本。

旧调用不带 `request_id` 保持兼容，但没有逻辑请求去重保护。去重容量与错误处理详见[接口说明](../../reference/command-transport.md)。

## 当天验证证据

| 验证 | 结果 | 范围 |
| --- | --- | --- |
| Core 全量默认测试（宿主执行） | 123 项通过 | MCP、状态机、去重、状态落盘恢复、取消与既有能力 |
| 宿主 tmux 测试 | 10 项通过 | 创建隔离 server，含事件顺序、binding、动态提示符、实际特殊字符输出 |
| 跨仓库传输测试 | 通过，计入 Core 测试 | 分片 stdin → Adapter → 真实 Unix socket → Core → 捕获后端，复用 MCP 特殊字符语料 |
| 模拟提交响应丢失 | 通过 | Core 已收到首次提交但客户端没收到结果；同 ID 重试仅产生一次终端输入 |
| 编译与差异格式检查 | 通过 | `compileall`、`git diff --check` |

测试入口：`tests/test_command_transport.py`、`tests/test_rdc_transport_integration.py`、`tests/host_tmux/test_command_quoting.py`。真实 tmux 验证只操作隔离测试 server，未向现有业务 pane 提交命令。

## 加载记录

当天经人工明确授权，Bridge daemon 已停止旧进程并用本地当前代码重新启动。重启后只读核验确认：

```text
execution_policy = local-receipt-auto-renew-v1
command_request_dedup = durable-submit-v1
managed_sessions = 12
```

服务及控制 socket 正常；重启保留既有 tmux 会话，不重建或停止其终端进程，原 ACTIVE lease 按恢复规则撤销。以上是当时快照，不把 PID、pane 或 generation 作为后续操作常量。

Bridge 重启不等于 Codex MCP 进程也已重载：已连接的旧 MCP 若尚未暴露新增 schema，需重新连接后使用 `request_id`。新 RDC worker 可直接探测 Core 能力。

## 后续与关联

尚待在专用会话完成 ChatGPT/RDC 插件的新 JSONL 端到端人工验收；真正多行执行仍暂缓。代码尚未因本轮操作提交、推送或发布新版本。

Adapter 的独立记录见[STB-RDC 当日调整](../../../../shared-terminal-bridge-rdc/docs/history/changes/2026-10-18-jsonl-transport.md)。

## 后续：Run 减少模型机械编排

新增 [terminal_run](../../reference/terminal-run.md)，在 Core 内完成复用/取得租约、严格提交和等待。执行部分沿用持久请求去重，同 ID 重试只观察原 job；等待参数可变，不重提命令。链内有效撤权后不能重新续租，旧 receipt 不得在中断后取得授权。取消等待和高资源批准语义沿用原实现，未新增 Codex MCP 自动授权入口。

本轮 Core 全量 134 项、隔离宿主 tmux 11 项通过；Adapter 37 项通过。新增了真正有序中断唤醒组合等待、旧 ID 重试与新 ID 续权、批准消费、等待取消、跨 Unix socket 响应丢失后不重放等回归。实际加载状态以重启后能力标志为准。

随后经人工明确许可重启 Bridge，真实 RDC 只读 bootstrap 已确认运行能力 `terminal_run=receipt-scoped-run-v1`、首选操作 run、模板及 `startup_request.timeout_ms=1` 均已生效。未向业务 pane 提交命令；原租约按重启规则撤销，tmux 会话保留。

## 后续：授权复杂度退出模型契约

按后续明确要求，不保留旧模型调用兼容。MCP 发布 run、job 输入/中断、审批请求 ID；RDC 取消 lease/submit，CLI 移除 lease/send。默认结果过滤内部授权元数据，命令和输出字符串不改写。输入和中断从原 job 解析内部权限，旧 job 不得操作新任务。

普通 run 不再依赖 Codex 回合身份或旧会话所有者来取得执行权限；本地 receipt 负责顺序，可信宿主身份仅用于风险审批证据。重启撤销没有人工事件序号的场景已回归，不再要求模型补 lease。预先取消的 MCP run 不提交，运行中的取消只停止等待。

Core 140 项、隔离宿主 11 项、Adapter 40 项通过，全局技能验证和手册构建通过。经本轮人工许可重启后，真实 bootstrap 只读核验 `model_tasks=job-authority-v2`、revision `model-tasks-v2`，只有 run/wait/job/interrupt/input/approve 模板且无内部计数；新建 MCP 实例同样验证通过。未提交业务命令；旧 Codex MCP 连接仍需重连刷新 schema。详情见[当前模型接口](../../reference/model-tasks.md)。
