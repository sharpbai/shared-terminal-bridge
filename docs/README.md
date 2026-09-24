# Shared Terminal Bridge 文档

先按目的选择入口，不需要顺序阅读全部文档。

## 使用

- [快速上手与日常管理](guides/getting-started.md)
- [托管 tmux Session 与 `stb` 命令](guides/managed-sessions.md)

## 原理与接口

- [高层架构](reference/architecture.md)
- [MCP Server 与工具语义](reference/mcp-server.md)
- [AI Context Policy 与 Terminal Task Block](reference/ai-context-policy.md)
- [STB-RDC Exclusive Mode](reference/stb-rdc-exclusive-mode.md)

## 开发与验证

- [代码结构与修改入口](development/code-structure.md)
- [测试分层与运行环境](development/testing.md)
- [验证与回归索引](validation/README.md)
- [当前路线图](roadmap.md)

## 历史资料

这里保存早期方案和已完成调研，仅用于理解演进过程，不作为当前用法依据。

- [Bridge API v0.1](history/api-v0.1.md)
- [本地 Bridge 原型](history/local-bridge-prototype.md)
- [模型编排轮数调研与实施规划](history/model-orchestration-research-and-plan.md)
- [2026-09 项目演进记录](history/project-evolution-2026-09.md)

## 组织规则

- 当前使用方式进入 `guides/`，系统语义和接口进入 `reference/`。
- 开发入口进入 `development/`，可复现证据进入 `validation/`。
- 已被替代的设计和完成后的调研进入 `history/`。
- 一个主题只维护一个当前事实来源；概览页只链接，不复制正文。
