# STB-RDC Exclusive Mode

> 当前版本：STB v0.16.0 / Bridge API v9 · 2026-10-19（contract 自 v0.15.0 引入）

## 问题

“分析 virga 编译失败01”暴露出一个边界漏洞：虽然终端写入已经受 STB 的 lease、generation、Human Override 和审计控制，但模型仍可调用同一 RDC 连接暴露的其他原生能力，从目标主机侧绕开 STB。

这不是单纯的 terminal-submit 问题，而是 capability-plane 问题。

## 安全不变量

- 用户明确选择 STB-RDC 后，STB 是唯一 target-host capability plane。
- RDC 只允许作为 transport/bootstrap。
- RDC 独立 filesystem/search/process/shell/edit 等能力默认拒绝。
- STB 能力不足时不得自动降级到 RDC；必须向人工申请旁路。
- 旁路批准必须 one-shot、capability-scoped，并记录原因和目标操作。
- 旁路永远不能覆盖 Human Override、lease revoke、Pane ACL 或 long-run approval。

## 人工旁路流程

当 STB 缺少完成任务所需能力时，模型必须停止并向人工报告：缺少的 STB capability、希望使用的 RDC capability、精确目标和操作、为什么 STB 路径无法完成，以及该旁路是否会读取或修改数据。

只有后续明确人工批准才可执行。批准仅对该次声明的 capability + operation 有效，执行后自动失效。新的旁路需要新的批准。

建议统一状态语义：`RDC_BYPASS_PERMISSION_REQUIRED`。

## 强制层级

当前仓库强制 STB 自身的 pane/action 边界，并通过 MCP 自发现 instructions、工具 schema 和 RDC bootstrap 声明模型侧 Exclusive Mode，不再依赖本地 routing skill。说明约束不等于宿主硬隔离；真正阻止独立 RDC tools 旁路仍需要宿主/连接器支持 capability filtering 或 policy hook。

因此分两层：当前通过 MCP 自发现契约、RDC bootstrap 与文档/回归测试，约束模型在 STB-RDC 任务中 fail-closed；最终硬隔离由 RDC/宿主根据 STB-RDC task context 隐藏或拒绝非 transport tools，仅接受带人工 one-shot approval token 的指定 bypass。

在硬隔离完成前，不把提示词约束描述成物理安全边界。

## v0.15.0 验收边界

自动化回归确认现代 `server/discover` 与旧版 `initialize` 都发布 Exclusive Mode
instructions，并明确 transport/bootstrap、one-shot bypass 和 Human Override 不可绕过。

本版能够保证的硬边界仍是 STB 自身的 Pane ACL、lease、generation、long-run
approval 和 Human Override。独立 RDC tools 是否从宿主工具列表中消失，不由 STB
进程控制，属于后续 capability filtering 工作。
