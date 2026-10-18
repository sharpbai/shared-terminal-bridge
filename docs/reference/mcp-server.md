# MCP Server：任务接口

MCP 是本机 Bridge socket 的 stdio 适配层，不直接操作 tmux。当前模型契约只暴露任务，不暴露授权计数；旧 acquire/submit/type/key 等模型接口不再发布，无兼容回退。完整语义见[模型任务接口](model-tasks.md)。

入口是 MCP 自发现的 instructions 与 tools/list schema，不需要安装或预读 STB skill，也不需要先读仓库文档。modern discover 和 initialize 发布相同操作/安全指引；STB-RDC 则由 bootstrap 返回对应的精简契约。

## 启动

```bash
python3 mcp_server/server.py --enable-actions --enable-session-management
```

不带 enable-actions 时只读；session 管理单独启用。默认 socket 为 `/tmp/shared-terminal-bridge.sock`。只读和模型执行仍受 Pane ACL 约束。

## 常规工作

1. 已知会话名时直接使用 name-based 观察，得到实际 pane 并核对目标，不先枚举全部会话。
2. 调用 terminal_run：pane、唯一 request_id、单行命令，以及可选耗时、资源类别和等待窗口。Core 内部授权、提交和等待。
3. 完成结果已含有界输出，不再补读。尚在运行则按 job ID 继续观察。
4. terminal_input_job 用 job ID 和唯一输入请求 ID 回复执行中的程序；terminal_interrupt_job 只中断该 job，不可作用于较新任务。
5. 高资源请求返回审批信息；展示完整命令与影响，取得有效后续人工批准后 terminal_approve_request，再用新 run ID 携带批准执行。

普通 run 不要求模型提供或取得宿主回合身份；风险审批所需的可信回合证据由 MCP 内部读取，模型不能通过参数伪造。无法验证审批时继续 fail closed，保留人工本地批准入口。

## 等待和取消

run 和 terminal_wait_job 都使用可取消的本地等待。默认最多 600000ms；Core 的检查点语义不变。MCP notifications/cancelled 唤醒等待，不发送终端 Ctrl+C。run 尚未进入 Core 就被取消时不提交命令。

Human Ctrl+C 仅在执行中的任务上取消旧链。新 run 以本地接收顺序授权；同 ID 重试只观察原 job，不能恢复旧执行链。未知 pane、旧 job、冲突 ID 和崩溃不确定状态仍拒绝。

## 协议与能力

保留 modern server/discover 与 legacy initialize 的 MCP 帧协议，二者发布相同的新任务契约；保留协议帧格式不等于保留旧模型工具。默认结果与错误隐藏授权元数据，命令和输出字符串不做替换。

Core 提供 `model_tasks=job-authority-v2`。升级后重启 Bridge，并重新连接 Codex MCP，刷新缓存的工具列表；旧进程不会因为源文件变化自动重载。不需重建 tmux 会话。

RDC 选择仍遵循[Exclusive Mode](stb-rdc-exclusive-mode.md)：只作 transport/bootstrap，独立能力需要一次性明确旁路批准。

## 开发与验证

- schema：`mcp_server/tools/tasks.py`；注册表：`mcp_server/tools/registry.py`。
- 转发与取消：`mcp_server/runtime/tool_calls.py`；模型结果：`bridge/protocol/model_view.py`。
- Core：`bridge/execution/run.py`、`job_actions.py`；内部授权与事件状态仍在原领域模块。
- 单元与 socket：`tests/test_mcp_tool_calls.py`、`test_mcp_request_identity.py`、`test_job_actions.py`、`test_rdc_transport_integration.py`。
- 真实隔离链路：`poc/mcp_end_to_end.py`，由 `tests/host_tmux/` 在宿主执行。
