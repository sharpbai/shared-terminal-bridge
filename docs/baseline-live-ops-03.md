# 实操基线：检查 local-33 磁盘占用 03

日期：2026-09-20  
Codex thread：`01a0bdf7-4a9a-7f82-a8cb-4c960ff9fa81`  
托管会话：`verify33`  
目标 pane：`%5`  
目标主机：`local-33`  

## 验证结论

本次实操确认以下控制链已经正常工作：

- 新 Codex thread 能取得 generation 4。
- 人类按下 `Ctrl+C` 后，当前扫描停止，Agent 没有继续写入。
- Agent 只读取已有信息并结束当前用户回合。
- 后续真实用户消息到达后，同一 thread 能取得 generation 5。
- root 权限由人类在共享终端中授予，Agent 随后继续只读分析。

功能目标已经成立。当前主要问题转为效率：终端 Bridge 很快，但模型调用、
审批链、轮询和重复上下文造成较高时间及 token 成本。

## 实操过程

### 回合 1：基础容量检查

用户目标：检查 Ubuntu 主机磁盘占用。

执行流程：

1. 列出托管会话并取得 generation 4。
2. 执行 `df -hT` 与 `lsblk`。
3. 执行 `df -ih`。
4. 得出 `Shared331` 100% 满、inode 正常。

耗时 32.845 秒，首 token 3.732 秒，共 6 次 MCP 调用。

### 回合 2：深入分析与 Human Override

用户目标：分析 `Shared331`。

执行流程：

1. 已有 generation 4 仍有效，因此重复 acquire 被拒绝，但状态查询返回当前
   ACTIVE Lease。
2. 提交顶层 `du` 扫描。
3. 人类按下 `Ctrl+C`。
4. `terminal_read` 返回 `human_override=true`，Agent 立即结束，没有继续提交。

耗时 41.660 秒，首 token 3.309 秒，共 6 次 MCP 调用。该回合验证了中断边界。

### 回合 3：新用户回合重新授权并完成分析

用户说明已经授予 root，要求继续分析。

执行流程：

1. 新用户 turn 获得 generation 5。
2. 确认身份为 root，并枚举顶层 6 个目录。
3. 对顶层目录执行分项、限时扫描。
4. 查询 Timeshift 快照列表和数量。
5. 分解 `backup61` 与 `sharpbai-shared`。
6. 枚举最大的普通文件并形成最终结论。

最终识别：Timeshift 约 1.8–1.9T、`bk61.img` 450G、两个 SD 镜像共约
174G。全程只读。

耗时 181.000 秒，首 token 6.357 秒，共 13 次 MCP 调用。

## 时间基线

| 回合 | 总耗时 | 首 token | MCP 调用 | MCP/审批可见耗时 | 主要等待来源 |
|---|---:|---:|---:|---:|---|
| 基础容量检查 | 32.845s | 3.732s | 6 | 约 9.219s | 两次写操作审批、模型采样 |
| Ctrl+C 中断 | 41.660s | 3.309s | 6 | 约 3.451s | 扫描启动、人工中断、收束回复 |
| root 后深入分析 | 181.000s | 6.357s | 13 | 约 14.119s | `du` 扫描、轮询、15 次模型采样 |
| 合计 | **255.505s** | — | **25** | **约 26.789s** | 扫描与模型编排占主导 |

Bridge Unix socket 的请求处理通常为 10–30ms。表中的数秒级 MCP 调用主要包含
Codex 对写工具的审批链，而不是 Bridge RPC 本身。因此优化重点不应放在 socket
协议，而应减少写工具调用次数、模型采样次数和无效轮询。

## Token 基线

| 回合 | Input | Cached input | 新增 input | Output | Reasoning | 总处理 token |
|---|---:|---:|---:|---:|---:|---:|
| 基础容量检查 | 306,434 | 281,728 | 24,706 | 894 | 152 | 307,328 |
| Ctrl+C 中断 | 263,415 | 258,688 | 4,727 | 1,117 | 481 | 264,532 |
| root 后深入分析 | 774,810 | 759,680 | 15,130 | 2,610 | 730 | 777,420 |
| 合计 | **1,344,659** | **1,300,096** | **44,563** | **4,621** | **1,363** | **1,349,280** |

缓存命中约 96.7%，说明直接成本受到缓存缓解，但每次模型采样仍重复处理约
4.3–5.9 万 tokens 的上下文。第三回合约 15 次模型采样，是 token 总量达到
77.5 万的直接原因。终端历史反复读取、工具说明、任务历史和审批转录共同构成
上下文膨胀。

