# Shared Terminal Bridge

一个本地优先、以人为主的交互式终端协同项目。

项目不创建新的“AI Terminal”，也不依赖飞书。用户继续在自己的 Terminal
和 tmux pane 中工作；Codex 作为 sidecar 读取同一份终端上下文，并且只在获得
明确授权时向同一个 pane 输入。tmux pane 是双方共享的事实来源。

## 当前目标

建立一层很薄的 Terminal Bridge，逐步提供：

1. 发现并标识 tmux session、window 和 pane。
2. 通过 `capture-pane` 读取用户正在使用的终端上下文。
3. 通过 `send-keys` 进行经过授权的 Agent 输入。
4. 在 tmux 客户端输入层识别真人 `Ctrl+C`。
5. 真人中止后，立即撤销对应 pane 的 Agent execution lease。

## 核心交互模型

```text
                    Human
                      │
                tmux client input
                      │
                      ▼
Terminal UI ──→ tmux session / pane ←── Terminal Bridge ←── Codex
                      │                         │
                      │ capture-pane            │ send-keys
                      └──── shared context ─────┘
```

数据通道与控制通道分开：

- 数据通道：`tmux capture-pane`，向 Codex 提供 scrollback/context。
- Agent 输入通道：`tmux send-keys`，只在明确授权和有效 lease 下使用。
- Human 控制通道：tmux client key binding，产生 `HUMAN_INTERRUPT` 等事件。

## 已验证

2026-09-20 已验证 tmux 能区分真人和 Agent 的 `Ctrl+C`：

- 真人按键经过 tmux client key table，正常送入 pane，并记录
  `HUMAN_INTERRUPT`。
- `tmux send-keys C-c` 直接注入 pane，不触发该事件。
- 事件中可同时得到 `pane_id` 和 `client_name`。

详见 [Human/Agent 来源分流验证](docs/validation-human-agent-source.md)。

Unix socket 结构化事件、Agent 不误报和 fail-open 验证也已通过，详见
[Unix Socket Human Event 验证](docs/validation-unix-socket-events.md)。

Execution Lease 的 `ACTIVE → REVOKED` 和 stale generation 拒绝也已通过，
详见 [Execution Lease 与 Human Override 验证](docs/validation-execution-lease.md)。

只读 pane 枚举、history/state 读取和未授权 pane 隔离已通过，详见
[Observation Bridge 验证](docs/validation-observation-bridge.md)。

多 client 的 active pane 精确解析和未知 client fail-closed 已通过，详见
[Per-client Active Pane 验证](docs/validation-active-pane.md)。

四个模块已合并进保持状态的本地 daemon，并通过端到端检查：
[本地 Bridge 原型](docs/local-bridge-prototype.md)、
[合并验证记录](docs/validation-combined-bridge.md)。

tmux root `C-c` 的原配置备份、精确恢复和无快照 fail-closed 已通过：
[Binding 生命周期验证](docs/validation-binding-lifecycle.md)。

daemon SIGKILL 后 lease、generation 和 binding 快照的 fail-closed 持久恢复
已通过：[异常退出恢复验证](docs/validation-crash-recovery.md)。

daemon 单实例锁、tmux server UUID 校验和 pane ID 复用隔离已通过：
[单实例与 Server Identity 验证](docs/validation-instance-identity.md)。

最小 stdio MCP 封装已完成：默认只读，Action 需显式启用且不暴露 lease
获取能力。Leased MCP 写入、Agent interrupt、Human Override 和 stale 拒绝的
端到端验证已通过。详见 [最小 MCP Server](docs/mcp-server.md)。

MCP 创建托管 tmux session 与本地一键进入/管理已实现：
[托管 tmux Session 与 stb 快捷命令](docs/managed-sessions.md)。

确定性的 AI Context Policy 与纯本地 `terminal_task_block` 已实现：模型优先读取 cursor
增量，Bridge 在内容进入上下文前清理终端噪声、折叠重复并强制字节/行预算；task
block 只在 daemon 内维护任务和观察元数据，每条终端命令仍必须显式提交。详见
[AI Context Policy v0.2](docs/ai-context-policy.md)。

