# API v8 只读 TaskBlockRunner 验证

日期：2026-09-21  
Bridge：v0.13.0 / API v8

## 自动回归

完整测试：

```text
Ran 63 tests in 5.533s
OK
```

新增覆盖包括：

- 旧 pane 密码提示不污染当前 job；
- 同一 Codex turn 重复 acquire 幂等；
- wait 返回输出完整性和推荐动作；
- 未闭合引号在写入 pane 前拒绝；
- 只读 block 顺序执行、断言与 output reference；
- Human Ctrl+C 后不执行剩余步骤；
- 管道、重定向、未知命令和修改型变体 fail closed；
- API v7 隐藏 Runner，API v8 才发布新工具；
- 既有 tmux binding、异常恢复、实例身份、托管 session 和 MCP 端到端基线。

## 运行态冒烟验证

创建临时托管会话 `taskblock-v8-smoke`，pane `%13`，取得 generation 1 后调用
`terminal_task_block_execute`：

1. `pwd`，断言输出包含 `shared-terminal-bridge`；
2. `uname -m`，断言匹配 `arm64|x86_64`。

结果：

```text
block state: COMPLETED
steps: 2/2 COMPLETED
completion_confidence: prompt_returned
assertions: 2/2 passed
elapsed: 4169 ms
```

两个步骤分别生成 `job_882b446b56c7` 和 `job_1978a9a315e8`，证明 Runner 没有把
命令拼成目标环境脚本。每步均保留独立 job、输出摘要和 `job://` 引用。验证后临时
托管会话已经停止。

## 运行状态

本地 daemon 已重启并确认：

```json
{
  "version": "0.13.0",
  "api_version": 8,
  "method": "terminal_task_block_execute"
}
```

