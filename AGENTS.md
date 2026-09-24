# Shared Terminal Bridge 开发指南

## 从最小上下文开始

1. 查 Bridge 公开方法，先看 `bridge/protocol/registry.py`。
2. 查 MCP 工具，先看 `mcp_server/tools/registry.py`，再按注册项打开对应 schema 和 Bridge 实现。
3. 只知道行为、不知道工具名时，先看 `docs/development/code-structure.md`。
4. 不要一开始读取整个 `poc/`、完整路线图或全部测试；先打开对应功能域和测试。
5. 保持工具名、socket payload、错误码、Pane ACL、generation、Human Override 和长任务批准语义兼容。

## 代码风格

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
- 每个主题只保留一个当前事实来源，其他位置通过链接引用。
- 行为、命令、路径或版本变化时，在同一次改动中更新文档；过时内容归档，不留在当前阅读路径。

## 验证

修改时先运行对应领域测试。默认测试不访问真实 tmux，可在容器或沙箱内执行：

```bash
python3 -m compileall -q bridge mcp_server stb_cli
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 bridge/local_bridge.py --help
python3 mcp_server/server.py --help
```

`tests/host_tmux/` 会创建隔离 tmux server，只能在容器外的宿主机执行。涉及 tmux、daemon、binding 或恢复逻辑时，再运行：

```bash
python3 -m unittest discover -s tests/host_tmux -p 'test_*.py' -v
```

完整说明见 `docs/development/testing.md`。
