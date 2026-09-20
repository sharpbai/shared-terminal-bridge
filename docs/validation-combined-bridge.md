# 合并本地 Bridge 端到端验证

日期：2026-09-20  
状态：原型端到端验证通过

## 验证范围

将此前单独验证的四个模块合并到同一个 daemon：

1. Observation API。
2. Per-client active pane resolution。
3. Unix socket Human Event。
4. Pane-scoped Execution Lease 与 Action Guard。

端到端 PoC：

```text
poc/combined_bridge.py
```

隔离资源：

```text
tmux socket    = combined-bridge-poc
control socket = /tmp/combined-bridge-control.sock
event socket   = /tmp/combined-bridge-events.sock
```

## 自动检查结果

```json
{
  "inventory_ok": true,
  "active_client_ok": true,
  "authorized_read_ok": true,
  "authorized_state_ok": true,
  "unauthorized_denied": true,
  "private_content_not_leaked": true,
  "binding_installed": true,
  "active_action_allowed": true,
  "agent_interrupt_not_revoke": true,
  "human_event_revoked": true,
  "stale_action_denied": true,
  "allowed_action_reached_pane": true,
  "stale_action_absent": true,
  "audit_complete": true
}
```

## Lease 结果

```json
{
  "pane": "%0",
  "generation": 1,
  "state": "REVOKED",
  "issued_at": "2026-09-20T12:35:32.606+08:00",
  "revoked_at": "2026-09-20T12:35:32.626+08:00",
  "event_seq": 1
}
```

旧 generation 的响应：

```json
{
  "ok": false,
  "error": {
    "code": "EXECUTION_LEASE_INVALID",
    "pane": "%0",
    "generation": 1
  }
}
```

## Audit

```text
SERVER_START
LIST
ACTIVE
READ
STATE
ACCESS_DENY
BINDING_INSTALL
LEASE_ACQUIRE
TYPE
KEY
AGENT_INTERRUPT
HUMAN_INTERRUPT
LEASE_REVOKE
ACTION_DENY
```

## 内容验证

- 有效 generation 写入的 `COMBINED_ALLOWED_ACTION` 出现在 pane history。
- 被撤销 generation 请求的 `COMBINED_STALE_ACTION` 不存在于 pane history。
- 未授权 pane 的 `COMBINED_PRIVATE_PANE` 不存在于 Bridge 可见响应。

## Human Event 说明

本次合并测试通过 datagram 直接注入结构化 Human Event，以验证 daemon 内部的
端到端状态连接。物理按键 → tmux binding → datagram 的链路已经在前序
[Unix Socket Human Event 验证](validation-unix-socket-events.md) 中由真人操作
验证通过。

## 结论

```text
client identity
  → exact pane
  → ACL
  → observation
  → execution lease
  → guarded action
  → Human event
  → lease revoked
  → stale action denied
```

以上链路已在一个保持状态的本地 Bridge daemon 中贯通。

## 下一步

在接入正常 tmux 与 MCP 前，优先补齐：

1. binding 原配置备份、卸载和恢复。
2. ACL 与 generation 的本地持久化。
3. daemon 身份与单实例锁。
4. event 去重、乱序与重启恢复。
5. CLI 端到端人工验收，再封装 MCP tools。

## 回归基准

本次端到端结果已固化为 v1 基准：

```text
tests/baselines/combined_bridge_v1.json
```

自动测试：

```text
tests/test_combined_bridge_baseline.py
```

基准固定：

- 14 个检查项的名称和结果。
- 最终 lease 状态必须为 `REVOKED`。
- stale action 必须返回 `EXECUTION_LEASE_INVALID`。
- Audit 必须包含完整关键动作集合。

运行：

```bash
python3 -m unittest tests/test_combined_bridge_baseline.py
```

如果未来有意修改协议或检查项，应新增 v2 baseline，而不是直接放宽 v1。
