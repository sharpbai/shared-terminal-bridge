# 快速上手与日常管理

本文集中记录 Shared Terminal Bridge 的安装、启动、会话管理和常见故障处理。设计原理见[高层架构](../reference/architecture.md)，MCP 工具细节见[最小 MCP Server](../reference/mcp-server.md)。

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

## 授权与审批

模型默认使用 terminal_run，由 Core 内部处理授权和等待，不需要逐条申请 lease 或传 generation。只有 STB 任务执行期间的人工 Ctrl+C 会取消该旧执行链；空闲操作不撤权。新明确调用按本地接收顺序处理，同一逻辑 ID 重试不重放旧命令。

本地管理员诊断时仍可显式管理内部执行租约（不是模型调用流程）：

```bash
./stb lease NAME
./stb release NAME GENERATION
```

创建 session 不等于执行命令。lease/release 属于人工诊断面，不要为了只读观察释放或抢占其他任务权限。

资源风险批准请求（单纯耗时长不自动要求批准）：

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

完整工具和授权模型见 [MCP Server](../reference/mcp-server.md)。

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

### `TERMINAL_BUSY` 或内部 `EXECUTION_LEASE_ALREADY_ACTIVE`

观察历史不需要 lease，直接使用只读工具或 `stb history`。写入被当前任务占用时先观察并协调，不释放或抢占另一个有效任务。模型只传 run/job ID，不通过回合身份或授权计数手动恢复。

### 人工中断后模型还能继续吗

旧执行链不能恢复；中断后新收到的明确 `terminal_run` 可以继续，不必先 acquire。Core 以本地接收顺序管理权限，同一 ID 重试只观察原任务。高风险仍需单独批准。
