# 模型编排轮数优化：调研与实施规划

日期：2026-09-21  
基线会话：`查看 local-33 磁盘占用13`  
Codex thread：`01a0c1f5-b08e-78f3-9702-59e4f0d40c6a`  
托管 tmux 会话：`verify33`

## 结论

当前 Bridge 的 Unix socket、tmux 写入和本地等待通常不是主要耗时。复杂任务的
主要成本来自模型在每条命令之后重新读取、判断、提交和等待。会话 13 共记录
65 次 `SUBMIT` / `JOB_CREATE`，复杂虚拟机转换和注册表修复中，大量 Bridge 调用
本身只需毫秒，但单个用户回合分别耗时约 165 秒和 382 秒。

下一阶段不应把控制脚本注入目标终端，也不应假设目标环境存在特定 shell、Python
或临时文件能力。优化方向是增加运行在本地 Bridge daemon 内的轻量
`TaskBlockRunner`：模型一次描述一组明确步骤，Bridge 仍逐条向 tmux 提交可见原始
命令，并对每一步执行现有 lease、generation、审批、审计和 Human Override 校验。
只有到达真正的决策边界时才重新唤醒模型。

## 会话 13 数据

- 首次磁盘检查 30.7 秒；会话 12 为 45.9 秒，缩短约 33%。
- 历史记录包含 258 条 `verify33` 事件。
- 65 次命令提交、65 个 job 创建、69 次 job 状态事件。
- 15 次 lease acquire、14 次 generation supersede。
- 2 次长任务请求与 2 次批准。
- 1 次 Human interrupt、2 次 Agent interrupt。
- 输入 token 25,033,971，其中缓存输入 24,729,344，缓存占约 98.8%。
- 非缓存输入约 304,627，输出 44,656，推理输出 13,258。

总 token 不能直接与单纯磁盘检查比较，因为本次还完成了 VirtualBox 虚拟机迁移、
Windows XP 0x7B 诊断、离线注册表修复和残留清理。但 65 次提交说明复杂任务仍被
切得过碎；缓存降低了直接成本，却没有消除每次模型采样的延迟。

## 成熟项目调研

### smolagents：用一次模型步骤表达多步动作

Hugging Face `smolagents` 的 `CodeAgent` 允许模型在一个 action 中表达多次工具调用，
并使用 `planning_interval` 每隔若干执行步骤才重新规划。值得借鉴的是“多步执行、
周期性重规划”，而不是在目标终端执行模型生成的 Python。

本项目采用受限变体：模型生成结构化 task block，本地 Runner 解释并调用 Bridge
已有的单命令执行原语，不开放任意本地代码执行。

### LangGraph：状态机、checkpoint 和 interrupt/resume

LangGraph 把长流程建模为有状态节点，在 checkpoint 边界持久化；人工审批使用
`interrupt` 暂停，再用 `Command(resume=...)` 恢复。它特别强调恢复时节点可能重新
执行，因此 side effect 必须幂等。

本项目应为每一步使用稳定键：

```text
task_block_id + step_id + generation
```

已完成的步骤返回历史结果，运行中的步骤返回同一 job，状态未知的写操作不得自动
重试，旧 generation 永远拒绝。

### OpenHands：事件流、上下文视图和卡死检测

OpenHands 将 action、observation、conversation state 和 context condenser 分离；
其 `StuckDetector` 检测重复 action-observation、重复 action-error、交替循环和无用户
输入的 Agent 独白。它只分析最近的活动分支，而不是反复注入全部历史。

本项目可在 daemon 内确定性完成重复、空增量、无进展和预算判断。完整原始输出留在
历史中，模型默认只收到当前 task block 的结构化摘要和必要证据。

### Temporal：长任务、heartbeat、取消和恢复语义

