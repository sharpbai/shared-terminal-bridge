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

观察读取有界历史/增量，不申请写权，也不抢占其他执行任务。run 输入单行可见命令并返回 job；交互和中断只使用 job ID。session 管理属于独立、显式启用的能力。

模型只见任务契约，内部 lease/generation 仍严格存在，不能因隐藏字段而放宽。当前工具映射见 [模型接口](model-tasks.md)，不从历史 API 复制调用。

## 任务状态与人工事件

命令开始、终端输出、人工 Ctrl+C 进入同 pane 的有序事件流，以 epoch/sequence/job/内部授权关联。

- 任务正在执行时人工 Ctrl+C 取消旧执行链、唤醒等待；后续输出不能把它改回正常完成。
- 提示符已返回则归入结束；空闲按键不撤权。提示符匹配仍是启发式，不提供可信退出码。
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
