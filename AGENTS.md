# Shared Terminal Bridge 开发指南

## 从最小上下文开始

- CLI 只读接入/刷新见 `stb_cli/bootstrap.py`，意图→命令引导见 `stb_cli/discovery.py`。共用执行/观察语义属于 STB，RDC 进程与传输专属规则属于 STB-RDC，不向 Core 通用说明加入 RDC 术语。

- Agent 执行/安全说明唯一来源为 `bridge/agent_instructions.py`，MCP instructions 与 CLI discover 共用；输入方式选择规则放 discover，不在默认或 run 帮助重复。

- Agent 执行入口在 `stb_cli/`，人工管理入口在 `stb_manage/`；不要向 Agent 默认帮助重新加入管理步骤。
- CLI：`stb` 只负责发现/观察/任务执行；创建、进入、停止会话、daemon、历史和 cleanup-tasks 使用 `stb-manage`。共享只读 list/info，不复制安全状态机。

1. 查 Bridge 公开方法，先看 `bridge/protocol/registry.py`。
2. 查 MCP 工具，先看 `mcp_server/tools/registry.py`，再按注册项打开对应 schema 和 Bridge 实现。
3. 只知道行为、不知道工具名时，先看 `docs/development/code-structure.md`。
4. 不要一开始读取整个 `poc/`、完整路线图或全部测试；先打开对应功能域和测试。
5. 模型接口采用 run/job ID，不保留旧 acquire/submit/generation 契约；Core 内部 Pane ACL、授权计数、Human Override、请求去重仍须严格校验。高风险确认由模型通过对话取得，不在 Core 中维护审批状态机。

- CLI 复杂输入用 --base64：Codex 使用本机工具按 UTF-8 编码并解码回验，不手算、不添加换行。run 已移除 stdio/stdin 参数；MCP text 不受此变更影响。

## 代码风格

- 自发现 JSON 的说明文案统一中文；字段名、协议标签、状态码、命令及终端原始输出保持不变。

目标是让人和模型容易理解、定位并安全修改。

- 按功能域组织代码，使工具、schema、实现和测试名称互相对应。
- 一般改动应集中在一个主要文件和少量明确依赖中。
- 优先使用清楚的命名、显式依赖和直接控制流。
- 最短代码、最少文件和复杂设计模式都不是目标。
- 只有确实减少重复或稳定边界，且不增加导航成本时才引入抽象。
- 文件和函数保持合理规模，但以维护和理解成本为准，不追求机械行数限制。
- 测试结构与生产功能域对应，并覆盖兼容性和安全行为。

## 文档与持续维护

- 代码结构、测试、导航和文档属于功能开发，不是事后清理。
- `README.md` 只做项目概览，`docs/README.md` 是文档总入口。
- 当前说明、验证证据和历史资料分开存放。
- 使用看 guides，契约看 reference，修改看 development，验收看 validation，按日演进看 history/changes；先按目的定位，不通读日期记录找当前接口。移动文档同时修复链接及手册目录。
- 每个主题只保留一个当前事实来源，其他位置通过链接引用。
- 行为、命令、路径或版本变化时，在同一次改动中更新文档；过时内容归档，不留在当前阅读路径。
- 版本号只在 `bridge/config.py` 定义；当前文档和 MCP metadata 由版本一致性测试约束。

## 依赖边界

- 领域 service 只能访问 `bridge/service.py` 中 `SERVICE_DEPENDENCIES` 明确声明的 owner 能力。
- 不要为了通过检查直接扩大依赖清单；先判断状态或协作方法是否应移动到更合适的领域。
- 修改 service 的 `self.bridge.*` 访问后，同步更新依赖声明和一致性测试预期。

## 验证

修改时先运行对应领域测试。默认测试不访问真实 tmux，可在容器或沙箱内执行：

```bash
python3 -m compileall -q bridge mcp_server stb_cli stb_manage
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 bridge/local_bridge.py --help
python3 mcp_server/server.py --help
```

`tests/host_tmux/` 会创建隔离 tmux server，只能在容器外的宿主机执行。涉及 tmux、daemon、binding 或恢复逻辑时，再运行：

```bash
python3 -m unittest discover -s tests/host_tmux -p 'test_*.py' -v
```

完整说明见 `docs/development/testing.md`。