## 建议的 Task Block 模型

将一次交互运维拆成可审计的任务块，而不是每条命令都回到模型重新规划：

```text
Task Block
├─ identity: thread_id + turn_id + pane + generation
├─ objective: 本块要回答的问题
├─ policy: readonly / timeout / max_output / stop_on_human_override
├─ steps: 有序命令与完成条件
├─ observations: 每步的增量输出摘要
└─ result: completed / timeout / human_override / denied
```

当时建议高层工具 `terminal_task_block` 一次提交多个只读步骤。后续实操证明，
这会迫使 Bridge 向未知执行环境注入脚本和传输协议，因此 v0.6 已废弃该执行
模型。task block 现只是 daemon 内的本地计划/观察元数据；每条命令必须经
`terminal_submit` 显式发送，并在步骤之间重新观察。

本次第三回合可收敛为三个任务块：

1. 身份与顶层清单。
2. 顶层目录限时容量扫描。
3. 对已识别的大目录及大文件做定向下钻。

预计可把 13 次 MCP 调用压缩到 3–5 次，并把约 15 次模型采样压缩到 4–6 次。

## AI Context Policy v0.1

策略参考范围限定为 OpenHands 的 Event Store / View / Condenser 模型。Bridge
保留完整原始事件，模型只消费按当前 Task Block 构建的增量 View；不采用按最近
N 条 observation 直接改写聊天历史的方案，以免破坏 prompt cache 和审计链。

### 1. 增量终端读取

`terminal_read` 应返回 cursor。后续调用只返回 cursor 之后的新内容，禁止默认
重复注入 30–120 行历史。Human Override 状态作为结构化字段始终保留。

### 2. 输出预算

每个任务块设置：

- `max_output_bytes`：默认 16 KiB；
- `max_lines`：默认 200；
- `timeout_seconds`：每步明确指定；
- 超限时返回截断标记、首尾样本和统计，不把完整输出送入模型。

### 3. 结构化观察代替屏幕重放

稳定事实只保留一次，例如主机、pane、挂载点、当前 generation。后续模型上下文
使用 observation digest，不再携带完整 terminal history。原始输出留在本地审计
文件，需要时按 cursor 取回。

### 4. 采样边界

只有以下事件触发模型重新决策：

- 任务块完成；
- 命令超时或失败；
- Human Override；
- 结果超过阈值，需要选择下钻目标。

普通轮询、命令仍在运行、输出没有实质变化时不触发模型采样。

### 5. Human Override 优先级

一旦收到 `human_override=true`：

1. 停止任务块；
2. 最多读取一次增量输出；
3. 生成简短 observation digest；
4. 立即结束当前用户回合。

只有经过 Codex turn gate 验证的新用户消息才能建立下一任务块。

### 6. 建议性能目标

针对类似磁盘诊断：

- 基础检查：不超过 3 次 MCP 调用、2–3 次模型采样、30 秒；
- 中断响应：Ctrl+C 后 2 秒内阻止写入，10 秒内返回已有信息；
- 深入扫描：不超过 5 次 MCP 调用、6 次模型采样；
- 单回合新增 input 控制在 10,000 tokens 内；
- 单回合累计 input 处理控制在 250,000 tokens 内。

## 下一步实现顺序

1. `terminal_read_cursor`：增量读取与输出上限。
2. `terminal_task_block`：仅本地任务范围和 stop-on-override 状态，不批量执行。
3. 本地 observation digest：原始终端输出与模型上下文分离。
4. 将本文件指标加入性能回归，比较耗时、MCP 调用数、模型采样数和 token。

## 可参考实现

- OpenHands Terminal 目录：
  <https://github.com/OpenHands/software-agent-sdk/tree/main/openhands-tools/openhands/tools/terminal>
- OpenHands command session：
  <https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-tools/openhands/tools/terminal/terminal/terminal_session.py>
- OpenHands observation schema：
  <https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-tools/openhands/tools/terminal/definition.py>
- OpenHands condenser：
  <https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-sdk/openhands/sdk/context/condenser/base.py>
- MCP Tasks extension：
  <https://tasks.extensions.modelcontextprotocol.io/specification/draft/tasks>
- VS Code Terminal Shell Integration：
  <https://code.visualstudio.com/docs/terminal/shell-integration>