Temporal 将 durable Workflow 与可能产生副作用的 Activity 分离，使用 event history、
heartbeat、cancellation 和 retry policy 管理长任务。当前项目无需引入完整 Temporal，
但可借鉴其语义：task block 类似 workflow，单条终端命令类似 activity，tmux 输出
变化类似 heartbeat，Human Ctrl+C 类似 cancellation signal，后续用户消息类似新的
workflow signal。

## 目标执行模型

```text
当前：模型 → submit → wait → 模型 → submit → wait → 模型

目标：模型生成 task block
             ↓
      Bridge 校验 block 和每个 step
             ↓
      本地连续 submit / wait / assert
             ↓
      完成、异常、审批、分支或人工中断
             ↓
      模型获得一次结构化 observation
```

模型负责目标理解、计划、语义分支、异常重规划和最终汇总。Bridge 负责租约、等待、
完成检测、确定性断言、上下文预算、循环检测、审计和中断。

## 安全与环境边界

- Runner 只存在于本地 Bridge daemon。
- 不向目标终端注入 wrapper、marker、临时脚本或控制协议。
- 不假设目标环境的 shell、解释器、文件系统或工具能力。
- 每个 step 的原始命令对用户可见，并单独进入审计历史。
- 每个 step 在发送前重新检查 pane、generation、approval 和 Human Override。
- 写入和破坏性步骤不得因为放入 task block 而扩大授权。
- Human Ctrl+C 立即终止 block 的后续步骤；已经产生的 observation 被保留。
- 新用户 turn 必须生成更新的可信 turn identity，并重新取得 generation。

## Task block 建议结构

```json
{
  "task_block_id": "tb_xxx",
  "thread_id": "codex-thread-id",
  "turn_id": 1789964824000,
  "session": "verify33",
  "pane": "%11",
  "generation": 16,
  "goal": "确认虚拟机磁盘引用",
  "risk": "read_only",
  "state": "PLANNED",
  "limits": {
    "max_steps": 8,
    "max_duration_seconds": 120,
    "max_output_bytes": 32768
  },
  "steps": [
    {"step_id": "s1", "command": "virsh list --all", "retry": "safe"},
    {
      "step_id": "s2",
      "command": "virsh dumpxml win7",
      "retry": "safe",
      "assert": {"contains": "device='disk'"}
    }
  ],
  "stop_conditions": [
    "human_interrupt",
    "interactive_prompt",
    "permission_denied",
    "unexpected_exit",
    "generation_changed"
  ]
}
```

当前 `terminal_task_block` 仍保持“只记录、不执行”的 v0.2 语义。新的执行能力应使用
新 API 或显式版本字段，不能让旧调用在升级后突然开始执行命令。

## 模型重新介入的边界

Bridge 可以自动继续：

- 只读命令正常完成；
- 确定性断言通过；
- 下一步不依赖输出的语义解释；
- 未出现交互提示、人工中断或 generation 变化；
- 时间、步骤和输出预算均未耗尽。

必须停止并唤醒模型：

- 需要根据内容选择分支；
- 断言不成立或出现未知错误；
- 出现密码、确认或其他交互提示；
- 下一步需要新的审批；
- 输出与运行时间明显超过预算；
- 重复执行、连续空增量或无实质进展；
- 用户发送新消息或 Human Ctrl+C；
- task block 完成，需要形成用户结论。

## 本地无模型判断

以下判断应在 Bridge 内完成，不消耗模型 token：

- job 是否运行、完成或被中断；
- 当前 job 是否产生新输出；
- 提示符是否回归；
- generation 和 approval 是否有效；
- 是否出现当前 job 的密码或确认提示；
- 是否存在未闭合引号的明显提交错误；
- 明确字符串、退出状态和正则断言是否成立；
- 是否出现相同命令和相同结果循环；
- 是否达到空增量、步骤、时间或输出预算。

建议初始规则：

