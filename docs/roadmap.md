# Shared Terminal Bridge 后续路线图

## 摘要

本路线图来自 Notion 文档《人与 Codex 共用终端的交互式运维架构260920》，并结合
2026-09-20 已完成的本地 tmux Human/Agent 来源分流实验进行修订。

原文将“在 iTerm2 + tmux -CC 中寻找 Human Ctrl+C 捕获点”列为第一优先级。本地
实验已经证明 iTerm2 不是合适边界，并验证 tmux client key table 能区分 Human
输入和 Agent 的 `send-keys` 注入。因此路线起点已经从“寻找捕获点”推进到
“把已验证事件接入本地 Bridge”。

## 背景与范围

### 目标

- 用户继续把自己的 Terminal/tmux pane 当作主界面和事实来源。
- Codex 默认只读，按需获取 pane history、状态和结构化事件。
- Codex 仅在明确授权下写入指定 pane。
- Human `Ctrl+C` 在 Bridge 层强制撤销 Agent 的继续执行权。
- 长期把字符流逐步提升为 Terminal State、Command Blocks 和 Event Stream。

### 不在当前范围

- 不开发新的 Web Terminal 或 AI Terminal。
- 不把多个 Agent 的复杂编排放进 Bridge。
- 不将全部 scrollback 无选择地塞入模型上下文。
- 不接入飞书、Notion 或其他云端运行时。
- 不在第一阶段开放 Agent 写权限。

## 路线总览

| 阶段 | 主题 | 状态 | 主要产物 |
|---|---|---|---|
| Phase 0 | Human/Agent 来源分流 | 已完成 | tmux `Ctrl+C` PoC 与验证报告 |
| Phase 1 | Observation Bridge | 核心 PoC 已通过 | pane 枚举、读取、状态接口 |
| Phase 2 | Human Event IPC | 核心 PoC 已通过 | Unix socket、事件 schema、事件消费者 |
| Phase 3 | Execution Control | 核心 PoC 已通过 | Pane ACL、Execution Lease、Human Override |
| Phase 4 | 受控写入 | 待实施 | type/key/interrupt、Read Guard、审计 |
| Phase 5 | AI Context Policy | 后排 | 上下文选择、压缩、相关历史检索 |
| Phase 6 | Command Block Model | 后排 | 命令边界、退出码、结构化事件 |
| Phase 7 | UI 选择 | 可选 | 仅在现有窗口体验不足时评估 |

## Phase 0：Human/Agent 来源分流

### 已完成

- 真人 `Ctrl+C` 经过 tmux client root key table。
- binding 将 `C-c` 原样送入 pane，并异步记录 Human 事件。
- Agent 的 `tmux send-keys C-c` 不经过 client key table，不产生 Human 事件。
- 事件能够携带 `pane_id` 和 `client_name`。

### 已否决路径

- iTerm2 `KeystrokeMonitor` 只在普通 shell 验证成功。
- 进入 tmux 后不能作为稳定输入事件源。
- 全局监听普通按键不满足最小权限与敏感输入保护要求。

### 后续补充测试

- 多 tmux client 同时连接。
- copy-mode、prompt mode 和其他 key table。
- nested tmux 与远程 SSH 场景。
- Human 与 Agent 同时输入时的事件顺序。
- tmux server restart 和配置 reload 后的 binding 生命周期。

## Phase 1：Observation Bridge

第一版 Bridge 只提供“眼睛”，不给 Agent “手”。

**2026-09-20 进展**：双 pane 自动验证已通过，授权 history/state 可读，未授权
pane 在 tmux 读取前被拒绝且正文不泄漏。
实测见 [Observation Bridge 验证](validation-observation-bridge.md)。

**同日补充**：两个 control-mode client 已分别解析到不同 pane，未知 client
fail-closed，且 pane 解析不绕过 ACL。验证中否决了会静默回退到错误 client 的
`display-message -c` 路径。实测见
[Per-client Active Pane 验证](validation-active-pane.md)。

### v0.1 Observation API

- `terminal_list`
  - 枚举 server、session、window、pane。
  - 返回稳定 pane ID，而不是只返回名称或索引。
- `terminal_read`
  - 按 pane 读取最近 N 行或指定 history 区间。
  - 对输出大小设置硬限制。
  - 支持保留或清理 ANSI 序列。
- `terminal_state`
  - 返回 pane、session、window、client、foreground process。
  - 尽可能返回 host、cwd、shell 和 SSH 目标。
