# STB 文档入口

按当前目的进入；日常使用不需要先读开发说明或演进记录。模型直接使用 MCP 自发现 instructions/schema。

| 目的 | 首选页面 | 接着看什么 |
| --- | --- | --- |
| 安装、启动和日常使用 | [快速上手](guides/getting-started.md) | [托管会话与 CLI](guides/managed-sessions.md) |
| 接入 Codex / MCP | [MCP 接入](reference/mcp-server.md) | [模型任务接口](reference/model-tasks.md) |
| 理解运行和安全边界 | [架构](reference/architecture.md) | [Run 内部流程](reference/terminal-run.md)、[传输与去重](reference/command-transport.md) |
| 控制上下文与交互成本 | [AI Context Policy](reference/ai-context-policy.md) | [当前路线图](roadmap.md) |
| 修改代码 | [代码地图](development/code-structure.md) | [测试分层](development/testing.md) |
| 查实际验证证据 | [验证目录](validation/README.md) | 按能力或实操基线查阅 |
| 查哪天为什么调整 | [历史与按日演进](history/README.md) | 不把旧命令当作当前接口 |

## 目录职责

- `guides/`：使用者要完成的事情，不解释实现细节。
- `reference/`：当前契约和系统原理；[Exclusive Mode](reference/stb-rdc-exclusive-mode.md)说明旁路约束及尚未实现的硬隔离。
- `development/`：代码定位、修改边界和测试环境。
- `validation/`：当前回归入口及专项验收证据；早期证据注明历史范围。
- `history/`：已完成设计、调研及 `changes/YYYY-MM-DD-topic.md` 按日记录。
- [路线图](roadmap.md)：只维护未完成工作；[CHANGELOG](../CHANGELOG.md)：已发布版本摘要。

## 维护规则

一个主题只维护一份当前说明，其他页面链接引用。日期记录归纳问题、决策、验证、发布和待办，不重复维护完整接口。跨日新建记录并互链；旧记录只补状态和后继入口。改行为时同时更新对应说明、代码导航和测试。
