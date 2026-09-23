# 快速上手与日常管理

本文集中记录 Shared Terminal Bridge 的安装、启动、会话管理和常见故障处理。设计原理见[高层架构](architecture.md)，MCP 工具细节见[最小 MCP Server](mcp-server.md)。

## 运行要求

- macOS 或 Linux
- Python 3
- tmux
- 本地 Unix domain socket

Bridge 和 MCP adapter 没有第三方 Python 运行时依赖。

## 获取项目

```bash
git clone https://github.com/sharpbai/shared-terminal-bridge.git
cd shared-terminal-bridge
./stb --help
```

仓库根目录的 `stb` 会转发到 `bin/stb`。需要全局调用时，可以把 `bin` 加入 `PATH`，或建立指向仓库根目录 `stb` 的符号链接。

## 最短可用流程

创建托管 session 并立即进入：

```bash
./stb create disk-check --cwd /absolute/path --enter
```

`stb create` 会在默认 Bridge socket 不存在时自动启动后台 daemon。若 tmux server 尚未运行，Bridge 会创建并清理一个短暂的 bootstrap session。

创建出的 session 带有 managed 标记，首个 pane 会加入动态 ACL，并启用：

```text
history-limit 100000
mouse on
```

退出 tmux 后再次进入：

```bash
./stb enter disk-check
```

- 当前不在 tmux 中时，使用 `attach-session`。
- 当前已在 tmux 中时，使用 `switch-client`。
- 目标没有 managed 标记时拒绝进入，避免误操作普通 session。

## Daemon 管理

```bash
./stb daemon start
./stb daemon status
./stb daemon logs
./stb daemon stop
```

默认运行文件：

```text
/tmp/shared-terminal-bridge.sock
/tmp/shared-terminal-events.sock
/tmp/shared-terminal-bridge-state.json
/tmp/shared-terminal-bridge.pid
/tmp/shared-terminal-bridge.log
```

需要前台调试时，可以显式运行：

```bash
python3 bridge/local_bridge.py serve \
  --tmux-socket default \
  --allow-session-management
```

## 会话和 pane

```bash
./stb list
./stb list --json
./stb create NAME --cwd /absolute/path
./stb create NAME --cwd /absolute/path --enter
./stb info NAME
./stb panes NAME
./stb enter NAME
./stb stop NAME
```

正常情况下使用 `stb stop NAME`，让 Bridge 同时移除 ACL 并撤销 lease。Bridge 不可用且确实需要紧急停止时，可以执行：

```bash
./stb stop NAME --direct
```

`--direct` 仍只允许停止带 managed 标记的 session。

## 租约与人工授权

本地管理员可以显式授予和释放执行租约：

```bash
./stb lease NAME
./stb release NAME GENERATION
```

创建 session 不等于取得 execution lease。真实用户在 pane 中按下 `Ctrl+C` 后，当前 generation 会被撤销；旧 generation 的后续写入会在到达 pane 前被拒绝。

长任务批准请求：

```bash
./stb approvals
./stb approvals --status PENDING
./stb approve REQUEST_ID
./stb reject REQUEST_ID
```

批准与 pane、generation、完整命令指纹、资源类型和时间预算绑定，不是长期通行证。

## Job 与等待

```bash
./stb jobs
./stb jobs --state RUNNING
./stb job JOB_ID
./stb watch JOB_ID
./stb wait JOB_ID
./stb waits
./stb cancel-wait WAIT_ID
./stb interrupt JOB_ID
```

`cancel-wait` 只取消 Bridge/MCP 的等待，不会停止终端进程。`interrupt` 才会由 Agent 向对应 pane 发送 `Ctrl+C`；真实人工 `Ctrl+C` 还会额外触发 Human Override。

## 查看交互历史

```bash
./stb history disk-check --limit 100
```

tmux/STB 交互历史默认以 `0600` JSONL 保存到：

```text
~/.local/state/shared-terminal-bridge/history.jsonl
```

历史用于审计和问题复盘，不应被当作可复用的 execution generation 来源。

## 接入 MCP

MCP host 可以用以下方式启动 adapter：

```json
{
  "command": "python3",
  "args": [
    "/absolute/path/shared-terminal-bridge/mcp_server/server.py",
    "--bridge-socket",
    "/tmp/shared-terminal-bridge.sock",
    "--enable-actions",
    "--enable-session-management"
  ]
}
```

不传 `--enable-actions` 时只注册 Observation 工具。不传 `--enable-session-management` 时不注册托管 session 的创建和停止工具。stdio 是协议通道，server 不应向 stdout 打印日志。

完整工具和授权模型见 [MCP Server](mcp-server.md)。

## 常见问题

### `No such file or directory: /tmp/shared-terminal-bridge.sock`

优先执行：

```bash
./stb daemon status
./stb daemon start
./stb daemon logs
```

`stb create` 通常会自动启动 daemon；若失败，日志会保留启动阶段的错误。

### `no server running on .../tmux-*/default`

当前版本会在创建首个托管 session 时 bootstrap tmux server。若仍出现该错误，确认 tmux 可执行文件可用，并查看 `stb daemon logs`。

### `EXECUTION_LEASE_ALREADY_ACTIVE`

观察历史不需要 lease，直接使用只读工具或 `stb history`。只有准备写入时才需要为当前 Codex 任务和用户回合取得授权。不要为了“看看输出”释放或抢占另一个有效 lease。

### 人工中断后模型还能继续吗

当前回合不能。Human Override 会撤销旧 generation，并要求模型在读取至多一次已有结果后结束当前回合。用户随后发送新的操作请求时，同一 Codex 任务可以基于新的 turn identity 重新 acquire。