- `get_active_pane`
  - 根据明确 client 解析当前 pane。
  - 多 client 时不得用模糊的全局“当前 pane”。

### 读取安全边界

- 只能读取允许的 tmux server/session/pane。
- 默认不跨 pane 聚合内容。
- 不把其他未授权 pane 的历史带入当前任务。
- 每次读取进入 Audit Log。

### 验收标准

用户说“看一下刚才的输出”时，Bridge 能在无需复制粘贴的情况下：

1. 解析目标 pane。
2. 读取有界上下文。
3. 返回可供 Codex 分析的稳定结果。
4. 不读取其他 pane。

## Phase 2：Human Event IPC

将 PoC 的文件日志替换为本地 Unix domain socket。该阶段仍不实现 Agent 写入。

**2026-09-20 进展**：Human JSON 事件、socket `0600`、Agent 不误报和
consumer 缺失时 fail-open 均已验证。重连、背压、重放和并发仍属于工程化待办。
实测见 [Unix Socket Human Event 验证](validation-unix-socket-events.md)。

### 事件 schema

```json
{
  "seq": 1,
  "type": "human_interrupt",
  "source": "tmux_client",
  "key": "C-c",
  "server": "default",
  "session": "ops",
  "pane": "%3",
  "client": "/dev/ttys021",
  "timestamp": "2026-09-20T11:08:31+08:00"
}
```

### 传输要求

- 单调递增 `seq`，便于发现丢失和乱序。
- 每行一个 JSON 对象，便于调试和重放。
- producer 不得因 consumer 断线阻塞 tmux 输入。
- consumer 重连后能够重新同步当前状态。
- socket 权限只允许当前用户访问。
- 日志只记录控制事件，不记录普通按键内容。

### 验收标准

- Human `Ctrl+C` 到达前台程序的路径不被事件消费者影响。
- Bridge 断开、崩溃或未启动时，用户仍能正常中止程序。
- 事件能稳定关联正确 pane/client。

## Phase 3：Execution Control

**2026-09-20 进展**：已验证 `ACTIVE → REVOKED` 状态转换、Agent `C-c`
不误撤销，以及旧 generation 在写入 pane 前被拒绝。多 pane、过期、reacquire、
并发原子性和 MCP 接入仍待实现。实测见
[Execution Lease 与 Human Override 验证](validation-execution-lease.md)。

### Pane ACL

授权绑定到具体 pane，而不是整个 tmux server。一次“你直接查吧”不得自动获得
其他 pane 的写权限。

ACL 至少区分：

```text
READ      默认允许，但仍受 pane 范围约束
SUGGEST   默认允许
WRITE     需要当前任务授权
CONTINUE  需要有效 execution lease
INTERRUPT Human Ctrl+C 立即撤销 CONTINUE
```

### Execution Lease

```json
{
  "pane": "%3",
  "generation": 42,
  "task": "current-codex-task",
  "state": "ACTIVE",
  "issued_at": "...",
  "expires_at": "..."
}
```

所有写调用必须携带 pane 与 generation。Human interrupt 将对应 lease 改为
`REVOKED`；旧 generation 的后续输入在 Bridge 层直接拒绝。

### Human Override 状态转换

```text
ACTIVE
  ├─ normal completion → RELEASED
  ├─ expiry            → EXPIRED
  └─ HUMAN_INTERRUPT   → REVOKED
```

撤销后系统必须：

1. 停止当前自动执行计划。
2. 不重试被中断命令。
3. 不因为 prompt 恢复而执行下一条命令。
4. 保留结果和上下文。
5. 等待用户明确重新授权。

## Phase 4：受控写入与审计

### v0.1 Action API

- `terminal_type`：输入文本，不隐式附加 Enter。
- `terminal_key`：发送 Enter、方向键等明确按键。
- `terminal_interrupt`：Agent 主动发送 `C-c`，来源记录为 Agent。

### Control API

- `acquire_execution`
- `release_execution`
- `execution_status`
- `terminal_events`

### 强制执行链

```text
READ → PLAN → AUTHORIZATION → ACT → READ
```

Bridge 不接受没有近期 READ、明确 pane、有效授权和有效 lease 的 ACT。模型提示词
只是辅助说明，真正的拒绝必须发生在 Bridge。

### Audit Log

```text
10:31:22 READ       pane=%3
10:31:25 LEASE      pane=%3 generation=42 ACTIVE
10:31:26 TYPE       pane=%3 generation=42 bytes=24
10:31:27 KEY        pane=%3 generation=42 Enter
10:31:28 READ       pane=%3
10:31:35 HUMAN_KEY  pane=%3 client=/dev/ttys021 Ctrl+C
10:31:35 OVERRIDE   pane=%3 generation=42 REVOKED
```

