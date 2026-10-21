# STB 架构与执行边界

STB 让人和 Agent 共用同一个真实 tmux pane。Terminal/SSH 仍是人的操作界面，Bridge 是本地控制面，不创建模型专属隐藏 Shell。

```text
Codex → MCP ──────────┐
                      ├→ Bridge → 同一个 tmux pane → Shell / SSH / 程序
ChatGPT → RDC Adapter ┘                 ↑
                                  人工直接操作
```

## 组件职责

| 组件 | 负责 | 不负责 |
| --- | --- | --- |
| tmux | session/pane、真实输入输出、scrollback、client 按键 | 模型推理和业务批准 |
| Bridge Core | Pane ACL、任务状态、内部授权计数、事件顺序、去重、等待、审计 | 远程可达性或目标环境安装 |
| MCP | 工具发现、结构化参数、取消观察、响应整形 | 第二套执行状态机 |
| RDC Adapter | 设备通道上的发现、stdin JSONL 映射 | 直接操作 tmux 或复制权限逻辑 |
| 模型 | 理解任务、制定命令、判断证据和风险 | 指定内部授权计数或绕过人工中断 |

## 三类操作

支持纯 `(END)` 及 `lines 1-N/N (END)` 状态栏。远端 less -X 可用仍开启的应用键盘模式替代 alternate-screen 证据，仍须同时满足已知分页命令、SSH 前台进程和反色视频状态栏；不放宽为任意 END 文本匹配。分页周期也追踪应用键盘模式的退出/重新进入。

分页退出按独立画面周期去重：只消费有序新增字节中的 alternate-screen 进入/退出序列（支持分段序列），退出后重新进入才开启下一周期。同一周期的重复 END 或重绘最多发送一次 q，同一任务可以处理多个周期。无法确认新周期时不连续猜测发键。

Core 对当前任务输出中的 `(END)` 做保守分页识别：本机前台进程组确认包含 less/more 时，自动输入一次 q，继续等待提示符。远端分支要求 SSH/mosh-client 前台进程、已知 Git/systemctl 分页命令、仍开启的 alternate screen 和反色视频 `(END)` 同时成立；明确指定 PAGER、编辑器、命令替换等不自动处理。这是有界启发式，不等于远端进程身份认证。记录 Agent 审计，不撤销租约，不自动标记完成。证据不足则返回 pager_unconfirmed，不发键；未到末尾不自动翻完整输出。不改全局配置或目标环境，不增加模型参数。

开始与 Agent 中断标记通过同一 tmux control 连接的字面命令响应交付，不依赖瞬时客户端消息。开始确认后清除 pending；5 秒仍未确认时返回 command_start_unconfirmed，保留执行占用并禁止自动重发，不从后来的屏幕快照臆测完成。

观察读取有界历史/增量，不申请写权，也不抢占其他执行任务。run 输入单行可见命令并返回 job；交互和中断只使用 job ID。session 管理属于独立、显式启用的能力。

模型只见任务契约，内部 lease/generation 仍严格存在，不能因隐藏字段而放宽。当前工具映射见 [模型接口](model-tasks.md)，不从历史 API 复制调用。

## 任务状态与人工事件

命令开始、终端输出、人工 Ctrl+C 进入同 pane 的有序事件流，以 epoch/sequence/job/内部授权关联。

- 任务正在执行时人工 Ctrl+C 取消旧执行链、唤醒等待；后续输出不能把它改回正常完成。
- 提示符已返回则归入结束；空闲按键不撤权。提示符匹配仍是启发式，不提供可信退出码。
- 无换行输出可能与提示符粘连：有序输出中的 readline 输入模式开启边界可辅助隔离提示符，仍须匹配已知提示符；纯文本后缀不作为新增完成依据。已确认提示符用于下一任务基线，避免粘连输出污染后续识别。未输出该边界的 Shell 不因此获得可靠的无换行检测；程序也可模拟终端序列，此机制不是可信退出协议。
- 已确认提示符保存在独立的 pane_prompts 状态中，清理 jobs 时保留；重启后仅在当前画面后缀、宿主进程类型一致时复用。无缓存的首条任务可在明确 readline 边界恢复污染基线末尾已有的完整 user@host:path 提示符；不接受任意后缀、不同主机或不完整提示符。
- 交互提示、观察超时和策略检查点不自动等于任务结束。
- 事件流断开或缺序进入需检查状态，不猜测成功或恢复写入。
- Agent job interrupt 不产生 Human 来源事件；旧 job 不得控制新 job。

新明确 run 按 Core 本地接收顺序内部授权；中断前旧调用及被取消调用的后续步骤不能续权。新调用不等于可以越过高风险批准或用户原任务范围。

## 去重与等待

逻辑请求在终端副作用前持久预留，执行回执关联 job。同 ID 重试观察原任务，不再次输入；冲突、容量满或崩溃不确定状态拒绝盲目重放。

run 的执行部分只做一次，观察窗口可重复。Core 在本地等待状态变化，MCP 取消和 RDC 采集超时只结束观察，不发送 Ctrl+C。详细步骤见 [Run](terminal-run.md) 和 [传输与去重](command-transport.md)。

## 上下文、持久化和恢复

tmux 保存原始历史；Bridge 先裁剪、去回显和折叠重复，只返回判断所需的有界输出，见 [上下文策略](ai-context-policy.md)。长期操作知识进入项目文档，不靠完整 scrollback 维持。

daemon 状态保存会话映射、任务和去重等；重启恢复撤销旧 ACTIVE 授权，不终止 tmux 进程。旧 cursor、运行状态和 server 身份需重新校验，不能把历史 pane/PID 当常量。运行能力以 bridge_info 为准，源文件更新不等于进程重载。

## 明确不做

不注入目标脚本/marker，不假设远端 Python 或特定 Shell，不自动执行真正多行，不以模型自觉替代安全校验。高风险仍需人工批准；[Exclusive Mode](stb-rdc-exclusive-mode.md)不等于宿主已实现能力硬隔离。

开发从 [代码地图](../development/code-structure.md) 进入，验收见 [验证目录](../validation/README.md)，未完成能力见 [路线图](../roadmap.md)，设计演进见 [历史目录](../history/README.md)。

## 历史浏览与应用输入

tmux copy-mode 是人的历史查看界面，不是 STB 命令输入目标。Core 的文本、提交回车和常用控制键通过独立命名、消费即删除的 paste buffer 直接送入 pane，不退出 copy-mode，不覆盖人的剪贴板，不启用 bracketed-paste 包装；不向目标环境注入脚本。提交与 Agent 中断仍在同一 control connection 中先记录有序来源事件，再输入。

人工 Ctrl+C 在 root、copy-mode 和 copy-mode-vi 中均保留 Human 事件来源；只有执行期间触发撤销。Agent Ctrl+C 不撤销授权，仍须确认提示符返回。浏览历史可与执行并行，但不保证人和模型同时编辑同一命令行的安全。尚未提供直接字节编码的特殊键在 copy-mode 下明确拒绝，而非误操作历史界面；普通模式继续使用 tmux 自身编码。此机制完全位于内部，不增加模型工具参数。
