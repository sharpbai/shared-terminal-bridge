# tmux Ctrl+C Binding 生命周期验证

日期：2026-09-20  
环境：macOS、tmux 3.6a、隔离 tmux server  
状态：核心 PoC 验证通过

## 验证目标

Bridge 安装 Human `Ctrl+C` binding 前必须保存用户原配置，并能安全恢复：

1. 原本存在自定义 binding 时精确恢复。
2. 原本不存在 binding 时恢复为不存在。
3. 重复安装不覆盖首次快照。
4. 没有快照时拒绝恢复，不猜测默认配置。
5. 安装和恢复进入 Audit Log。

## 自定义 binding 场景

测试前配置：

```tmux
bind-key -T root C-c display-message ORIGINAL_CTRL_C_BINDING
```

Bridge 保存 `list-keys -T root C-c` 的规范化输出，然后安装 Human Event
binding。安装后确认 binding 包含 `emit-event`。

调用 `restore_human_binding` 后：

```tmux
bind-key -T root C-c display-message ORIGINAL_CTRL_C_BINDING
```

恢复结果与安装前快照逐字相同。

## 原本无 binding 场景

测试先执行：

```tmux
unbind-key -T root C-c
```

Bridge 快照记录为 `None`。安装 Human Event binding 后调用恢复，最终
`list-keys -T root C-c` 再次返回不存在。

## Fail-closed

快照已被成功恢复并清除后，再次调用 `restore_human_binding`：

```json
{
  "error": {
    "code": "BINDING_SNAPSHOT_NOT_FOUND"
  }
}
```

Bridge 不尝试猜测或写入默认 binding。

## 自动检查

```json
{
  "original_binding_detected": true,
  "human_binding_installed_over_custom": true,
  "custom_snapshot_reported": true,
  "custom_binding_restored_exactly": true,
  "absent_binding_detected": true,
  "human_binding_installed_over_absent": true,
  "absence_restored": true,
  "double_restore_fail_closed": true,
  "audit_complete": true
}
```

结果：

```text
PASS: custom C-c binding was restored exactly.
PASS: an originally absent binding was restored as absent.
PASS: restore without a snapshot failed closed.
```

## 当前边界

快照目前保存在 daemon 内存中。如果 daemon 在安装后、恢复前崩溃，新的 daemon
无法知道原 binding。因此该实现还不能直接接入日常 tmux server。

## 下一步

将以下状态持久化到权限为 `0600` 的本地 state 文件：

- tmux server identity。
- 原始 binding 快照及其 hash。
- binding 是否处于 installed 状态。
- 每个 pane 的 generation 上限和 lease 最终状态。

daemon 启动时应检测未完成的 binding installation，并提供显式恢复，而不是自动
覆盖当前配置。

