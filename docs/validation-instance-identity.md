# Daemon 单实例与 tmux Server Identity 验证

日期：2026-09-20  
状态：核心 PoC 验证通过

## 验证目标

- 同一份持久 state 同时只能由一个 Bridge daemon 持有。
- tmux server 重建后，即使 socket 名和 pane ID 被复用，也不能加载旧
  lease 状态。
- 身份校验失败时 fail-closed，不创建 Control socket，不接受动作。

## 实现边界

Bridge 对 state 文件的专属 `.lock` 文件持有非阻塞 `flock` 锁。第二个
daemon 获取失败时立即以 `INSTANCE_ALREADY_RUNNING` 退出。

Bridge 在 tmux global environment 中维护
`SHARED_TERMINAL_BRIDGE_SERVER_ID=<uuid>`，并把 UUID 写入 state。启动时如果
state 中的 UUID 与当前 tmux server 不一致，以
`STATE_TMUX_SERVER_MISMATCH` 拒绝启动。

## 实测步骤

PoC 使用隔离的 `instance-identity-poc` tmux socket：

1. 启动第一个 daemon，为 `%0` 获取 generation 1 lease。
2. 用同一 state 启动第二个 daemon，确认被单实例锁拒绝。
3. 停止第一个 daemon，销毁并以同名 socket 重建 tmux server。
4. 确认新 server 再次分配 `%0`，但 server UUID 已变化。
5. 使用旧 state 启动替代 daemon，确认在对外服务前被身份校验拒绝。

## 实测结果

9 项检查全部通过：

```text
state_has_server_identity
second_daemon_rejected
second_error_is_singleton
second_created_no_control_socket
pane_id_reused_for_test
new_tmux_server_has_new_identity
replacement_daemon_rejected
replacement_error_is_identity_mismatch
old_generation_remains_only_in_old_state
```

结论：`tmux socket name + pane_id` 不再被当作足够的执行现场身份。旧
generation 1 只保留在旧 state 中，不会因为新 server 重用 `%0` 而生效。

## 自动回归

```bash
python3 -m unittest tests/test_instance_identity_baseline.py
```

## 下一步

在真实日常 tmux server 上进行人工验收：只授权指定测试 pane，验证正常
Observation、lease 动作、真人 `Ctrl+C` 撤销和原 binding 恢复，然后再决定
MCP 封装边界。
