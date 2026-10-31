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
| Execution Lease、generation、`terminal_type` | 不对模型发布（内部实现） | `bridge/execution/authority.py` |
| `terminal_submit` | 不对模型发布（内部实现） | `bridge/execution/submit.py` |
| `terminal_run`、job 输入/中断 | `mcp_server/tools/tasks.py` | `bridge/execution/run.py`、`job_actions.py`；去重见 `bridge/runtime/command_requests.py` |
| job 创建与状态更新 | `mcp_server/tools/jobs.py` | `bridge/execution/jobs.py` |
| `terminal_job_*`、`terminal_wait_job` | `mcp_server/tools/jobs.py` | `bridge/execution/job_wait.py`；状态判定见 `jobs.py` |
| 内部 Task Block | 不对模型发布 | `bridge/execution/task_blocks.py` |
| Task Block 只读命令判断 | 无独立工具 | `bridge/execution/read_only_policy.py` |
| `terminal_program_profile` | `mcp_server/tools/programs.py` | `bridge/sessions/service.py`；数据在 `bridge/config.py` |
| Human `Ctrl+C` / Human Override | 无独立 MCP 写入入口 | `bridge/runtime/human_events.py` |
| 输出/按键有序事件与执行阶段 | 无独立 MCP 写入入口 | `bridge/tmux/control_stream.py`、`bridge/runtime/terminal_events.py`、`bridge/execution/lifecycle.py` |
| 本地接收顺序与自动续授权 | Core 内部处理，不发布手工授权工具 | `bridge/runtime/admission.py`、`bridge/execution/authority.py`、`LocalBridge.dispatch` |
| 审计与持久化历史 | `mcp_server/tools/observation.py` | `bridge/runtime/audit.py` |

Bridge socket 方法的完整注册表位于 `bridge/protocol/registry.py`。MCP 工具的完整注册表位于 `mcp_server/tools/registry.py`。不知道入口时只需先打开这两个小文件之一。

## 常见改动路径

| 要修改的内容 | 主要实现 | 对应测试 |
| --- | --- | --- |
| 读取、增量与等待 | `bridge/observation/service.py` | `tests/test_bridge_observation.py` |
| Lease、generation 与 turn gate | `bridge/execution/authority.py` | `tests/test_turn_gate.py` |
| 命令提交与 Job 状态 | `bridge/execution/submit.py`、`jobs.py`、`job_wait.py` | `tests/test_bridge_jobs.py` |
| Run 授权/提交/等待组合 | `bridge/execution/run.py` | `tests/test_terminal_run.py`、`tests/host_tmux/test_terminal_run.py` |
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
    ├── command_metadata.py     # 命令指纹与审计脱敏
    ├── submit.py               # 命令完整性检查和提交
    ├── run.py                  # 同 receipt 内授权、单次提交和等待
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
│   ├── tool_calls.py           # 参数验证、任务调用转发
│   └── stdio.py                # JSON-RPC stdio 调度
└── tools/
    ├── registry.py             # 完整工具索引
    ├── observation.py
    ├── sessions.py
    ├── tasks.py
    ├── jobs.py
    └── programs.py

stb_cli/                       # Agent 执行与共用只读能力
├── main.py                     # Agent 调度；共用错误处理
├── parser.py                   # discover/list/info/run/job/wait/interrupt
├── parser_common.py            # 共用中文帮助与 socket 参数
├── commands_sessions.py        # 仅 list/info，不改会话
├── commands_execution.py       # run/job/wait/interrupt
├── session_info.py             # 面板与当前任务的会话级聚合
├── command_input.py            # Base64 解码与单行边界
├── client.py                   # Unix socket 与 tmux 查询
└── output.py                   # 共用结果显示

stb_manage/                    # 独立人工管理包
├── main.py                     # stb-manage 调度
├── parser.py                   # 管理命令帮助
├── commands_sessions.py        # create/enter/stop
├── commands_admin.py           # history/daemon/cleanup-tasks
├── daemon.py                   # daemon 生命周期
└── task_cleanup.py             # 备份后清理残留任务

```

`bin/stb` 与 `bin/stb-manage` 分别为 Agent 和人工管理入口，不保留旧管理子命令别名。默认测试按相同领域拆分为 `test_bridge_*` 与 `test_mcp_*` 文件；共享 fixture 分别位于 `tests/context_support.py` 和 `tests/mcp_support.py`。需要真实 tmux 的集成基线位于 `tests/host_tmux/`，必须在容器外执行。`poc/` 是历史实验和基线实现，不是日常修改入口。

## 兼容性约束

- `bridge.local_bridge` 继续导出 `LocalBridge`、`TmuxBackend`、`BridgeError`、`now` 和 `unix_ms`。
- `mcp_server.server` 继续导出 `MinimalMCPServer`、`BridgeClient`、`MCPError` 和 `CodexTurnResolver`。
- 公开工具名、Bridge method、socket payload 和错误码不能因目录调整而改变。
- pane ACL、generation、Human Override 必须继续由本地 STB 强制执行。
- 发布版本以 `bridge/config.py` 的 `BRIDGE_VERSION` 和 `BRIDGE_API_VERSION` 为唯一代码来源；`tests/test_version_consistency.py` 校验 MCP metadata 和当前文档。

## 验证命令

```bash
python3 -m compileall -q bridge mcp_server
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 bridge/local_bridge.py --help
python3 mcp_server/server.py --help
```

真实 tmux 集成测试见[测试分层](testing.md)。
