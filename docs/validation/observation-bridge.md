# Observation Bridge 验证

日期：2026-09-20  
环境：macOS、tmux 3.6a、隔离双 pane session  
状态：核心 PoC 验证通过

## 验证目标

验证只读 Bridge 的三个 v0.1 接口及 Pane ACL：

1. `terminal_list` 能枚举 pane，但只返回最小定位元数据。
2. `terminal_read` 能读取授权 pane 的有界 history。
3. `terminal_state` 能读取授权 pane 的 tmux 状态。
4. 未授权 pane 在执行 `capture-pane` 前被拒绝。
5. 未授权 pane 的正文不会通过其他响应泄漏。

接口定义见 [Bridge API v0.1](../history/api-v0.1.md)。

## 测试环境

```text
tmux socket = observation-bridge-poc
session     = observation-bridge-poc
window      = @0
pane %0     = authorized
pane %1     = unauthorized
```

测试 fixture 向两个 pane 分别写入：

```text
%0 → AUTHORIZED_PANE_MARKER
%1 → PRIVATE_PANE_MARKER
```

Bridge 的 allowlist 仅包含 `%0`。

## terminal_list

实际返回两个 pane：

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
    },
    {
      "server": "observation-bridge-poc",
      "session": "observation-bridge-poc",
      "window": "@0",
      "pane": "%1",
      "pane_index": 1,
      "active": false,
      "authorized": false
    }
  ]
}
```

未授权 pane 没有暴露 cwd、当前命令、TTY、PID 或正文。

## terminal_read

对授权 pane `%0` 请求最近 100 行，成功返回包含：

```text
AUTHORIZED_PANE_MARKER
```

响应同时返回 pane、请求行数和截断状态。

对未授权 pane `%1` 请求相同操作，返回：

```json
{
  "error": {
    "code": "PANE_ACCESS_DENIED",
    "pane": "%1"
  }
}
```

实现先检查 allowlist，再调用 tmux；被拒绝请求不会执行 `capture-pane`。

## terminal_state

`%0` 实测状态：

```json
{
  "server": "observation-bridge-poc",
  "session": "observation-bridge-poc",
  "window": "@0",
  "pane": "%0",
  "pane_index": 0,
  "active": true,
  "current_command": "zsh",
  "cwd": "/Users/sharpbai/Documents/ChatGPT/IT网管/shared-terminal-bridge",
  "pid": 29634,
  "tty": "/dev/ttys029",
  "dead": false
}
```

这些字段均由 tmux format 读取，不通过解析屏幕文本猜测。

## 内容隔离

PoC 将 inventory、授权 read、授权 state 和拒绝响应整体序列化，再检查
`PRIVATE_PANE_MARKER`。

结果：私有标记不存在于任何 Bridge 可见响应。

## Audit

```text
LIST       panes=2
READ       pane=%0 lines=100
STATE      pane=%0
READ_DENY  pane=%1 reason=PANE_ACCESS_DENIED
```

Audit 记录动作、目标和范围，不记录终端正文。

## 结论

```text
PASS: two panes were enumerated with minimal metadata.
PASS: authorized pane history and state were readable.
PASS: unauthorized pane content was denied and did not leak.
```

只读 Observation Bridge 的核心边界成立：

```text
inventory metadata
       │
       ├─ authorized pane   → history + state
       └─ unauthorized pane → identity only + access denied
```

## 尚未验证

- 根据具体 tmux client 解析 selected/active pane。
- 多 window、多 session 和多个 tmux server。
- history 行数硬限制、超限错误和真实截断检测。
- ANSI escape 保留/清理模式。
- 大量 scrollback 的性能和输出上限。
- pane 在请求过程中关闭的竞态。
- SSH host、远程 cwd 和 foreground process tree。
- ACL 动态授予、撤销和持久化。
- MCP tool schema 与真实 Codex 调用。

## 下一步

优先验证 `get_active_pane(client)`：

1. 建立两个同时连接的 tmux client。
2. 让两个 client 分别选择不同 pane/window。
3. Bridge 根据明确 `client_name` 返回各自 selected pane。
4. 不允许使用模糊的全局“当前 pane”。

完成后，Observation API 才具备日常“看看我现在这个窗口”的可靠目标解析能力。

