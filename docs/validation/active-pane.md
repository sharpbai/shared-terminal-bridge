# Per-client Active Pane 验证

日期：2026-09-20  
环境：macOS、tmux 3.6a、两个 control-mode client  
状态：核心 PoC 验证通过

## 验证目标

验证 Bridge 不使用模糊的全局“当前 pane”，而是根据明确的 tmux
`client_name` 解析目标：

1. 两个 client 可以同时解析到不同 pane。
2. pane 解析和 Pane ACL 相互独立。
3. 未知 client 必须 fail-closed，不得回退到其他 client。

## 测试环境

```text
tmux socket = active-pane-poc

client-62076
  → session active-pane-a
  → pane %0
  → authorized=true

client-62077
  → session active-pane-b
  → pane %1
  → authorized=false
```

两个 client 都是无 UI 的 tmux control-mode client，用于自动验证多 client
上下文，不依赖 iTerm2。

## 发现的错误路径

最初尝试：

```text
tmux display-message -p -c <client> ...
```

在外部调用上下文中，该路径没有可靠切换到指定 client：

- client A、client B 都解析成最后一个 client。
- 传入不存在的 client 时也没有可靠失败。
- 结果会静默回退，存在读取错误 pane 的风险。

这种行为不能用于安全边界。

## 最终解析方法

Bridge 对同一个 `list-clients` 快照读取：

```text
client_name
client_session
pane_id
```

然后在进程内按 `client_name` 精确匹配：

- 恰好匹配一行才返回 pane。
- 找不到时返回 `CLIENT_NOT_FOUND`。
- 不允许 fallback 到 active、latest 或其他 client。
- 得到 pane 后仍独立计算 `authorized`，解析本身不授予权限。

## 实测结果

### Client A

```json
{
  "client": "client-62076",
  "session": "active-pane-a",
  "pane": "%0",
  "authorized": true
}
```

### Client B

```json
{
  "client": "client-62077",
  "session": "active-pane-b",
  "pane": "%1",
  "authorized": false
}
```

### 未知 client

```json
{
  "error": {
    "code": "CLIENT_NOT_FOUND",
    "client": "missing-client"
  }
}
```

## Audit

```text
ACTIVE     client=client-62076 pane=%0 authorized=true
ACTIVE     client=client-62077 pane=%1 authorized=false
ACTIVE_DENY client=missing-client reason=CLIENT_NOT_FOUND
```

## 结论

```text
PASS: each client resolved to its own active pane.
PASS: pane authorization remained independent of resolution.
PASS: unknown client was rejected without fallback.
```

因此日常交互中的“我现在这个窗口”必须转换为：

```text
explicit client identity
  → exact client snapshot match
  → pane ID
  → Pane ACL
  → read/action
```

不能转换为：

```text
some global active pane
  → best effort fallback
```

## 尚未验证

- 同一个 session 中两个 client 分别选择不同 window/pane。
- client 在解析后、读取前切换 pane 的竞态。
- iTerm2 普通 client 与 control-mode client 的名称稳定性。
- client detach/reconnect 后如何恢复用户到 client 的映射。
- 多 tmux server 的 client identity 命名空间。
- 将 client snapshot 与 read/action 放进同一事务或 generation。

## 下一步

将已经验证的四块拼成一个本地 Bridge 原型：

1. Observation API。
2. per-client pane resolution。
3. Unix socket Human Event consumer。
4. pane-scoped execution lease guard。

原型先提供本地 CLI/JSON 接口并运行端到端测试，再决定是否包装成 MCP server。

