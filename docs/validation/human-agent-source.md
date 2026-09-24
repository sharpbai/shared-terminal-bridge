# Human/Agent 来源分流验证

日期：2026-09-20  
环境：macOS、tmux 3.6a  
状态：核心假设验证通过

## 验证目标

确认在同一个 tmux pane 中能够区分：

1. 用户通过 tmux client 亲自按下 `Ctrl+C`。
2. Agent/Bridge 使用 `tmux send-keys C-c` 注入 `Ctrl+C`。

同时要求用户按下的 `Ctrl+C` 仍然正常到达前台程序。

## 最初假设及失败记录

最初尝试使用 iTerm2 Python API 的 `KeystrokeMonitor`：

- 普通 shell 中成功捕获 `Ctrl+C`，实际事件为
  `chars='\\x03'`、`Modifier.CONTROL`、`Keycode.ANSI_C`。
- 进入普通 tmux 后，绑定的 monitor 不再收到后续按键。
- 全局监听还会扩大敏感输入暴露范围，不符合最小权限原则。

因此放弃以 iTerm2 为系统边界，改为在实际管理共享 pane 的 tmux 输入层分流。

## tmux PoC

PoC 使用独立 socket：

```text
socket  = human-event-poc
session = human-event-poc
log     = /tmp/tmux-human-events.log
```

安装的核心 binding 等价于：

```tmux
bind-key -T root C-c \
  send-keys C-c \; \
  run-shell -b '记录 HUMAN_INTERRUPT、pane_id、client_name'
```

关键性质：

- 真人输入经过 `root` key table，因此触发 binding。
- binding 先执行 `send-keys C-c`，保证 SIGINT 优先。
- 日志异步执行，记录失败不会阻塞中断。
- Agent 的 `tmux send-keys` 不经过 client key table。

## 实测步骤

启动并 attach 隔离 session：

```bash
./poc/human_event_tmux.py
```

在 pane 中运行：

```bash
ping 1.1.1.1
```

用户亲自按 `Ctrl+C`，然后 detach。得到：

```text
2026-09-20T11:08:31+0800 HUMAN_INTERRUPT pane=%0 client=/dev/ttys021
```

随后执行 Agent 注入测试：

```bash
./poc/human_event_tmux.py --agent-ctrl-c
```

输出显示执行了 `tmux send-keys`，事件日志仍然只有原来的一条：

```text
2026-09-20T11:08:31+0800 HUMAN_INTERRUPT pane=%0 client=/dev/ttys021
```

## 结论

验证通过：

| 输入来源 | pane 收到 C-c | 产生 HUMAN_INTERRUPT |
|---|---:|---:|
| Human，经 tmux client | 是 | 是 |
| Agent，经 tmux send-keys | 是 | 否 |

因此 tmux client input layer 可以作为 Human Event Layer 的可靠边界，并直接提供：

- `pane_id`：事件作用的共享终端。
- `client_name`：事件来自哪个 tmux client/TTY。
- 输入来源分流：client input 与 programmatic `send-keys`。

## 尚未验证

- 多 client 同时连接同一 session。
- copy-mode、prompt mode 和非 root key table 下的 `Ctrl+C`。
- tmux 配置 reload、server restart 后的 binding 生命周期。
- Unix socket 事件投递、消费者断线和背压。
- Human interrupt 与 Agent 输入并发时的严格排序。
- execution lease 的撤销和 stale generation 拒绝。

## 下一步

将异步文件日志替换为本地 Unix domain socket，发送结构化事件：

```json
{
  "seq": 1,
  "type": "human_interrupt",
  "source": "tmux_client",
  "key": "C-c",
  "pane": "%0",
  "client": "/dev/ttys021",
  "timestamp": "2026-09-20T11:08:31+08:00"
}
```

下一步仍只验证事件传输，不提前实现完整 MCP Bridge。