```text
相同命令 + 相同结果连续 3 次  → NEEDS_REPLAN
相同命令 + 相同错误连续 2 次  → NEEDS_REPLAN
连续 3 次空增量                → 转为事件等待，不再唤醒模型
只读 block 超过 8 个步骤        → NEEDS_REPLAN
达到预计时长上限                → STRATEGY_REVIEW_REQUIRED
同一策略重新规划 2 次仍无进展    → HUMAN_DECISION_REQUIRED
```

## 会话 13 遗留问题

### P0：提示检测污染

曾因 pane 历史中的旧 `sudo` 密码提示误判当前 job 需要输入，导致多余 Agent interrupt。
提示检测必须使用命令回显锚定后的当前 job 增量，不得在整个 pane snapshot 中匹配。

### P0：同 turn 重复 acquire 不幂等

注册表修复末尾出现一次不必要的 acquire 失败。相同 thread、可信 turn、pane 和有效
generation 的重复 acquire 应返回现有 lease；不同 owner 或不同 turn 仍按现有规则
更新、拒绝或 supersede。

### P1：wait 后仍追加 status

个别正常路径在 `terminal_wait_job` 完成后又调用
`terminal_job_status(include_output=true)`。wait 应返回明确终态、输出完整性、截断标记、
完成置信度和推荐下一动作，使正常命令维持 `submit + wait` 两次调用。

### P1：提交前的明显引号错误

一次 VirtualBox 残留检查进入 zsh `dquote>` 状态。Bridge 可做保守的“输入是否明显不完整”
检查，只识别未闭合的单/双引号、末尾续行等确定性问题；不执行命令、不进行 shell
扩展，也不假设远端 shell 语义。无法确定时正常提交，不能把 lint 变成错误拒绝。

### P1：复杂任务步骤碎片化

虚拟机迁移和注册表修复包含大量毫秒级 submit/wait，却消耗数分钟模型编排时间。
需通过顺序只读 block、写入后验证 block 和长任务 block 将模型采样移到决策边界。

### P2：长任务改进尚未覆盖远程断线实测

会话 13 未覆盖 SSH Broken pipe、前台程序变化和等待取消后的恢复，需要单独真实验收，
不能仅以单元测试视为完成。

## 下一步实施规划

### Milestone A：先消除不必要往返

状态：**已实现（2026-09-21）**。

1. 将 interaction prompt 检测限定到当前 job output window。
2. 同 turn acquire 幂等返回当前 lease。
3. 扩充 wait 的终态响应，消除正常路径的追加 status。
4. 加入只报告、不执行的保守命令完整性 lint。
5. 为以上问题补充回归测试和历史审计断言。

验收：普通短命令稳定为一次 `submit + wait`；旧 pane 密码提示不产生
`NEEDS_ATTENTION`；重复 acquire 不创建新 generation，也不报占用错误。

### Milestone B：只读 TaskBlockRunner

状态：**已实现首版（2026-09-21）**。首版采用保守单命令白名单，不支持管道、
重定向、shell 展开或长任务审批继承；这些限制用于建立可验证的安全基线。

1. 新增版本化的 `terminal_task_block_execute`，旧 `terminal_task_block` 语义不变。
2. 支持最多 8 个顺序只读 step。
3. 每步内部复用现有 submit/job/wait/lease/audit 实现。
4. 支持 contains、not_contains、regex 等确定性断言。
5. 任何 Human Override、交互提示、未知状态或 generation 变化立即停止。
6. 返回 block 级摘要和每步 output reference，默认不返回全部原文。

验收：基础磁盘与虚拟机只读检查中，命令仍逐条可见和可审计；模型采样次数至少
降低 50%，Ctrl+C 后不再发送后续 step。

### Milestone C：写入后验证与审批继承

1. 支持一个已批准写步骤及其只读验证步骤。
2. approval 只绑定指定 step 的命令摘要，不授权整个 block 任意写入。
3. 写步骤状态未知时禁止自动重试。
4. 为每步保存幂等键和恢复状态。

验收：一次人工批准可完成“写入 + 只读验证”，但不能执行计划外写命令；daemon
重启后不会重复未知状态的写操作。

