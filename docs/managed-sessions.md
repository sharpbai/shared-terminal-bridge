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

配置使用 session/window 作用域，不修改普通 tmux session。同时安装
`after-new-window` hook，以便托管 session 后续新建的 window 也设为 10 万行。
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
./stb stop NAME
```

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
