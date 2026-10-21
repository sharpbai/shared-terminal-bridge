# Changelog

## v0.17.0 — 2026-10-21

配套 STB-RDC v0.3.1，Bridge API 保持 v9，run/job 模型入口不变。升级重启 Bridge（撤销租约、保留终端进程），重连 MCP 刷新 schema/instructions。分页判断仍是有界启发式，远端分支测试采用 SSH 进程证据回放，不宣称已覆盖所有远端 Shell。

- 新增 `stb cleanup-tasks`：默认预览，`--yes` 备份并清理未结束任务、重启 Bridge，`--pane` 限定目标；保留提示符缓存及防重放，不终止实际命令。须先确认终端空闲。
- MCP 和 RDC 自发现提示建议 Git/systemctl 禁用分页并限定输出，不修改目标全局配置。
- 本次不涉及 Terminal 保活，也不引入 Jev／小模型。SSH 登录中或输入行未就绪的提交检查尚未实现，不将其列为已修复。

- 适配 systemctl 的 `lines 1-N/N (END)` 状态栏，以及 less -X 不使用备用屏幕、仅启用应用键盘模式的远端分页；继续要求前台传输、已知命令和反色视频状态栏证据。

- 分页自动退出按独立 alternate-screen 出现周期去重，而非整个任务一次；按有序新增字节识别退出/重新进入，处理分段转义序列，重复 END/重绘不再次发送 q。同一任务多分页器真实 tmux 回归通过。

- Bridge 内部识别本地及远端分页末尾并安全退出一次，继续等待提示符；证据不足明确返回需检查，不向模型新增操作步骤。开始/Agent 中断标记改用字面 control 命令响应，开始确认缺失 5 秒后有界返回且不重放。增加真实 tmux/less、SSH 证据回放及安全边界回归。

- 已确认提示符独立按 pane 持久化，不随任务清理丢失；仅在当前画面后缀和宿主进程类型一致时复用。首次无缓存且基线被无换行输出污染时，允许在明确 readline 边界恢复基线中已有的完整 user@host:path 提示符。增加任务清理、重启及冷启动回归。

- 修复无换行输出与提示符粘连造成任务持续 RUNNING：在有序输出中结合 readline bracketed-paste-enable 边界与已知提示符识别完成，保存确认后的提示符供下一任务使用；不接受任意文本后缀作为完成证据。

- 内部输入通道：滚屏 copy-mode 下命令文本、回车及 Ctrl+C 直接进入 pane，保留历史浏览位置；人工/Agent 来源、有序中断及授权语义不变。补充真实 tmux 滚屏回归，不增加模型参数。

- terminal_interrupt_job 默认发送 Ctrl+C 后事件驱动等待提示符返回，可选 wait_ms（默认 600000）；MCP 支持取消该观察，前置取消不发键。旧交互检查点不当作结束，超时/取消不释放执行占用，且不自动升级信号。

- Agent Ctrl+C 请求纳入有序事件流，提示符确认后以 INTERRUPTED_BY_AGENT 结束；中断响应区分 accepted 与 termination_confirmed，忽略信号时保留执行占用。修复远端 Shell 的 ^C 回显和 keypad 模式转义影响提示符识别；job input C-c 共享同一来源路径。

- 文档统一按 guides/reference/development/validation/history 分层；按日记录进入 history/changes，重写当前架构、传输与上下文边界，修复旧模型调用说明及手册导航。

## v0.16.0 — 2026-10-19

破坏性模型接口更新：MCP 改用 run/job ID，不兼容旧 acquire/submit/generation 工具。升级 Core 与 STB-RDC v0.3.0 后重启 Bridge，并重连 MCP 刷新工具；重启撤销旧授权但不终止 tmux 进程。Bridge API 保持 v9，以能力字段校验新版任务契约。

- CLI 新增离线 `stb discover --json` 与 `stb mcp`，提供 Agent 自发现导航、MCP 全局注册及超时配置指引；不自动修改配置或执行目标任务。

- 移除项目及全局 STB skill 入口，运行指引归入 MCP 自发现 instructions/schema；保留 Human Override、风险审批、CLI 优先和 STB-RDC 旁路约束，不要求模型先读仓库文档。

- 模型接口收敛为 run、job 输入/中断和审批请求 ID；不再发布旧租约申请、submit 和 generation 参数，默认响应隐藏内部授权元数据。Core 保留严格校验与审计；新增重启恢复、job 隔离和无计数 MCP 回归，Codex MCP 需重连刷新工具。

- 增加 receipt-scoped `terminal_run`：Core 复用/取得租约、严格提交、持久化 job 后等待；同 ID 重试只观察原 job，链内撤权不能续租。复用已有审批、取消等待和 Human Override，原 MCP 工具不变。

- 命令传输阶段一、二：MCP `terminal_submit.request_id` 与 RDC JSONL 共用 Core 持久去重；相同 ID 不重复执行或重新续租，冲突/崩溃不确定状态 fail closed。单行保持原文，控制字符与真正多行拒绝；增加双路径和隔离 tmux 回归。

