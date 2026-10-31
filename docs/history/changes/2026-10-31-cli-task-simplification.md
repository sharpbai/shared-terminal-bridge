# 2026-10-31：CLI 任务入口、发现与文档收口

本页记录当天调整，随 STB v0.18.0 / STB-RDC v0.4.0 发版整理；发布摘要见 CHANGELOG。日常用法以[模型任务接口](../../reference/model-tasks.md)和[Run 说明](../../reference/terminal-run.md)为准；[CHANGELOG](../../../CHANGELOG.md)记录待发布摘要。

## 为什么调整

不断叠加的授权、审批、等待诊断、传输参数与程序输入入口，让模型需要理解大量无关流程。目标是让模型通过可见的非交互 CLI 任务执行意图，Core 保留确定性的权限和中断控制，人继续使用原有终端。

## 最终决定

| 主题 | 当前源码行为 |
| --- | --- |
| Agent 与人工管理 | stb 面向观察和任务；stb-manage 承担会话生命周期、daemon、历史、cleanup-tasks 与 MCP 配置 |
| 发现 | bootstrap 首次只读观察，context 后续刷新；已知名称直接解析，不先全量列举 |
| 参数传输 | run --text 或 --base64 PAYLOAD；无 stdio/stdin 输入模式，MCP 继续传原文 text |
| Base64 | 复杂原文用本机可靠工具按 UTF-8 编码并解码回验；不手算、不添加换行，解码后仍校验非空、单行、控制字符与 65536 字节边界 |
| 自动化范围 | 删除 CLI input 与 MCP terminal_input_job 暴露；只提交非交互 CLI 任务，交互提示/TUI 交人工，不用新 run 伪装回复 |
| 等待 | CLI 默认画面 40 行，观察 60 秒；wait --seconds 60，可设 1–600 秒；不改变 Core/MCP 原有观察上限或任务预算 |
| 风险与授权 | 删除资源强制审批及批准凭证；高风险通过对话确认，内部授权、ACL、任务互斥、请求去重、人工中断仍由 Core 强制 |
| 人工中断 | 只在命令执行期间取消旧链；bootstrap 画面不携带旧租约 execution 历史，不清除原任务状态；任务结果仍返回权威中断状态 |

Base64 不是加密，体积约增加三分之一，不能据此承诺任意启动参数或目标终端输入长度。终端复制的折行须先核对，编码不负责修复命令。

## 两条路径不混用

Codex 在本机直接调用 stb 或 MCP，不需要 RDC 中转。STB 通用 instructions 不加入 RDC 参数。ChatGPT 的工具选择、deviceId、PID、结果收集等只由 [STB-RDC 当日记录](../../../../shared-terminal-bridge-rdc/docs/history/changes/2026-10-31-cli-workflow.md)和对应 workflow 说明。

STB CLI bootstrap 目前仍保留其自身的能力检查和 bootstrap_result 等元数据；今天移除 ready/协议协商的改动针对 STB-RDC，不能将两边输出误写成完全相同。两边均不再输出 bootstrap context.execution。

## 验证范围

- 最终移除 input 后：Core 默认测试 196 项，其中 13 项跳过；Adapter 40 项通过，编译和 diff 检查通过。
- 同日前阶段：2 项 Adapter→隔离 Unix socket→Core 回归、16 项宿主机隔离 tmux 回归通过；验证文本/Base64 逐字一致、响应丢失不重放及既有终端行为。
- 后续文档整理没有重新执行生产命令或所有宿主机测试。不将 mock/参数模板检查说成真实 ChatGPT/RDC 业务全链路验收；远端环境、启动长度与目标 Shell 限制仍需专用场景验证。

## 加载与待办

发版前已按最终源码重新验证：Core 196 项默认测试（13 项跳过）、Adapter 40 项、跨仓库 socket 2 项、宿主机隔离 tmux 16 项均通过，compileall 与 diff 检查通过。该发版回归晚于上述分阶段记录，仍不等于真实 ChatGPT/RDC 业务全链路或生产实例加载验收。

当天曾按人工授权重启 Bridge，修复旧运行实例不返回 instructions 导致的发现错误，并只读验证 local-mac bootstrap 成功。之后又移除了 input 暴露并收紧 CLI-only instructions；最后一轮尚未重启 Bridge，也未确认 MCP 已重连。因此“源码已更新”不代表所有常驻服务已加载。

CLI/Adapter 每次启动读取新代码；更新 Bridge 返回的 instructions 需授权重启，MCP 工具与 instructions 需重新连接刷新。本轮整理纳入 v0.18.0 发版；Git 标签和 GitHub Release 是发布事实来源，未同步 Notion。Core 内部输入安全实现保留，不属于 Agent 输入入口。

## 文档分工

现行指南/协议写怎么用，开发地图写到哪里改；验收索引说明证据范围，路线图只保留未完成方向。本页保存当天决定，原有阶段验证与早期 TUI 方案只加历史标注，不改写成最终实现。