敏感信息策略：

- 默认记录动作类型、目标和长度，不无条件保存完整命令。
- 明文命令审计是否开启应成为显式配置。
- 不保存密码、Token 或普通 Human 输入内容。

## Phase 5：AI Context Policy

该阶段不阻塞 MVP。

### 默认应进入 context

- 当前 pane 的最近命令与有限输出。
- foreground command 的必要输出窗口。
- host、cwd、shell、SSH 目标和 prompt 状态。
- 最近 Human 事件，尤其 interrupt 和 pane 切换。
- 最近一次 Agent 动作及其结果。
- 当前任务目标、判断和授权状态。
- 与当前任务相关的长期本地知识。

### 默认不进入 context

- 无关的大量 scrollback。
- 高频重复日志。
- ANSI 绘制字符等显示噪声。
- 已被结构化总结且不再需要原文的历史。
- 未授权 pane 的任何内容。

演进方向：

```text
固定最近 N 行
→ 当前状态 + 最近命令窗口
→ 最近 Command Blocks
→ 与任务相关的历史检索
```

## Phase 6：Command Block / Terminal Event Model

目标是让 Codex 面对结构化执行现场，而不是一整块字符快照。

Command Block 只能由 Bridge 本地元数据或目标环境显式安装的 shell integration
产生。Bridge 不得为推测命令边界或退出码而注入包装脚本、marker、临时
文件或 TTY 协议。没有显式 integration 时，只记录可验证的 pane 快照与输入事件。

### Command Block

```json
{
  "command": "systemctl restart x-ui",
  "source": "human",
  "host": "tx-bj-vps-0001",
  "cwd": "/home/duobeiyun",
  "started_at": "...",
  "finished_at": "...",
  "exit_code": 1,
  "interrupted": false
}
```

### Event 类型

- `human_input_activity`
- `human_interrupt`
- `agent_input`
- `command_started`
- `output_chunk` / `output_summary`
- `command_finished`
- `prompt_ready`
- `pane_selected`
- `ssh_host_changed`
- `cwd_changed`

最终上下文由以下部分组成：

```text
Terminal State
+ Command Blocks
+ Event Stream
+ 必要的 Raw Output
```

## Phase 7：UI 与远期选择

当前继续使用独立 Terminal 与 Codex 窗口，由操作系统并排布局。只有在实际使用证明
下列需求无法满足时才评估 Web Terminal：

- 跨设备持续访问同一个交互现场。
- 需要明确的可视化授权与事件时间线。
- 需要 pane、任务和审计的一体化导航。

即便增加 UI，tmux、Bridge、lease 和 event protocol 仍应保持独立，不把安全边界
迁移到前端。

## 参考项目的用途边界

- **agent-mux**：参考 Human + Agent 协作、pause/kill-switch 和 audit，不采用较重
  的多 Agent 编排。
- **tmux-bridge-mcp**：参考薄 MCP↔tmux Bridge、pane 枚举和 Read Guard。
- **Wave Terminal**：参考 durable session、SSH 状态、approval 和 context 选择。
- **Warp**：参考 Command Block 与终端事件结构化。
- **xterm.js / ttyd**：仅作为 PTY 输入输出路径和未来 UI 的底层参考。

## 当前最近三步

1. ~~定义 `terminal_list`、`terminal_read`、`terminal_state` 的输入输出
   schema。~~ 核心 PoC 与 per-client active pane 均已完成；下一步组合本地
   Bridge 原型。
2. ~~将 Human Event PoC 的文件日志改为 Unix socket，并保留 fail-open 行为。~~
   核心 PoC 已完成，工程化边界仍待补齐。
3. ~~用事件消费者模拟 execution lease，在 Human `Ctrl+C` 后拒绝旧
   generation。~~ 核心 PoC 已完成，下一步回到只读 Observation Bridge。

**2026-09-20 合并进展**：Observation、per-client resolution、Human Event、
Execution Lease 和 Action Guard 已合并进本地 JSON Bridge daemon，并通过
14 项端到端检查。详见
[合并本地 Bridge 端到端验证](validation-combined-bridge.md)。

合并、binding 恢复、状态持久化、daemon 生命周期和真实日常 tmux
人工验收均已完成。

