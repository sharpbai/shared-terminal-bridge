# 真实日常 tmux 受限人工验收

日期：2026-09-20  
状态：验收通过

## 首次启动记录

Codex 从非交互式执行器启动验收器后，脚本成功定位日常 tmux server
的 `codex-test` session、`/dev/ttys022` client 和原 pane `%0`，但在 120 秒内
未收到物理 `Ctrl+C`，因此未将本次记为功能通过。

超时后已额外核验清理结果：

```text
client=/dev/ttys022 pane=%0 session=codex-test
remaining panes: %0 only
root C-c binding: absent (same as before test)
temporary files: none
```

因此超时路径的 pane 回切、binding 恢复、临时 pane 删除和文件清理已验证；
随后已从用户可见的 tmux shell 内完成功能验收。

## 最终验收结果

用户在专用 `bridge-manual` tmux session 中启动验收器，并在 ping
运行时物理按下 `Ctrl+C`。脚本返回：

```text
observation_authorized       true
other_pane_denied            true
inventory_scoped             true
agent_ctrl_c_kept_lease      true
human_ctrl_c_revoked_lease   true
stale_generation_denied      true
allowed_action_visible       true
stale_action_absent          true
audit_complete               true
```

```text
PASS: daily-use tmux acceptance test passed.
```

这证明以下链路不仅在隔离 PoC server 中成立，在日常 tmux server 的
真实 client 输入路径中也成立：

```text
authorized observation/action
  -> Agent C-c does not enter Human Event path
  -> physical C-c stops foreground process
  -> Human Event revokes current generation
  -> stale action is denied before tmux write
```

## 验收边界

本测试不再创建隔离 tmux server，而是连接用户正在使用的 tmux server。
为了不把 Agent 写入权授予现有工作 pane，验收器在当前 session 中创建
`bridge-acceptance` 临时 window，Bridge ACL 只包含该 window 的 pane。

退出时必须：

- 切回原 pane。
- 恢复测试前的 tmux root `C-c` binding。
- 删除临时测试 pane。
- 停止 Bridge daemon 并删除本次 PID 专属的 socket/state。

## 执行

必须从需要验收的 tmux client 内运行。如果当前 shell 尚未进入 tmux，
先创建专用人工 session：

```bash
tmux new-session -s bridge-manual
```

然后在 tmux 内执行：

```bash
cd '/Users/sharpbai/Documents/ChatGPT/IT网管/shared-terminal-bridge'
./poc/live_tmux_acceptance.py
```

不应在 tmux 外使用 `--origin-pane` 猜测另一个 client 的 pane：那样物理按键
可能来自不同终端，不能作为 Human Event 的有效验收。

脚本会自动切换到临时 window 并启动 `ping 1.1.1.1`。看到 ping 输出后，
需要真人在键盘上按一次 `Ctrl+C`。不需要 detach，也不需要输入其他命令。

## 自动检查

```text
observation_authorized
other_pane_denied
inventory_scoped
agent_ctrl_c_kept_lease
human_ctrl_c_revoked_lease
stale_generation_denied
allowed_action_visible
stale_action_absent
audit_complete
```

其中人工边界是：

```text
Agent send-keys C-c  -> lease remains ACTIVE
physical Ctrl+C      -> ping stops + lease becomes REVOKED
stale generation     -> denied before reaching pane
```

## 故障恢复

正常异常和 `Ctrl+C` 终止都会进入 `finally` 清理。验收器优先通过 Bridge RPC
恢复 binding；如果 daemon 已无法连接，则使用脚本启动前捕获的原 binding
直接恢复。

如果终端或整个 Python 进程被 `SIGKILL`，应先停止继续验收，根据本次
`/tmp/live-tmux-acceptance-<pid>-state.json` 中的 binding 快照恢复后再清理。

## 手工基准

本测试需要真实物理按键，不应用 `tmux send-keys C-c` 自动化替代。上述
9 项检查作为发布前手工基准，涉及 tmux binding、事件路径或 execution
lease 的改动应重跑本脚本。
