# 宿主机 tmux 集成测试

本目录的测试会创建和销毁独立的 tmux server/socket，并验证 daemon、binding、恢复和 MCP 端到端行为。

它们不属于默认单元测试，必须在安装了 tmux、允许访问宿主机 tmux socket 的容器外环境执行：

```bash
python3 -m unittest discover -s tests/host_tmux -p 'test_*.py' -v
```

测试使用独立的 tmux socket 名称，不连接日常使用的默认 socket。不要在禁止 Unix socket 或进程创建的沙箱/容器中运行；该环境中的 `Operation not permitted` 表示测试环境不满足条件，不代表业务断言失败。
