# Daemon 异常退出与持久状态恢复验证

日期：2026-09-20  
状态：核心 PoC 验证通过

## 验证目标

Bridge daemon 被 `SIGKILL` 后：

- 崩溃前的 `ACTIVE` lease 不得在重启后复活。
- generation 必须保持单调递增。
- stale generation 必须继续被拒绝。
- 原 tmux binding 快照必须跨进程保留并可恢复。
- state 文件权限必须保持 `0600`。

## 持久状态

state schema v1 保存：

```json
{
  "schema_version": 1,
  "tmux_socket": "crash-recovery-poc",
  "generations": {},
  "leases": {},
  "binding": {
    "snapshot_taken": true,
    "installed": true,
    "original": "bind-key ..."
  }
}
```

写入采用同目录临时文件、`fsync`、`os.replace` 原子替换，并在替换后再次确认
权限为 `0600`。

## 实测状态转换

崩溃前：

```text
pane=%0 generation=1 state=ACTIVE
```

Bridge 被强制终止后重启，自动恢复为：

```json
{
  "generation": 1,
  "pane": "%0",
  "state": "REVOKED",
  "revoke_reason": "daemon_restart"
}
```

使用 generation 1 的后续动作返回 `EXECUTION_LEASE_INVALID`。重新授权得到
generation 2，而不是重新从 1 开始。

## Binding 恢复

- daemon 崩溃时 Human binding 仍留在 tmux server。
- 新 daemon 从 state 文件恢复原 binding 快照和 installed 状态。
- 调用恢复后，自定义原 binding 被精确恢复。

## 自动检查

11 项检查全部通过：

```text
state_written_before_crash
state_mode_0600_before
binding_snapshot_persisted
human_binding_survived_crash
active_lease_revoked_on_restart
stale_generation_denied
binding_snapshot_recovered
original_binding_restored
generation_monotonic_after_restart
state_mode_0600_after
state_records_generation_2
```

## 结论

```text
daemon crash
  → persisted ACTIVE lease
  → startup fail-closed conversion
  → REVOKED(reason=daemon_restart)
  → stale action denied
  → new generation remains monotonic
```

daemon 异常退出不会重新获得此前的执行权限，也不会丢失用户原 binding 的恢复能力。

## 尚未验证

- state JSON 损坏、截断或 schema 不支持时的恢复界面。
- state 文件所在磁盘不可写或空间耗尽。
- audit 的持久化与 crash recovery。
- 正常 shutdown 是否应自动恢复 binding。

## 下一步

单实例锁、tmux server identity 校验和 pane ID 复用隔离已完成，详见
[单实例与 tmux Server Identity 验证](validation-instance-identity.md)。下一步进入
真实日常 tmux server 的受限人工验收。
