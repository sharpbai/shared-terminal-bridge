# 验证与回归索引

本文收纳 README 中不适合长期展开的 PoC 入口、验收记录和回归命令。所有会改变 tmux 状态或要求人工按键的验证，都应先阅读对应脚本和文档。

## 自动化回归

2026-10-21 v0.17.0 发布回归：默认测试 170 项（9 项跳过，其余通过），宿主机隔离 tmux 14 项通过；compileall、git diff --check 通过。覆盖 Agent 中断确认/取消、滚屏输入、无换行及基线缓存、开始确认、单任务多分页周期、less -X 带行数 END、本地任务清理。远端分页使用真实 tmux/less 画面与 SSH 进程证据回放，不等于真实远端全环境认证；Terminal 保活和 Jev 不纳入测试范围。

最近记录：[2026-10-19 任务接口、自发现与 v0.16.0 发布](../history/changes/2026-10-19-model-api-release.md)，含最终测试与发布证据；前序 [2026-10-18 调整过程](../history/changes/2026-10-18-state-and-transport.md)保留阶段快照，不作为当前接口。

运行完整测试：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

只重跑最早期基准：

```bash
python3 -m unittest discover -s tests -p 'test_*_baseline.py'
```

## 已验证能力

下表多数记录来自早期分阶段 PoC，保留当时的 lease/generation 和测试数量；它们是专项历史证据，不是 v0.16.0 的模型调用教程。当前模型只使用 [run/job 接口](../reference/model-tasks.md)，当前完整测试入口见 [测试分层](../development/testing.md)。

| 能力 | 结论 | 记录 |
| --- | --- | --- |
| Human/Agent `Ctrl+C` 来源分流 | tmux client 输入产生 Human 事件，`send-keys C-c` 不误报 | [来源分流](human-agent-source.md) |
| Unix socket 结构化事件 | 事件可携带 pane/client/seq，监听器缺失不阻止人工中断 | [Socket 事件](unix-socket-events.md) |
| Execution Lease | Human Override 完成 `ACTIVE → REVOKED`，旧 generation 被拒绝 | [Lease 验证](execution-lease.md) |
| Observation Bridge | 只读枚举、history/state 和 Pane ACL 隔离通过 | [Observation](observation-bridge.md) |
| Per-client active pane | 多 client 精确解析，未知 client fail-closed | [Active Pane](active-pane.md) |
| 合并 Bridge daemon | Observation、事件、lease 和写入链路端到端通过 | [合并验证](combined-bridge.md) |
| tmux binding 生命周期 | 原配置可备份、精确恢复；无快照时 fail-closed | [Binding](binding-lifecycle.md) |
| 异常退出恢复 | lease、generation 和 binding 快照持久恢复 | [Crash Recovery](crash-recovery.md) |
| daemon/server identity | 单实例锁、tmux UUID 和 pane ID 复用隔离通过 | [Instance Identity](instance-identity.md) |
| 真实 tmux 日常验收 | 观察、隔离、Agent/Human 中断和 stale action 检查通过 | [Live Acceptance](live-tmux-acceptance.md) |
| Task Block Runner | 白名单只读多步骤、逐步 lease 校验和停止条件通过 | [Task Block Runner](task-block-runner.md) |
| 程序能力选择 | CLI/CMD/batch 优先与轻量 TUI fallback 策略通过 | [Program Capability](program-capability-v9.md) |
| STB-RDC Exclusive Mode contract | modern/legacy MCP 均发布 fail-closed 与 one-shot bypass 说明 | [Exclusive Mode](../reference/stb-rdc-exclusive-mode.md) |

操作实测基线另见：

- [早期操作基线 03](baselines/live-ops-03.md)
- [Task Block 与上下文优化基线 14](baselines/live-ops-14.md)
- [当前稳定体验基线 15](baselines/live-ops-15.md)

## 独立 PoC 入口

### Human Event

```bash
./poc/human_event_tmux.py
./poc/human_event_tmux.py --agent-ctrl-c
./poc/human_event_socket.py
./poc/human_event_socket.py agent-test
./poc/human_event_socket.py fail-open
```

### Lease、观察与 pane 解析

```bash
./poc/execution_lease.py
./poc/observation_bridge.py
./poc/active_pane_clients.py
```

### daemon 生命周期与恢复

```bash
./poc/combined_bridge.py
./poc/binding_restore.py
./poc/crash_recovery.py
./poc/instance_identity.py
```

### MCP 与托管 session

```bash
./poc/mcp_end_to_end.py
./poc/managed_session_end_to_end.py
```

### 真实 tmux 人工验收

```bash
./poc/live_tmux_acceptance.py
```

该脚本需要在 tmux 内运行，或显式传入 `--origin-pane`。它会切换到临时 window，并要求真人按一次 `Ctrl+C`；不适合作为无人值守 CI。

## Human Event 手工步骤

运行 `./poc/human_event_tmux.py` 后，在隔离 session 中执行：

```bash
ping 1.1.1.1
```

亲自按 `Ctrl+C`，再按 `Ctrl+B`、`D` detach。脚本应输出 `HUMAN_INTERRUPT`。随后用 `--agent-ctrl-c` 验证 Bridge 注入的按键不会产生同类事件。

这里识别的是“来自 tmux client 的输入”与“通过 Bridge 注入的输入”，不是操作系统级人员身份认证。