**2026-09-20 binding 进展**：自定义 root `C-c` binding 精确恢复、原本无
binding 的恢复、重复恢复 fail-closed 和审计均已通过。快照仍是内存态，下一步
验证异常退出后的持久恢复。详见
[tmux Ctrl+C Binding 生命周期验证](validation-binding-lifecycle.md)。

**2026-09-20 持久恢复进展**：SIGKILL 后 ACTIVE lease 自动转为 REVOKED、旧
generation 拒绝、新 generation 单调递增、binding 快照跨进程恢复以及 state
`0600` 均已通过。详见
[Daemon 异常退出与持久状态恢复验证](validation-crash-recovery.md)。

**2026-09-20 实例身份进展**：同一 state 的第二 daemon 会被非阻塞
`flock` 拒绝；同名 tmux socket 重建并复用 `%0` 时，server UUID 不匹配会
fail-closed，旧 lease 不会套用。详见
[单实例与 tmux Server Identity 验证](validation-instance-identity.md)。该项完成后已进入
真实日常 tmux 的受限人工验收。

**2026-09-20 真实 tmux 验收进展**：在用户可见的 tmux client 中，
Observation/ACL、Agent 动作、Agent `C-c` 不误撤销、物理 `Ctrl+C` 撤销、
stale generation 拒绝和审计链路 9 项检查全部通过。详见
[真实日常 tmux 受限人工验收](validation-live-tmux-acceptance.md)。安全原型阶段
的预定验证已完成，下一步是定义 MCP 只读接口与显式授权的 Action 封装边界。

下一阶段可以接入最小 MCP 封装；仍不提前加入完整写入能力或 UI。

**2026-09-20 最小 MCP 进展**：已完成零第三方依赖的 stdio 适配器，
支持 `2026-07-28` 和 `2025-11-25` 两种协议时代。默认仅注册四个
Observation tools；Action 必须显式启用，且 MCP 不暴露 lease 获取。
MCP stdio → Unix socket → Bridge → 授权 tmux pane 端到端验证已通过。详见
[最小 MCP Server](mcp-server.md)。

**2026-09-20 真实运维性能基线**：使用 `verify33` 完成 local-33 磁盘检查、
Human Override、后续用户 turn 重新授权和 root 只读下钻。三个回合共耗时
255.505 秒、25 次 MCP 调用、处理 1,344,659 input tokens。Bridge RPC 为
毫秒级，主要优化空间是任务块、增量读取、审批合并和 AI Context Policy。
详见 [检查 local-33 磁盘占用 03 实操基线](baseline-live-ops-03.md)。

**2026-09-21 模型编排调研与会话 13 复盘**：当前性能瓶颈已经从 Bridge RPC 和
等待机制转移到复杂任务中的模型采样边界。会话 13 共记录 65 次命令提交；首次磁盘
检查较会话 12 缩短约 33%，租约、长任务审批、Human Override 和持久历史均工作正常，
但仍存在旧提示误判、重复 acquire、wait 后追加 status、明显引号错误和复杂步骤
碎片化。下一阶段将先修复这些往返，再以版本化、本地执行且不向目标环境注入脚本的
`TaskBlockRunner` 压缩模型编排次数。详见
[模型编排轮数优化：调研与实施规划](model-orchestration-research-and-plan.md)。

## 2026-09-21 下一阶段优先级

1. **P0：当前 job 范围的提示检测**，消除旧密码提示造成的误中断。
2. **P0：同 turn acquire 幂等**，已有有效租约时返回当前 generation。
3. **P1：wait 终态完备化**，正常路径不再追加 status。
4. **P1：保守命令完整性 lint**，在本地发现明显未闭合引号但不执行或展开命令。
5. **P1：只读 TaskBlockRunner**，用新版本 API 连续执行受控步骤，旧 task block
   保持只记录语义。
6. **P1：写入后验证 block**，批准精确绑定单个写 step，验证步骤保持只读。
7. **P2：循环/空增量本地检测**，只在真正决策边界唤醒模型。
8. **P2：远程断线、取消和恢复实测**，覆盖 SSH Broken pipe 与 daemon restart。
9. **P2：性能基准固化**，持续比较模型采样、MCP 调用、耗时和非缓存 token。

