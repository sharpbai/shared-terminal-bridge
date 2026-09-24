# 代码结构与修改入口

STB 按产品功能域组织代码。遇到一个工具或行为时，先在下面的映射中找到入口，再读取对应实现；通常不需要打开完整的 daemon 或 MCP server。`LocalBridge` 和 `MinimalMCPServer` 是兼容 facade，通过显式 descriptor 委托给命名 service，不再依赖多重继承 Mixin；每个 service 的 owner 依赖分别通过 `bridge` 或 `server` 属性显式可见。

代码以降低人和模型的理解、定位及安全修改成本为目标。最短代码、最少文件或复杂设计模式不是目标；应在局部可理解、整体可导航和长期维护成本之间保持合理平衡。完整约束见仓库根目录的 `AGENTS.md`。

## 维护与文档规则

- 功能开发同时维护代码结构、测试、导航和文档，不把它们留作事后清理。
- `README.md` 只保留项目概览；`docs/README.md` 作为文档导览。
- 当前说明、验证证据和历史归档分开存放。
- 每个主题只保留一个当前事实来源，其他文档通过链接引用。
- 行为、命令、路径或版本变化时同步更新文档；过时内容归档，不混入当前阅读路径。

## 从公开工具定位实现

| 要查看或修改的能力 | MCP schema | Bridge 实现 |
| --- | --- | --- |
| `terminal_read`、`terminal_read_delta`、`terminal_wait_delta` | `mcp_server/tools/observation.py` | `bridge/observation/service.py` |
| `terminal_session_*` | `mcp_server/tools/sessions.py` | `bridge/sessions/service.py` |
| Execution Lease、generation、`terminal_type` | `mcp_server/tools/execution.py` | `bridge/execution/authority.py` |
| `terminal_submit` | `mcp_server/tools/execution.py` | `bridge/execution/submit.py` |
| job 创建与状态更新 | `mcp_server/tools/jobs.py` | `bridge/execution/jobs.py` |
| `terminal_job_*`、`terminal_wait_job` | `mcp_server/tools/jobs.py` | `bridge/execution/job_wait.py`；状态判定见 `jobs.py` |
| `terminal_long_run_*` | `mcp_server/tools/long_run.py` | `bridge/execution/long_run.py` |
| `terminal_task_block*` | `mcp_server/tools/task_blocks.py` | `bridge/execution/task_blocks.py` |
| Task Block 只读命令判断 | 无独立工具 | `bridge/execution/read_only_policy.py` |
| `terminal_program_profile` | `mcp_server/tools/task_blocks.py` | `bridge/sessions/service.py`；数据在 `bridge/config.py` |
| Human `Ctrl+C` / Human Override | 无独立 MCP 写入入口 | `bridge/runtime/human_events.py` |
| 审计与持久化历史 | `mcp_server/tools/observation.py` | `bridge/runtime/audit.py` |

Bridge socket 方法的完整注册表位于 `bridge/protocol/registry.py`。MCP 工具的完整注册表位于 `mcp_server/tools/registry.py`。不知道入口时只需先打开这两个小文件之一。

## 常见改动路径

| 要修改的内容 | 主要实现 | 对应测试 |
| --- | --- | --- |
| 读取、增量与等待 | `bridge/observation/service.py` | `tests/test_bridge_observation.py` |
| Lease、generation 与 turn gate | `bridge/execution/authority.py` | `tests/test_turn_gate.py` |
| 命令提交与 Job 状态 | `bridge/execution/submit.py`、`jobs.py`、`job_wait.py` | `tests/test_bridge_jobs.py` |
| 长任务批准 | `bridge/execution/long_run.py` | `tests/test_bridge_long_run.py` |
| Task Block 与只读 Runner | `bridge/execution/task_blocks.py`、`read_only_policy.py` | `tests/test_bridge_task_blocks.py` |
| 托管会话与 tmux 操作 | `bridge/sessions/service.py`、`bridge/tmux/backend.py` | `tests/test_bridge_sessions.py`；宿主机基线见 `tests/host_tmux/` |
| MCP 发布与调用转发 | `mcp_server/tools/`、`mcp_server/runtime/` | `tests/test_mcp_discovery.py`、`test_mcp_tool_calls.py` |
| `stb` 命令 | `stb_cli/commands_*.py`、`parser_*.py` | `tests/test_stb_cli.py` |

新增公开工具时，必须同步检查 MCP schema、`mcp_server/tools/registry.py`、Bridge protocol registry、facade descriptor、领域实现和测试。`tests/test_registry_consistency.py` 会检查公开路由是否漂移。