- 按 Bridge 本地接收序号自动续授权：人工中断取消当前执行链，中断后新收到的命令可自动换代 generation，同回合 acquire 幂等复用；中断前的在途调用及同一 Task Block 的后续步骤不能自行恢复。调用方不能指定 receipt。耗时本身不再触发审批，高资源影响和其他高风险确认保留。

- 新提交命令将开始边界、终端输出和人工 Ctrl+C 纳入 pane 独立的 tmux control-mode 有序流，以 epoch/sequence/job/generation 驱动状态机，不再由周期 capture 与异步按键事件竞速。输出先返回提示符不撤权；按键先到则中断状态不可被后续提示符覆盖。断流/缺序进入人工检查并拒绝该 pane 的新提交。

- Human Ctrl+C 撤权由任务执行状态机控制：仅同 pane、同 generation 的 EXECUTING 任务被中断时撤权；空闲租约、已结束任务不撤权。按键前快照可将已返回提示符的陈旧任务收敛为 FINISHED；交互等待与预算检查点不等于命令结束。

- 修复重构后 Human Ctrl+C 绑定误启动 `sessions/service.py`：恢复 `local_bridge.py emit-event` 入口，并验证实际 tmux 绑定命令能够发送事件和撤销租约。

- 修复 `cd` 或 Git 分支变化后的动态提示符导致 Job 一直 RUNNING：同主机/用户前缀和提示符符号、前台进程返回及稳定画面共同提供启发式完成证据，不依赖修改目标 Shell。
- 修复长命令回显折行和 baseline 末行变化引入旧历史；任务输出在已识别返回提示符处截断。
- 增加动态提示符、误判保护、输出边界单元测试及隔离真实 tmux 验收。

## v0.15.1 — 2026-10-12

- 修复恢复旧 Codex 会话后 `CODEX_TURN_ID_UNAVAILABLE`：按每次 MCP 请求的宿主 `x-codex-turn-metadata` 解析 thread/turn 身份，与本地真实用户回合核对，不再用会话创建时间猜测租约归属。
- 请求身份缺失、矛盾或过期时拒绝授权；模型工具参数不能指定身份。保留 Human Override、generation 和长任务批准边界。
- 增加默认关闭的脱敏身份诊断及回归测试；真实恢复会话已由人工验证能够获取租约。
- 按职责重组 Bridge、MCP、CLI、测试和文档，提供小入口导航，降低人和 Agent 的局部维护成本。
- 相关项目导航加入独立 Tools 仓库。

- 增加 GitHub Actions：Python 3.11/3.12 容器安全测试，以及独立宿主 runner 的真实 tmux 集成测试。
- 为 Bridge 领域 service 增加显式依赖清单和运行时受限 `ServiceContext`，并以静态一致性测试阻止依赖静默扩张。
- 统一 Bridge/MCP 版本来源，增加当前文档、CHANGELOG、MCP metadata 和 API feature gate 的版本一致性测试。
- 修复 Linux tmux 初始托管 pane 未继承 10 万行历史上限的问题：在同一命令队列中先设置全局选项，再创建 session。

Bridge API 保持 v9。升级后需重新连接 MCP（或重启 Codex 应用）以加载身份解析修复；无需重建托管 tmux 会话。宿主元数据的信任范围是本地 Codex 及其日志，不是面对不可信客户端的密码学认证。

## v0.15.0 — 2026-09-24

- 增加 STB-RDC Exclusive Mode contract。
- 用户明确选择 STB-RDC 后，RDC 被限定为 transport/bootstrap；目标主机操作默认必须经过 STB。
- 独立 RDC filesystem/search/process/shell/edit capability 需要一次性、capability-scoped 人工旁路批准。
- 旁路不得覆盖 Human Override、lease revoke、stale generation、Pane ACL 或 long-run approval。
- modern `server/discover` 与 legacy `initialize` 发布一致的 Exclusive Mode instructions。
- 增加 Exclusive Mode 文档与自动化回归测试。
- 更新路线图，纳入 2026-09-22 至 2026-09-24 的 STB-RDC、公开文档和远程 capability-plane 演进。

限制：v0.15.0 强制 STB 自身的本地安全边界，并通过 MCP contract/routing policy 让当前客户端 fail closed；独立 RDC tools 的物理隐藏仍需要 RDC/宿主提供 capability filtering 或 policy hook。

## v0.14.0 — 2026-09-21

- Bridge API v9 增加 `terminal_program_profile`。
- 首批提供 TestDisk/PhotoRec CLI、CMD、batch 能力选路。
- 只读 TaskBlockRunner 精确支持 `fdisk -l`、`blkid -p`、TestDisk 版本探测和 `qemu-nbd --version`。
- 固化轻量 TUI 策略：CLI/CMD 优先，其次人类协同检查点，最后才是 Agent 受限 fallback。
- 完成会话 15 性能回归，验证无 TUI 日常工作流。