完整的实施阶段、接口分层、Pane ACL、Execution Lease、审计、AI Context Policy
和 Command Block 演进见 [后续路线图](docs/roadmap.md)。

## 运行当前 PoC

```bash
cd '/Users/sharpbai/Documents/ChatGPT/IT网管/shared-terminal-bridge'
./poc/human_event_tmux.py
```

进入隔离测试 session 后执行：

```bash
ping 1.1.1.1
```

亲自按 `Ctrl+C`，然后按 `Ctrl+B`、`D` detach。脚本会显示事件日志。

验证 Agent 注入不会被误判：

```bash
./poc/human_event_tmux.py --agent-ctrl-c
```

下一阶段的 Unix socket 事件 PoC：

```bash
./poc/human_event_socket.py
./poc/human_event_socket.py agent-test
./poc/human_event_socket.py fail-open
```

Execution Lease 撤销 PoC：

```bash
./poc/execution_lease.py
```

只读 Observation Bridge PoC：

```bash
./poc/observation_bridge.py
```

多 client active pane 解析 PoC：

```bash
./poc/active_pane_clients.py
```

合并后的本地 Bridge 端到端 PoC：

```bash
./poc/combined_bridge.py
```

tmux `Ctrl+C` binding 备份/恢复 PoC：

```bash
./poc/binding_restore.py
```

daemon 异常退出与持久状态恢复 PoC：

```bash
./poc/crash_recovery.py
```

daemon 单实例与 tmux server identity PoC：

```bash
./poc/instance_identity.py
```

真实日常 tmux 的受限人工验收：

```bash
./poc/live_tmux_acceptance.py
```

该步骤会切换到临时 tmux window，需要真人按一次 `Ctrl+C`。详见
[真实 tmux 人工验收](docs/validation-live-tmux-acceptance.md)。

最小 MCP 端到端 PoC：

```bash
./poc/mcp_end_to_end.py
```

重跑 v1 回归基准：

```bash
python3 -m unittest discover -s tests -p 'test_*_baseline.py'
```

## 目录

```text
shared-terminal-bridge/
├── README.md
├── bridge/
│   ├── __init__.py
│   └── local_bridge.py
├── mcp_server/
│   ├── __init__.py
│   └── server.py
├── docs/
│   ├── api-v0.1.md
│   ├── ai-context-policy.md
│   ├── architecture.md
│   ├── local-bridge-prototype.md
│   ├── mcp-server.md
│   ├── roadmap.md
│   ├── validation-active-pane.md
│   ├── validation-binding-lifecycle.md
│   ├── validation-combined-bridge.md
│   ├── validation-crash-recovery.md
│   ├── validation-execution-lease.md
│   ├── validation-human-agent-source.md
│   ├── validation-instance-identity.md
│   ├── validation-live-tmux-acceptance.md
│   ├── validation-observation-bridge.md
│   └── validation-unix-socket-events.md
├── poc/
    ├── active_pane_clients.py
    ├── binding_restore.py
    ├── combined_bridge.py
    ├── crash_recovery.py
    ├── execution_lease.py
    ├── human_event_socket.py
    ├── instance_identity.py
    ├── live_tmux_acceptance.py
    ├── mcp_end_to_end.py
    ├── observation_bridge.py
    └── human_event_tmux.py
└── tests/
    ├── baselines/
    │   └── combined_bridge_v1.json
    ├── test_binding_restore_baseline.py
    ├── test_combined_bridge_baseline.py
    ├── test_crash_recovery_baseline.py
    ├── test_instance_identity_baseline.py
    ├── test_mcp_end_to_end_baseline.py
    └── test_mcp_server.py
```

## 当前边界

- 已实现本地 Bridge、execution lease 与最小 stdio MCP 封装。
- 大部分自动 PoC 使用独立 tmux socket；真实日常 tmux 受限验收已通过，
  并在退出时恢复临时 binding，不修改 `~/.tmux.conf`。
- Unix socket、execution lease 和只读 Observation 核心链路均已验证。
- 合并 Bridge、binding 恢复、异常退出持久状态、daemon 单实例、
  tmux server identity 和真实 tmux 人工验收均已通过。
- 不记录普通按键、密码、Token 或完整命令。
- 本项目与飞书、Notion 或其他云端文档系统无关。