**2026-09-21 实施进展**：P0/P1 基础修复及只读 TaskBlockRunner 首版已完成。
Bridge/MCP 升级到 API v8 / v0.13.0；旧 `terminal_task_block` 保持只记录，新增
`terminal_task_block_execute` 执行最多 8 个保守白名单只读步骤。当前 job 范围的
提示检测、同 turn acquire 幂等、wait 终态提示、明显不完整命令拒绝均已加入测试。
写入后验证、持久 block 恢复、循环检测和真实性能对比仍属于后续阶段。
自动回归 63 项全部通过，隔离托管 tmux 中的两步只读 block 运行态验证完成；详见
[API v8 只读 TaskBlockRunner 验证](validation-task-block-runner.md)。

**2026-09-21 会话 14 复盘与 TUI 决策**：TaskBlockRunner 将首次磁盘检查 input
降低约 30%，但 TestDisk 三个全屏交互回合产生 91 次按键、26 次屏幕读取，消耗约
14.303M input tokens。近期不建设重型 TUI 支持；后续顺序调整为“程序原生 CMD/
batch → 人类辅助操作 TUI → Agent 轻量操作 TUI”。全屏退出后的错位不是 pane 宽度
不一致，而更接近 ncurses 模式恢复或按键越过 TUI 生命周期边界。详见
[查看 local-33 磁盘占用 14 实操基线](baseline-live-ops-14.md)。

## 2026-09-21 重新排序后的下一步

1. **P0：程序 capability profile**：先覆盖 TestDisk/PhotoRec，再逐步记录已验证的
   CMD、batch、list、dry-run、日志和结构化输出方式。
2. **P0：精确扩充只读 Runner profile**：加入 `fdisk -l`、只读 `blkid`、
   `testdisk /version`、`qemu-nbd --version`，不扩大为整个程序白名单。
3. **P1：人工协同 TUI 工作流**：模型给出目标界面和连续操作提示，然后结束当前轮；
   人到达检查点后再读取一次屏幕，不逐键遥控。
4. **P1：写入后验证 block**：批准只绑定一个写 step，后续验证保持只读。
5. **P1：本地循环/空增量检测**：没有有效变化时不触发模型。
6. **P2：轻量 TUI 生命周期保护**：expected process、screen fingerprint、前台程序
   变化后拒绝剩余按键、正常退出优先、强制退出后的 display check。
7. **P2：轻量 TUI 降 token**：有限 key sequence 和 changed-row snapshot；不做
   通用 TUI 控件识别、视觉模型或终端仿真。
8. **P2：远程断线、取消与恢复实测**：覆盖 SSH Broken pipe 和 daemon restart。
9. **P2：性能回归**：将会话 14 加入基准，分别统计普通命令与 TUI 段。

**2026-09-21 实施进展（API v9 / v0.14.0）**：已完成 P0 与 P1 首批。
新增 TestDisk/PhotoRec capability profile；Runner 精确支持 `fdisk -l TARGET`、
`blkid -p [-O OFFSET] TARGET`、TestDisk 版本探测和 `qemu-nbd --version`，模板外
参数仍 fail closed。MCP 已强制推荐人工检查点工作流；本轮未增加通用 TUI
自动化，P2 生命周期保护与 changed-row 观察仍保留为后续。

**2026-09-21 会话 15 回归**：14 个回合、10.1 分钟、4.73M input，相比会话 14
分别下降约 7%、65% 和 79%，主要收益来自完全避开 TUI。首次磁盘检查
input 基本持平，耗时由 28.5 秒升至 42.8 秒，说明后续优化重点仍是模型
编排而非 Bridge RPC。剩余问题为一次多余 status、长任务显式使用 60 秒
wait 以及 Skill 的每回合重复加载。详见
[查看 local-33 磁盘占用 15 实操基线](baseline-live-ops-15.md)。

## 风险与开放问题

- tmux 不同 key table 是否需要统一绑定策略。
- 多 client 同时操作一个 pane 时如何定义 active/selected pane。
- 事件产生与 pane 接收 `C-c` 的严格先后顺序。
- socket consumer 断线期间的事件保留与重放边界。
- 远程 SSH、nested tmux 和本地 tmux 的 pane/host 映射。
- vim、less、top 等全屏程序下如何判定 terminal state。
- shell integration 是否足以提供 command/exit/host/cwd，还是需要独立 shell hook。
- Agent 写入命令的审计内容如何兼顾可追溯性与凭证保护。

## 来源

- Notion：
  [人与 Codex 共用终端的交互式运维架构260920](https://app.notion.com/p/3e147b2dd1458175b152cfd6e8daf43f)
  （读取于 2026-09-20，页面状态 Doing）。
- 本地实测：
  [Human/Agent 来源分流验证](validation-human-agent-source.md)。
