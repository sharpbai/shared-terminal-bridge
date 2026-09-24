# Execution Lease 与 Human Override 验证

日期：2026-09-20  
环境：macOS、tmux 3.6a、本地 Unix domain datagram socket  
状态：核心 PoC 验证通过

## 验证目标

证明 Human `Ctrl+C` 不只是一个供模型理解的提示，而能在 Bridge 控制层：

1. 撤销绑定到具体 pane 和 generation 的 execution lease。
2. 阻止旧 generation 的后续 Agent 操作进入 pane。
3. 不把 Agent 自己发送的 `C-c` 误判为 Human Override。

## 测试模型

```text
pane       = %0
generation = 1
state      = ACTIVE
```

测试使用隔离的 tmux server：

```text
tmux socket  = execution-lease-poc
session      = execution-lease-poc
event socket = /tmp/shared-terminal-execution-lease.sock
```

PoC 文件：

```text
poc/execution_lease.py
```

## 测试顺序

### 1. Agent Ctrl+C

PoC 先通过 `tmux send-keys C-c` 注入一次 Agent `Ctrl+C`。

结果：

- pane 收到了 `C-c`。
- 没有产生 Human Event。
- lease 继续保持 `ACTIVE`。

审计记录：

```text
AGENT_KEY  pane=%0 generation=1 key=C-c state=ACTIVE
```

### 2. 有效 lease 下的 Agent 操作

Bridge 使用 `generation=1` 写入：

```text
printf 'LEASE_GEN_1_ACTION_ALLOWED\n'
```

pane 实际执行并显示：

```text
LEASE_GEN_1_ACTION_ALLOWED
```

审计记录：

```text
ALLOW      pane=%0 generation=1 bytes=37
```

### 3. Human Ctrl+C

用户在 pane 中运行：

```bash
ping 1.1.1.1
```

亲自按下 `Ctrl+C` 后：

- `ping` 正常收到 SIGINT 并打印统计信息。
- socket receiver 收到一个 `human_interrupt`。
- 事件正确关联 `pane=%0` 和 `client=/dev/ttys021`。

```json
{
  "client": "/dev/ttys021",
  "key": "C-c",
  "pane": "%0",
  "seq": 1,
  "session": "execution-lease-poc",
  "source": "tmux_client",
  "timestamp": "2026-09-20T11:41:21.213+08:00",
  "type": "human_interrupt"
}
```

lease 状态转换：

```text
ACTIVE → REVOKED
```

审计记录：

```text
OVERRIDE   pane=%0 generation=1 previous=ACTIVE state=REVOKED event_seq=1
```

### 4. 旧 generation 操作

Human Override 后，PoC 尝试使用旧的 `generation=1` 写入：

```text
STALE_ACTION_SHOULD_NOT_RUN
```

Bridge 在执行 tmux 命令之前拒绝该操作：

```text
DENY       pane=%0 generation=1 lease_generation=1 state=REVOKED
```

`capture-pane` 验证：

- `LEASE_GEN_1_ACTION_ALLOWED` 存在。
- `STALE_ACTION_SHOULD_NOT_RUN` 不存在。

## 完整实测结论

```text
PASS: Human Ctrl+C revoked generation=1.
PASS: stale generation=1 action was denied before reaching pane.
```

验证通过的状态链：

```text
Agent C-c
  → pane
  → no Human Event
  → lease remains ACTIVE

Human C-c
  → pane/SIGINT
  → Human Event
  → lease REVOKED
  → stale Agent action DENIED
  → no bytes reach pane
```

## 关键结论

Human Override 不需要依赖 Codex 是否理解 prompt 或是否自觉停止。Bridge 可以根据
结构化事件强制撤销 execution lease，并在 tmux 写入发生前拒绝 stale generation。

因此以下安全语义已获得本地实验证据：

```text
Ctrl+C = revoke execution authority
```

而不只是：

```text
Ctrl+C = tell the model it should probably stop
```

## 尚未验证

- lease 过期时间和自动 `EXPIRED`。
- revoke 与并发写入之间的原子顺序。
- 多 pane 各自独立 lease。
- 多 client 同时触发 Human Event。
- Bridge 进程重启后的 generation 持久化。
- lease reacquire 后 generation 单调递增。
- socket 事件重复、丢失或乱序时的幂等处理。
- 真正 MCP tool 调用层的 generation 强制校验。

## 下一步

当前可以进入 Observation Bridge 验证：

1. 定义 `terminal_list`、`terminal_read`、`terminal_state` schema。
2. 在隔离 tmux server 中实现只读接口。
3. 验证多 pane 枚举、指定 pane history 和状态读取。
4. 验证未授权 pane 不会被读取。

完成只读 Bridge 后，再把 execution lease guard 接入正式 Action API。

