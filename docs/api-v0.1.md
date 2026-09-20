# Bridge API v0.1

Observation API 已完成核心验证。合并原型同时提供实验性的 Control/Action API，
但尚未授权接入正常日常 tmux；调用方式见 [本地 Bridge 原型](local-bridge-prototype.md)。

## 通用约束

- pane 必须使用 tmux 稳定 ID，例如 `%3`。
- 所有 pane 内容和状态读取都经过 Pane ACL。
- `terminal_list` 只返回定位所需的最小元数据，不返回 pane 内容。
- 输出必须有界；调用方不得请求无限 scrollback。
- 每次允许或拒绝的读取都写入 Audit Log。

## terminal_list

列出 Bridge 可见的 tmux pane inventory。

### 请求

```json
{
  "include_unauthorized": true
}
```

### 响应

```json
{
  "panes": [
    {
      "server": "observation-bridge-poc",
      "session": "observation-bridge-poc",
      "window": "@0",
      "pane": "%0",
      "pane_index": 0,
      "active": true,
      "authorized": true
    }
  ]
}
```

未授权 pane 只暴露定位元数据和 `authorized=false`，不返回 cwd、命令、TTY 或
history。

## terminal_read

读取指定 pane 的有界 history。

### 请求

```json
{
  "pane": "%0",
  "lines": 100,
  "include_ansi": false
}
```

### 响应

```json
{
  "pane": "%0",
  "lines_requested": 100,
  "content": "...",
  "truncated": false
}
```

### 约束

- `lines` 必须位于 `1..5000`。
- 未授权 pane 返回 `PANE_ACCESS_DENIED`，不得调用 `capture-pane`。
- v0.1 默认清理 ANSI；后续可增加显式保留模式。

## terminal_state

读取指定 pane 的当前 tmux 状态。

### 请求

```json
{
  "pane": "%0"
}
```

### 响应

```json
{
  "server": "observation-bridge-poc",
  "session": "observation-bridge-poc",
  "window": "@0",
  "pane": "%0",
  "pane_index": 0,
  "active": true,
  "current_command": "zsh",
  "cwd": "/path/to/project",
  "pid": 12345,
  "tty": "/dev/ttys001",
  "dead": false
}
```

### 约束

- 与 history 一样受 Pane ACL 约束。
- `current_command` 是 tmux 当前可观察到的前台命令，不保证等价于完整进程树。
- host、SSH 目标和 prompt 状态暂未进入 v0.1；需要 shell hook 或额外探测。

## get_active_pane

根据明确的 tmux client 解析其当前 pane。

### 请求

```json
{
  "client": "control-client-123"
}
```

### 响应

```json
{
  "client": "control-client-123",
  "session": "ops",
  "pane": "%3",
  "authorized": true
}
```

### 约束

- `client` 必须显式提供，不定义全局默认 active pane。
- 未知或已断开的 client 返回 `CLIENT_NOT_FOUND`。
- 解析 pane 不等于授予读取或写入权限；后续操作仍检查 Pane ACL。
- 多 client 可以同时解析到不同 pane。

## 错误

```json
{
  "error": {
    "code": "PANE_ACCESS_DENIED",
    "pane": "%1"
  }
}
```

v0.1 错误码：

- `PANE_ACCESS_DENIED`
- `PANE_NOT_FOUND`
- `CLIENT_NOT_FOUND`
- `INVALID_LINE_LIMIT`
- `TMUX_UNAVAILABLE`

## Audit

```text
LIST       panes=2
READ       pane=%0 lines=100
STATE      pane=%0
READ_DENY  pane=%1 reason=PANE_ACCESS_DENIED
```

Audit 默认记录动作和目标，不记录读取到的终端正文。