### Milestone D：本地循环检测与长任务恢复

1. 增加重复 action/observation、重复错误和空增量检测。
2. 等待使用事件通知，空输出不触发模型轮询。
3. 任务达到预计上限后触发一次策略评估；明显超期转人工决策。
4. 完成 SSH 断线、取消等待、daemon 重启和后续用户 turn 的真实验收。

### Milestone E：上下文视图与性能基准

1. task block 默认只返回 facts、exceptions、metrics 和 output references。
2. 完整输出继续保存在 0600 历史文件中，按需读取。
3. 将会话 03、11、12、13 固化为性能基线。
4. 每次回归统计命令数、模型采样数、MCP 调用数、墙钟时间、非缓存 input 和误唤醒。

### Milestone F：程序交互模式选择

状态：**首批已完成**。该阶段优先减少进入 TUI 的机会，不建设通用 TUI 自动化。

执行顺序固定为：

1. 检查程序是否提供 CLI、CMD、batch、script、JSON、日志或导出接口；
2. 若仍需 TUI，优先让人类连续操作，模型只在明确检查点读取一次屏幕；
3. 只有人机协同仍不适用时，Agent 才进行受限 TUI 操作。

CMD 能力探测不得直接尝试潜在修改参数。优先使用程序官方文档、`--help`、version、
只读 list/dry-run；将已经验证的调用保存为程序级 capability profile。TestDisk 优先
评估其官方 `/cmd` 模式，尤其是 list、advanced、undelete 和日志输出。

实施：API v9 提供 `terminal_program_profile`，首批覆盖 TestDisk/PhotoRec；
只读 Runner 增加四类精确诊断模板，MCP 明确要求人工检查点工作流。

### Milestone G：轻量 TUI 降本（后续方向）

不实现终端仿真器、通用控件识别、视觉理解或自动菜单规划。仅保留低成本、高收益项：

1. TUI 操作前记录前台程序、pane 尺寸和当前屏幕 fingerprint；
2. 前台程序改变后拒绝后续按键，防止按键泄漏到 shell；
3. 支持有上限的小型 key sequence，合并连续方向键，但 Enter/确认保持独立边界；
4. 当前可见屏幕按 changed rows 返回，避免重复注入整屏；
5. 优先正常退出；强制 Ctrl+C 后先做 shell-ready/display-check，再继续业务命令；
6. Human Ctrl+C 或人类开始操作时立即停止 Agent 的剩余按键。

该阶段只有在 CMD 优先和人工协同策略仍不能满足实际任务时再实施。

## 性能目标

针对类似会话 13 的复杂运维流程：

- 命令本身仍可保持约 65 条，但模型编排边界降到 15–25 次；
- 连续只读检查的模型采样减少至少 50%；
- 正常单命令路径仅使用 `submit + wait`；
- 无变化等待不产生模型调用；
- block 摘要默认不超过 16 KiB，完整输出使用 reference；
- Human Ctrl+C 后立即阻止未开始步骤，2 秒内反映为 block interrupted；
- 不增加任何目标环境注入或隐式脚本执行。

## 参考资料

- smolagents CodeAgent：<https://huggingface.co/docs/smolagents/reference/agents>
- smolagents planning/HITL：
  <https://github.com/huggingface/smolagents/blob/main/docs/source/en/examples/plan_customization.md>
- LangGraph interrupt：
  <https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/types.py>
- LangGraph graph API 与幂等说明：
  <https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/graph-api.mdx>
- OpenHands Agent 架构：
  <https://github.com/OpenHands/docs/blob/main/sdk/arch/agent.mdx>
- OpenHands StuckDetector：
  <https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-sdk/openhands/sdk/conversation/stuck_detector.py>
- Temporal Python SDK：<https://github.com/temporalio/sdk-python>
- Temporal event history/replay：
  <https://github.com/temporalio/documentation/blob/main/docs/encyclopedia/architecture/temporal-sdks.mdx>
