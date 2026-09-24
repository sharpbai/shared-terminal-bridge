# Shared Terminal Bridge 当前路线图

本文只记录尚未完成或需要持续验证的工作。已完成阶段和决策过程见
[2026-09 项目演进记录](history/project-evolution-2026-09.md)，已发布变化见
[CHANGELOG](../CHANGELOG.md)。

## 当前基线

- STB v0.15.0 已固定 Observation、Execution Lease、generation、Human Override、Job/Wait、Task Block 和本地审计语义。
- Codex 通过本地 MCP 使用 STB；ChatGPT 通过 RDC transport 与 STB-RDC Adapter 使用同一安全状态机。
- STB-RDC Exclusive Mode 当前由工具说明和 Adapter contract 实现 fail-closed；宿主级能力隔离仍待实现。

## P0：宿主级能力隔离

- RDC/宿主在 STB-RDC context 中隐藏或拒绝非 transport 工具。
- 一次性旁路授权绑定 capability、operation、target、影响范围和有效期。
- 旁路进入统一审计，完成、失败或取消后自动恢复 Exclusive Mode。

完成标准：模型无法仅靠改换工具绕过 lease、generation、Pane ACL、Human Override 或长任务批准。

## P1：远程生命周期与恢复

- 覆盖 SSH 断线、RDC transport 断线、MCP cancellation、daemon restart 和 tmux server restart 的组合回归。
- 等待取消只结束观察；终止命令仍需独立、显式并校验 generation。
- 状态未知的写操作不自动重放，使用稳定 job/action identity 返回已有结果或要求人工确认。

完成标准：断线和重连不会重复副作用，也不会把“停止等待”误当成“停止命令”。

## P1：模型编排与性能

- 分别基准测试冷启动首检、长扫描、写入后验证、TUI fallback 和远程 STB-RDC。
- `output_complete=true` 后不再追加无意义 status；长任务优先一次本地长等待。
- 减少重复 Skill/schema 和完整 scrollback，稳定事实进入有界 task digest。
- 使用历史 Job 估计同类任务耗时，但不取消 high I/O 和 full scan 的人工批准。

完成标准：在不降低安全边界和证据质量的前提下，减少模型轮数、等待采样和上下文 Token。

## P1：Task Block 演进

- 保持 `terminal_task_block` 只记录目标、证据、风险、预算和 observation cursor。
- 写入批准只绑定单个 step，之后以独立只读 step 验证。
- 使用稳定的 `task_block_id + step_id + generation` 复用已完成结果和运行中的 Job。
- 由 Bridge 确定性检测循环、重复错误和空增量，仅在需要语义判断时唤醒模型。

完成标准：复杂任务可恢复、可审计，并且不会因为重试而重复有副作用的步骤。

## P2：轻量 TUI 与跨平台

- 继续采用 `CLI/CMD/batch → 人工协同检查点 → Agent 受限 fallback` 的顺序。
- 仅在必要时增加 expected process、screen fingerprint、changed-row snapshot 和有限按键序列。
- 不建设通用 TUI 视觉 Agent 或完整终端仿真。
- Unix/tmux 模型稳定后，评估 PowerShell/Windows 入口并复用现有控制语义。

完成标准：常见 TUI 场景降低输出和模型轮数，同时避免扩大脆弱的界面自动化范围。

## 持续工作

- 功能改动同时维护代码结构、测试、文档导览和相关验证记录。
- 新验证证据加入[验证索引](validation/README.md)，不堆入路线图。
- 已完成项目从本页移入 CHANGELOG 或演进记录，保持本页短小且只面向未来。
