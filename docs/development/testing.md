# 测试分层

STB 把不依赖真实 tmux 的快速测试与需要宿主机权限的集成基线分开。

## 默认：容器内单元测试

这组测试使用 fake tmux 或 mock，不创建真实 tmux server，适合日常修改和受限容器：

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

`tests/host_tmux/` 没有 Python package 标记，因此默认 discovery 不会递归进入。

## 容器外：真实 tmux 集成测试

这组测试创建隔离的 tmux socket，并覆盖 binding、daemon 恢复、server identity、托管 session 和 MCP 端到端链路。必须在宿主机执行：

```bash
python3 -m unittest discover -s tests/host_tmux -p 'test_*.py' -v
```

运行前应满足：

- 已安装 `tmux`；
- 当前进程可以创建 Unix socket 和子进程；
- 不在禁止访问宿主机 tmux socket 的沙箱或容器中。

出现 `Operation not permitted` 时先检查执行环境，不应直接判断为代码回归。

## 完成前检查

```bash
python3 -m compileall -q bridge mcp_server stb_cli
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 bridge/local_bridge.py --help
python3 mcp_server/server.py --help
```

涉及 tmux、daemon、binding 或恢复逻辑的改动，还必须在容器外追加真实 tmux 集成测试。

## CI

GitHub Actions 的 `unit` job 在 Python 3.11 和 3.12 上执行容器安全测试、编译和入口检查。`host-tmux` job 运行在独立 Ubuntu 宿主 runner，安装真实 tmux 后执行 `tests/host_tmux/`，不使用 job container。