领域 service 通过 `bridge/service.py` 中的 `SERVICE_DEPENDENCIES` 显式声明可访问的 owner 状态和协作方法。运行时 `ServiceContext` 拒绝未声明访问；一致性测试从 service 源码提取实际依赖并要求声明完全匹配。修改 service 依赖时应先判断是否真的属于该领域，再同步更新声明。

## 目录职责

```text
bridge/
├── local_bridge.py             # 兼容 facade、service 显式委托、CLI
├── common.py                   # 结构化错误和时间工具
├── config.py                   # 预算、限制和静态 capability 数据
├── protocol/
│   └── registry.py             # Bridge method → 实现方法
├── runtime/
│   ├── state.py                # instance lock、持久化和恢复
│   ├── audit.py                # audit 与交互历史
│   ├── human_events.py         # Human Override 和 lease revoke
│   └── socket_server.py        # control/event Unix socket 生命周期
├── tmux/
│   └── backend.py              # tmux 命令和托管会话底层操作
├── sessions/
│   └── service.py              # session、pane、human binding API
├── observation/
│   └── service.py              # read、delta cursor 和有界等待
└── execution/
    ├── authority.py            # pane ACL、lease、generation
    ├── long_run.py             # 长任务请求与审批
    ├── submit.py               # 命令完整性检查和提交
    ├── jobs.py                 # job 创建、监控与状态更新
    ├── job_wait.py             # job 查询、等待和取消等待
    ├── task_blocks.py          # task block 规划、执行与观察
    └── read_only_policy.py     # Runner 只读命令分类

mcp_server/
├── server.py                   # 兼容 facade、component 显式委托和 CLI
├── config.py                   # 协议版本与 Bridge feature gate
├── transport.py                # Bridge Unix socket client
├── turn_context.py             # Codex thread/turn 解析
├── tool_catalog.py             # 旧导入路径的兼容导出
├── runtime/
│   ├── compatibility.py        # Bridge API 能力检测
│   ├── protocol.py             # initialize、discover 和工具列表
│   ├── tool_calls.py           # 参数验证、调用转发和 session acquire
│   └── stdio.py                # JSON-RPC stdio 调度
└── tools/
    ├── registry.py             # 完整工具索引
    ├── observation.py
    ├── sessions.py
    ├── execution.py
    ├── jobs.py
    ├── long_run.py
    └── task_blocks.py

stb_cli/
├── main.py                     # 最小 CLI 调度和统一错误处理
├── commands_sessions.py        # 会话命令
├── commands_execution.py       # lease、批准、job、wait 与 interrupt
├── commands_admin.py           # history 与 daemon
├── parser.py                   # 根参数和中文帮助入口
├── parser_sessions.py          # 会话参数
├── parser_execution.py         # 执行控制参数
├── parser_admin.py             # 管理参数
├── client.py                   # tmux discovery 与 Bridge 调用
├── daemon.py                   # daemon start/status/stop
├── output.py                   # 人类可读与 JSON 输出
└── config.py                   # CLI 路径和 tmux 格式
```

`bin/stb` 仅保留可执行入口和历史导入兼容层。默认测试按相同领域拆分为 `test_bridge_*` 与 `test_mcp_*` 文件；共享 fixture 分别位于 `tests/context_support.py` 和 `tests/mcp_support.py`。需要真实 tmux 的集成基线位于 `tests/host_tmux/`，必须在容器外执行。`poc/` 是历史实验和基线实现，不是日常修改入口。

## 兼容性约束

- `bridge.local_bridge` 继续导出 `LocalBridge`、`TmuxBackend`、`BridgeError`、`now` 和 `unix_ms`。
- `mcp_server.server` 继续导出 `MinimalMCPServer`、`BridgeClient`、`MCPError` 和 `CodexTurnResolver`。
- 公开工具名、Bridge method、socket payload 和错误码不能因目录调整而改变。
- pane ACL、generation、Human Override、长任务审批必须继续由本地 STB 强制执行。
- 发布版本以 `bridge/config.py` 的 `BRIDGE_VERSION` 和 `BRIDGE_API_VERSION` 为唯一代码来源；`tests/test_version_consistency.py` 校验 MCP metadata 和当前文档。

## 验证命令

```bash
python3 -m compileall -q bridge mcp_server
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 bridge/local_bridge.py --help
python3 mcp_server/server.py --help
```

真实 tmux 集成测试见[测试分层](testing.md)。
