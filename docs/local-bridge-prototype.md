# 本地 Bridge 原型

## 组成

`bridge/local_bridge.py` 是一个保持状态的本地 daemon，同时提供：

- Unix stream socket：接收一行一个 JSON RPC 请求。
- Unix datagram socket：接收 tmux Human Event。
- tmux backend：枚举、读取、状态和受控输入。
- Pane ACL：所有内容读取和动作前检查。
- Per-client resolver：精确 client snapshot 匹配。
- Execution Lease：pane-scoped generation 与状态机。
- Audit Log：记录读取、授权、动作、拒绝和 Human Override。

## 安全默认值

- 没有 `--allow-pane` 时不授权任何 pane。
- control/event socket 权限均设为 `0600`。
- 未知 client 不回退。
- 未授权 pane 不执行 `capture-pane`。
- Action 必须同时满足 pane ACL 和有效 generation。
- Human Event 撤销 lease 后，旧 generation 在 tmux 写入前被拒绝。
- Human Event producer 无法连接时 fail-open，不阻止 `Ctrl+C`。
- 同一 state 只允许一个 daemon 持有非阻塞文件锁。
- state 与当前 tmux server UUID 不一致时拒绝启动。

## 启动

以下示例使用名为 `default` 的 tmux socket，并只授权 `%3`：

```bash
python3 bridge/local_bridge.py serve \
  --tmux-socket default \
  --allow-pane %3
```

默认本地 socket：

```text
/tmp/shared-terminal-bridge.sock
/tmp/shared-terminal-events.sock
```

## JSON CLI

列出 pane：

```bash
python3 bridge/local_bridge.py call terminal_list
```

读取：

```bash
python3 bridge/local_bridge.py call terminal_read \
  --params '{"pane":"%3","lines":100}'
```

状态：

```bash
python3 bridge/local_bridge.py call terminal_state \
  --params '{"pane":"%3"}'
```

安装 Human `Ctrl+C` binding：

```bash
python3 bridge/local_bridge.py call install_human_binding
```

获取 lease：

```bash
python3 bridge/local_bridge.py call acquire_execution \
  --params '{"pane":"%3"}'
```

写入文本和 Enter 必须携带返回的 generation：

```bash
python3 bridge/local_bridge.py call terminal_type \
  --params '{"pane":"%3","generation":1,"text":"pwd"}'

python3 bridge/local_bridge.py call terminal_key \
  --params '{"pane":"%3","generation":1,"key":"Enter"}'
```

读取审计：

```bash
python3 bridge/local_bridge.py call audit_log
```

## 当前 RPC

Observation：

- `terminal_list`
- `get_active_pane`
- `terminal_read`
- `terminal_state`

Human Event：

- `install_human_binding`
- `restore_human_binding`
- `human_binding_status`
- Unix datagram `human_interrupt`

Control：

- `acquire_execution`
- `release_execution`
- `execution_status`

Action：

- `terminal_type`
- `terminal_key`
- `terminal_interrupt`

Audit：

- `audit_log`

## 原型限制

- Local JSON RPC 保留为安全核心边界，已由 `mcp_server/server.py` 封装为
  最小 stdio MCP；MCP 不直接调用 tmux。
- ACL 仍来自启动参数，audit 仍只保存在内存。
- generation、lease 和 binding 快照已原子持久化；重启时 ACTIVE lease
  fail-closed 转为 REVOKED。
- 尚无用户确认 UI 或任务身份。
- 没有 lease 过期时间。
- 未处理重复/乱序 Human Event。
- socket 权限依赖本机单用户边界，没有更强身份认证。
- tmux server UUID 保存在 tmux global environment；手动删除该变量会导致
  下次启动 fail-closed，需要明确处理旧 state。

在连接正常日常 tmux server 前，应先实现 binding 备份与恢复、持久 generation 和
明确的 pane 授权配置。
