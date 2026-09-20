# Unix Socket Human Event 验证

日期：2026-09-20  
环境：macOS、tmux 3.6a、Unix domain datagram socket  
状态：核心 PoC 验证通过

## 验证目标

在已经证明 tmux 能区分 Human/Agent `Ctrl+C` 的基础上，继续验证：

1. Human Event 能通过本地 Unix socket 发送结构化 JSON。
2. socket 只允许当前用户访问。
3. Agent 的 `tmux send-keys C-c` 不产生 Human Event。
4. 事件监听器不存在时，Human `Ctrl+C` 仍正常到达 pane。

## 实现

PoC：

```text
poc/human_event_socket.py
```

隔离环境：

```text
tmux socket  = human-event-socket-poc
session      = human-event-socket-poc
event socket = /tmp/shared-terminal-human-event.sock
socket mode  = 0600
```

事件生产路径：

```text
Human Ctrl+C
  → tmux client root key table
  → send-keys C-c
  → foreground process receives SIGINT
  → asynchronous run-shell
  → short-lived event producer
  → Unix datagram socket
  → event receiver assigns seq
```

生产者发送失败时静默退出，不改变前面的 `send-keys C-c` 路径。

## Human 事件实测

用户在隔离 tmux pane 中运行 `ping 1.1.1.1`，亲自按下 `Ctrl+C`，然后
detach。receiver 收到一个事件：

```json
{
  "client": "/dev/ttys021",
  "key": "C-c",
  "pane": "%0",
  "seq": 1,
  "session": "human-event-socket-poc",
  "source": "tmux_client",
  "timestamp": "2026-09-20T11:22:27.611+08:00",
  "type": "human_interrupt"
}
```

验证结果：

- 事件数量为 1。
- 类型、来源、按键、pane、client 和 session 正确。
- receiver 成功添加单调序号 `seq=1`。
- socket 权限为 `0600`。

## Agent 来源测试

PoC 使用以下路径注入：

```text
tmux send-keys -t human-event-socket-poc C-c
```

自动测试结果：

```text
Received events: 0
PASS: agent send-keys produced no Human event.
```

因此 Unix socket 事件通道没有破坏 Phase 0 已验证的来源分流。

## Fail-open 测试

测试时不启动 event listener，只保留 tmux binding。用户再次在 pane 中运行
`ping` 并亲自按下 `Ctrl+C`。

结果：前台程序仍可正常被中止，随后正常 detach；事件 socket 不存在没有阻塞
Human 控制路径。

## 结论

以下核心链路已经成立：

```text
Human Ctrl+C
  ├─→ pane/SIGINT
  └─→ structured local event

Agent send-keys C-c
  ├─→ pane/SIGINT
  └─X no Human event

consumer absent
  ├─→ pane/SIGINT remains available
  └─X event may be dropped by design
```

Unix datagram socket 适合作为 Human Event Layer 到本地 Bridge 的第一版传输方式。

## 尚未验证

- receiver 重启后的序号连续性。
- consumer 断线期间是否需要持久化或允许丢弃。
- socket buffer 满时的事件丢失和背压行为。
- 高频事件和多个 tmux client 并发。
- 伪造 datagram 的威胁模型；当前依赖文件系统权限 `0600`。
- Bridge 启动时如何清理失效 socket。
- 事件与 Agent 写操作并发时的严格排序。
- execution lease 消费者收到事件后的实际撤销。

## 下一步

实现最小 execution lease 模拟器：

1. 为指定 pane 创建 `ACTIVE` lease 和 generation。
2. 允许携带正确 generation 的模拟 Agent 操作。
3. 收到该 pane 的 `human_interrupt` 后改为 `REVOKED`。
4. 拒绝所有携带旧 generation 的后续操作。
5. 同时记录可审计的状态转换。

