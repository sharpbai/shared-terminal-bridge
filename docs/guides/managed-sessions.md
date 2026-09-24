# 托管 tmux Session 与 stb 快捷命令

## 启用 Bridge 和 MCP

Bridge 必须显式允许托管 session：

```bash
python3 bridge/local_bridge.py serve \
  --tmux-socket default \
  --allow-session-management
```

MCP server 增加对应工具：

```bash
python3 mcp_server/server.py \
  --bridge-socket /tmp/shared-terminal-bridge.sock \
  --enable-actions \
  --enable-session-management
```

MCP 可调用：

```text
terminal_session_list
terminal_session_create {name, cwd}
terminal_session_stop {name}
```

`terminal_session_create` 创建的 session 会写入 tmux user options：

```text
@shared_terminal_managed=1
@shared_terminal_id=<uuid>
@shared_terminal_created_at=<timestamp>
```

首个 pane 自动加入 Bridge 动态 ACL。停止 session 时移出 ACL，并撤销该 pane
的 ACTIVE lease。

创建时还会显式追加托管配置：

```text
history-limit 100000
mouse on
```

鼠标配置使用 session 作用域。由于 tmux 在 pane 创建时固化 `history-limit`，Bridge 会在
创建首个托管 session 前将当前 tmux server 的全局 `history-limit` 设为 100000。因此已有
普通 pane 不会改变，但同一 server 此后新建的普通 pane 也会继承 10 万行历史。
这样可以保证托管 session 的初始 pane 和后续 window 都真实获得 10 万行，而不是只显示
一个创建后才写入、对现有 pane 无效的 option。
`stb list` 和 `stb info` 会返回实际 `history_limit` 和 `mouse` 值。

## 一键进入

MCP 创建 session 并返回 `name` 后，在项目目录执行：

```bash
./stb enter SESSION_NAME
```

- 当前不在 tmux 中：执行 `tmux attach-session`。
- 当前已在 tmux 中：执行 `tmux switch-client`。
- 目标没有 managed 标记：拒绝进入，避免名称输错时切换到普通 session。

如需在任意目录使用 `stb`，可将项目的 `bin` 目录加入 `PATH`，或自行建立
指向本项目 `stb` 的符号链接。

## 手工管理命令

```bash
./stb list
./stb list --json
./stb create NAME --cwd /absolute/path
./stb create NAME --cwd /absolute/path --enter
./stb info NAME
./stb panes NAME
./stb enter NAME
./stb lease NAME
./stb release NAME GENERATION
./stb approvals
./stb approvals --status PENDING
./stb approve REQUEST_ID
./stb reject REQUEST_ID
./stb jobs
./stb jobs --state RUNNING
./stb job JOB_ID
./stb waits
./stb cancel-wait WAIT_ID
./stb wait JOB_ID
./stb watch JOB_ID
./stb interrupt JOB_ID
./stb stop NAME
```

`stb create` 发现默认 Bridge socket 不存在时会自动在后台启动 daemon，因此无需先手工
执行 `bridge/local_bridge.py serve`。后台进程可通过以下命令管理：

```bash
stb daemon start
stb daemon status
stb daemon logs
stb daemon stop

# 查询持久化的 tmux/STB 操作历史
stb history <会话名称> --limit 100
```

默认运行文件：

```text
/tmp/shared-terminal-bridge.sock
/tmp/shared-terminal-events.sock
/tmp/shared-terminal-bridge-state.json
/tmp/shared-terminal-bridge.pid
/tmp/shared-terminal-bridge.log
```

如果 tmux server 尚不存在，自动启动会创建一个短暂 bootstrap session；目标托管 session
创建成功或失败后都会清理 bootstrap。

`create` 默认通过 Bridge 创建，以便同步动态 ACL。`stop` 默认也通过
Bridge，以便移除 ACL 并撤销 lease。

Bridge 不可用且确实需要紧急停止时：

```bash
./stb stop NAME --direct
```

`--direct` 仍只能停止带 managed 标记的 session。Bridge 下次启动时会清理
已不存在的托管 session 状态。

## 安全边界

- 普通 tmux session 不会出现在 `stb list`。
- `stb enter/stop/info/panes/lease/release` 均拒绝未标记 session。
- MCP session management 默认不注册，必须显式启用。
- 创建 session 不等于取得 execution lease；MCP 仍不暴露 lease acquisition。
- session 名限制为 1–64 位字母、数字、`.`、`_`、`-`。

## 验证

```bash
./poc/managed_session_end_to_end.py
python3 -m unittest tests/test_stb_cli.py
```

端到端测试已覆盖 MCP create、动态 ACL、`stb list/info/panes/lease/release/stop`、
普通 session 防误删和审计链。
