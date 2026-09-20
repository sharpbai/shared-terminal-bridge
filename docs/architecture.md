# 高层架构

具体实施顺序和各阶段验收条件见 [后续路线图](roadmap.md)。

## 产品定位

Shared Terminal Bridge 服务的是“Human 主操作、Agent 旁路协作”的工作方式：

- Terminal 仍然是主要交互界面。
- 用户可以直接执行 SSH、运维命令、编辑器和交互程序。
- Codex 不要求用户复制粘贴终端内容。
- Codex 按需读取同一个 tmux pane 的历史。
- Agent 的输入能力晚于只读能力，并受授权和 execution lease 约束。

它不是一个新的 Web Terminal，也不是将 Shell 包在 Codex TUI 下面。

## 系统组件

```text
┌─────────────────────────┐     ┌─────────────────────────┐
│ Terminal                │     │ Codex                   │
│                         │     │                         │
│ Human → tmux client     │     │ task/reasoning context  │
└────────────┬────────────┘     └────────────┬────────────┘
             │                               │ MCP/local API
             ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────┐
│ tmux server             │◀───▶│ Terminal Bridge         │
│                         │     │                         │
│ session/window/pane     │     │ pane registry           │
│ history buffer          │     │ read/input/event APIs   │
│ client input key table  │     │ execution leases        │
└────────────┬────────────┘     └────────────┬────────────┘
             │                               ▲
             │ HUMAN_INTERRUPT               │ local IPC
             └──────── Human Event Layer ────┘
```

## 上下文分层

1. Terminal 短期上下文：tmux scrollback，通常读取最近数千行。
2. 当前任务上下文：Codex task 中正在处理的问题、假设和决策。
3. 长期环境上下文：本地项目文档和 AGENTS.md，不依赖 scrollback 保存。

## Human/Agent 输入分流

来源判定发生在 tmux，而不是 Terminal 模拟器：

```text
Human keyboard
  → tmux client
  → root key table
  → pane

Agent
  → Terminal Bridge
  → tmux send-keys
  → pane
```

真人 `Ctrl+C` 命中 root key binding。binding 首先把 `C-c` 原样送入当前
pane，然后异步发布事件。Agent 的 `send-keys` 直接写入 pane，不经过 client
key table，所以不会产生 Human 事件。

这里识别的严格含义是“来自 tmux client 的输入”和“通过 Bridge 注入的输入”。
它不是操作系统级的人员身份认证。

## Execution Lease

未来每次允许 Agent 连续操作 pane 时创建 lease：

```json
{
  "pane": "%3",
  "generation": 42,
  "state": "ACTIVE"
}
```

收到对应 pane 的 `HUMAN_INTERRUPT` 后：

1. 将 lease 标记为 `REVOKED`。
2. 拒绝携带旧 generation 的后续输入。
3. 保留已有终端和任务上下文。
4. 等待用户再次明确授权，不自动重试或继续下一步。

语义固定为：

```text
Human Ctrl+C ≠ command failed
Human Ctrl+C ≠ retry
Human Ctrl+C ≠ continue
Human Ctrl+C = revoke Agent execution authority
```

## 安全原则

- Human 操作优先于 Agent 操作。
- 默认只读；写入必须有明确授权。
- Human Event Layer 不保存普通按键内容。
- Bridge 崩溃不得影响用户继续使用 tmux。
- 日志失败不得阻止 `Ctrl+C` 到达 pane。
- pane、client、lease generation 都必须显式传递，避免“当前窗口”歧义。

## 实施阶段

### Phase 0：输入来源 PoC

已完成：tmux client `Ctrl+C` 与 `send-keys C-c` 来源分流。

### Phase 1：只读 Bridge

- pane discovery
- active/selected pane resolution
- bounded `capture-pane`
- structured terminal context

### Phase 2：Human Event IPC

- 文件日志替换为 Unix domain socket
- 结构化事件 schema
- 重连、顺序号和消费者确认

### Phase 3：受控输入

- execution lease
- command/input API
- Human interrupt revocation
- stale generation rejection

### Phase 4：命令事件

- command start/exit
- exit code
- prompt/host/current directory
- 输出区间与命令关联
