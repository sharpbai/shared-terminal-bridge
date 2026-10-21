# 2026-10-19：任务接口、自发现与 v0.16.0 发布

本记录按北京时间归档，整理跨越 10 月 18–19 日的连续调整，区分阶段过程、当前结论和后续方向。不保存原始会话、秘密或运行身份常量。前序过程见 [10 月 18 日记录](2026-10-18-state-and-transport.md)。

## 当日结论

STB v0.16.0 与 STB-RDC v0.3.0 已发布。模型只需命令、逻辑请求 ID 和 job ID，不再管理 lease/generation；授权校验仍在 Core 内部。必要用法由 MCP 自发现或 RDC bootstrap 提供，不依赖本地 STB skill。

当前事实来源：[模型任务接口](../../reference/model-tasks.md)、[Run](../../reference/terminal-run.md)、[命令传输与重试](../../reference/command-transport.md)、[MCP 接入](../../reference/mcp-server.md)。本页是当日证据，不替代这些接口文档。

## 调整脉络与落地结果

| 阶段 | 原问题 | 最终处理 |
| --- | --- | --- |
| 完成识别与中断 | 已返回提示符仍等待；空闲 Ctrl+C 误撤权 | 动态提示符和输出边界修复；以任务执行阶段判定人工撤权；开始、输出、按键进入有序事件流 |
| 自动授权 | 普通操作频繁申请租约；重启后旧授权状态阻塞新调用 | 以本地接收顺序处理新明确调用，内部换代授权；旧执行链不恢复，高风险确认保留 |
| 可靠传输 | RDC 启动 Shell 提前展开复杂命令 | Adapter 固定启动、stdin 传 JSON；Core 保持单行原文，不注入脚本，不增加目标环境假设 |
| 降低编排 | lease/submit/wait 多轮往返；模型暴露内部计数 | run 内部完成授权、提交和等待；input/interrupt 绑定原 job，审批绑定请求 ID；移除旧模型工具 |
| 自发现 | skill 与 MCP 说明重复，首次入口不清楚 | 移除项目及全局 skill；MCP instructions/schema 作为入口；CLI 提供 discover、mcp 与 usage 引导 |
| 发布固化 | 多轮修复仍处于未发布状态 | Core v0.16.0、Adapter v0.3.0 同步发版，当前文档和版本一致性检查更新 |

## 保持不变的安全边界

- 人工 Ctrl+C 只在 STB 命令执行期间取消当前执行链；空闲操作不视为接管。
- 后到的新明确调用可内部续授权，不表示允许重放旧调用的排队步骤或扩大任务范围。
- 同逻辑 ID 重试只能观察原提交，不重复输入；参数冲突或崩溃不确定状态拒绝盲目重放。
- 旧 job 不能输入或中断新 job。取消观察等待不等于停止目标进程。
- 高风险操作仍须明确批准；不以 RDC、独立 SSH 或隐藏 Shell 绕过 Core。
- 提示符返回是完成启发式，不是可信退出码或业务成功证明；真正多行执行尚未实现。

## 自发现入口

| 使用者 | 入口 | 说明来源 |
| --- | --- | --- |
| Codex / MCP 客户端 | 已全局注册的 STB MCP | instructions 和工具 schema；不先读 skill/仓库 |
| 本机 CLI 使用者 | `stb`、`stb --help` | 命令帮助顶部说明首次入口 |
| 需要机器可读导航 | `stb discover --json` | 离线能力导航，不执行任务 |
| 需要配置 MCP | `stb mcp` | 复制用全局注册指引，不自动改配置 |
| ChatGPT / RDC | `stb-rdc bootstrap SESSION` | 只读上下文、精简规则、请求模板；详见 [RDC 当日记录](../../../../shared-terminal-bridge-rdc/docs/history/changes/2026-10-19-discovery-performance-release.md) |

全局配置启动核验已返回新版自发现说明。移除 skill 不等于既有会话缓存立即刷新；旧 MCP 连接需重连。CLI 导航不能替代运行中 schema 的能力检查。

## 验证与发布证据

| 验证 | 当日最终结果 |
| --- | --- |
| Core 默认测试 | 144 项，9 项跳过，其余通过 |
| 宿主真实 tmux | 11 项通过，隔离 server，不操作业务 pane |
| Adapter | 43 项通过 |
| 编译与差异格式 | 通过 |
| GitHub CI | 两仓库分支和标签触发的检查均通过 |

阶段记录中的 123/134/140 等数量是中间快照，不是最终发布测试总数。主要覆盖任务状态、事件顺序、去重恢复、job 隔离、审批、取消等待、双路径特殊字符传输及自发现。

- Core 提交：`fb95422`；[v0.16.0 发布](https://github.com/sharpbai/shared-terminal-bridge/releases/tag/v0.16.0)。
- Adapter 提交：`cd4eb1e`；[v0.3.0 发布](https://github.com/sharpbai/shared-terminal-bridge-rdc/releases/tag/v0.3.0)。
- Bridge API 仍为 v9；新任务契约以能力字段校验，不能只按 API 数字判断兼容。
- 此前按明确授权完成过 Bridge 重启及只读能力核验；本次发版本身没有再次重启，也未中断 tmux 进程。源文件版本更新不代表运行进程已重载版本字符串。

## 后续

### 发布后：Agent Ctrl+C 的请求与结束确认

“排查 DNS 高 CPU”实操中，10:45:01 Agent 中断仅返回 accepted，随后数次新调用被旧执行任务拦截；旧 job 到 10:48:45 才按输出证据收敛。历史未保存可确认的按键后退出提示符，不能认定当时程序已经停止，也不能把发键直接当成任务结束。

补充修复将 Agent 请求来源加入同一有序流，收到提示符后以 INTERRUPTED_BY_AGENT/FINISHED 收敛，保留 ACTIVE 授权且不伪装人工事件。随后按明确要求，job 中断改为默认发键并等待提示符，可选 wait_ms，默认 600000，返回 termination_confirmed。忽略 SIGINT 或无退出证据时继续保留占用，取消只停止观察；旧交互检查点不会提前结束该等待。job input 的 C-c 共享来源记录，专用 interrupt 才负责等待。补充 ^C 无换行、keypad 模式、延迟处理 SIGINT、取消与预取消回归。该修复晚于 v0.16.0，不回写发布标签；实际加载以重启结果为准。

### 发布后的文档整理

本轮中断修复最终回归：Core 默认 153 项（9 项跳过）、隔离宿主 tmux 12 项、Adapter 45 项通过。真实隔离场景覆盖延迟处理 SIGINT、忽略 SIGINT、后续任务提示符基线和新命令占用保护。更新后仍需明确授权重启加载，不能把测试结果写成业务 daemon 已生效。

同日重新组织两仓库文档：使用、参考、开发、验证、历史分层；日期记录移入 history/changes，持久 SSH 调研移入 history/research。重写当前架构、命令传输与上下文策略，清理过期 lease/submit 模型流程；手册侧栏按层级分组。此整理是发布后的文档变更，不回写已发布标签，也不改运行代码或重启服务。

继续观察多轮编排成本；详细时间分布和未实施建议统一记录在 RDC 当日页，不在 Core 重复维护。宿主级旁路能力隔离、真正多行执行和长期故障场景仍是后续方向；当前发布不宣称这些能力已完成。
