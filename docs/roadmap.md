# Shared Terminal Bridge 当前路线图

本文只记录尚未完成或需要持续验证的工作。已完成阶段和决策过程见
[2026-09 项目演进记录](history/project-evolution-2026-09.md)，已发布变化见
[CHANGELOG](../CHANGELOG.md)。

## 当前基线

2026-10-31 v0.18.0 调整见[CLI 任务入口整理](history/changes/2026-10-31-cli-task-simplification.md)；仓库发布版本不等于运行实例已加载。

- STB v0.18.0 以 run/job ID 提供模型入口，授权计数留在 Core；持久去重保证同 ID 不重复执行。支持内部分页周期退出、滚屏输入隔离、提示符缓存及本地任务状态清理。
- 待处理：SSH 登录或命令行已有输入时的提交就绪检查；不能将当前提示符启发式视为可信退出码协议。终端保活配置归 Terminal 管理，不作为 STB 特判；Jev／小模型不属于本次发布。
- 普通授权按本地接收顺序处理；执行期间人工 Ctrl+C 停止旧执行链，新明确调用可续授权，高风险仍批准。开始、输出、人工按键进入有序事件流。
- Codex 通过本地 MCP 使用 STB；ChatGPT 通过 RDC transport 与 STB-RDC Adapter 使用同一安全状态机。
- STB-RDC Exclusive Mode 当前由工具说明和 Adapter contract 实现 fail-closed；宿主级能力隔离仍待实现。

## P0：宿主级能力隔离

- RDC/宿主在 STB-RDC context 中隐藏或拒绝非 transport 工具。
- 一次性旁路授权绑定 capability、operation、target、影响范围和有效期。
- 旁路进入统一审计，完成、失败或取消后自动恢复 Exclusive Mode。

完成标准：模型无法仅靠改换工具绕过内部执行授权、Pane ACL 或 Human Override；高风险通过对话取得人工同意，不引入 Core 审批状态机。

## P1：远程生命周期与恢复

- 覆盖 SSH 断线、RDC transport 断线、MCP cancellation、daemon restart 和 tmux server restart 的组合回归。
- 等待取消只结束观察；终止命令通过独立 job 中断，Core 内部校验原任务授权。
- 状态未知的写操作不自动重放，使用稳定 job/action identity 返回已有结果或要求人工确认。

完成标准：断线和重连不会重复副作用，也不会把“停止等待”误当成“停止命令”。

## P1：模型编排与性能

- 分别基准测试冷启动首检、长扫描、写入后验证、人工协同观察和远程 STB-RDC。
- `output_complete=true` 后不再追加无意义 status；长任务优先一次本地长等待。
- 不重复读取已知契约、文档和完整 scrollback，稳定事实进入有界 task digest；STB 已移除 skill 依赖。
- 使用历史 Job 估计同类任务耗时；资源标签不触发 Core 审批，高风险由模型通过对话确认。

完成标准：在不降低安全边界和证据质量的前提下，减少模型轮数、等待采样和上下文 Token。

## P1：Task Block 演进

- 内部 Task Block 保持只记录目标、证据、风险、预算和 observation cursor；不重新暴露已移除的模型计数接口。
- 风险确认明确操作范围，写入后以独立只读 step 验证；不重新引入 Core 批准凭证。
- 内部使用稳定任务/步骤身份及授权校验复用结果；模型使用返回的 job ID，不主动生成请求 ID，也不读取 generation。
- 由 Bridge 确定性检测循环、重复错误和空增量，仅在需要语义判断时唤醒模型。

完成标准：复杂任务可恢复、可审计，并且不会因为重试而重复有副作用的步骤。

## P2：人工协同与跨平台

- Agent 仅提交非交互 CLI/CMD/batch 任务，先查可用命令和非交互参数。
- 无适合 CLI 或必须操作 TUI 时由人完成，Agent 在检查点做有界观察，不提供自动文本回复或逐键 fallback。
- 可评估只读 changed-row snapshot 等降上下文成本措施，不重新开放任意按键入口。
- Unix/tmux 模型稳定后，评估 PowerShell/Windows CLI 任务入口，复用授权、中断与观察语义。

完成标准：人机协同能明确交接，减少无效画面和模型轮数，不扩大界面自动化范围。

## 持续工作

- 功能改动同时维护代码结构、测试、文档导览和相关验证记录。
- 新验证证据加入[验证索引](validation/README.md)，不堆入路线图。
- 已完成项目从本页移入 CHANGELOG 或演进记录，保持本页短小且只面向未来。
