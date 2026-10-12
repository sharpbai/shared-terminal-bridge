# Changelog

## v0.15.1 — 2026-10-12

- 修复恢复旧 Codex 会话后 `CODEX_TURN_ID_UNAVAILABLE`：按每次 MCP 请求的宿主 `x-codex-turn-metadata` 解析 thread/turn 身份，与本地真实用户回合核对，不再用会话创建时间猜测租约归属。
- 请求身份缺失、矛盾或过期时拒绝授权；模型工具参数不能指定身份。保留 Human Override、generation 和长任务批准边界。
- 增加默认关闭的脱敏身份诊断及回归测试；真实恢复会话已由人工验证能够获取租约。
- 按职责重组 Bridge、MCP、CLI、测试和文档，提供小入口导航，降低人和 Agent 的局部维护成本。
- 相关项目导航加入独立 Tools 仓库。

- 增加 GitHub Actions：Python 3.11/3.12 容器安全测试，以及独立宿主 runner 的真实 tmux 集成测试。
- 为 Bridge 领域 service 增加显式依赖清单和运行时受限 `ServiceContext`，并以静态一致性测试阻止依赖静默扩张。
- 统一 Bridge/MCP 版本来源，增加当前文档、CHANGELOG、MCP metadata 和 API feature gate 的版本一致性测试。
- 修复 Linux tmux 初始托管 pane 未继承 10 万行历史上限的问题：在同一命令队列中先设置全局选项，再创建 session。

Bridge API 保持 v9。升级后需重新连接 MCP（或重启 Codex 应用）以加载身份解析修复；无需重建托管 tmux 会话。宿主元数据的信任范围是本地 Codex 及其日志，不是面对不可信客户端的密码学认证。

## v0.15.0 — 2026-09-24

- 增加 STB-RDC Exclusive Mode contract。
- 用户明确选择 STB-RDC 后，RDC 被限定为 transport/bootstrap；目标主机操作默认必须经过 STB。
- 独立 RDC filesystem/search/process/shell/edit capability 需要一次性、capability-scoped 人工旁路批准。
- 旁路不得覆盖 Human Override、lease revoke、stale generation、Pane ACL 或 long-run approval。
- modern `server/discover` 与 legacy `initialize` 发布一致的 Exclusive Mode instructions。
- 增加 Exclusive Mode 文档与自动化回归测试。
- 更新路线图，纳入 2026-09-22 至 2026-09-24 的 STB-RDC、公开文档和远程 capability-plane 演进。

限制：v0.15.0 强制 STB 自身的本地安全边界，并通过 MCP contract/routing policy 让当前客户端 fail closed；独立 RDC tools 的物理隐藏仍需要 RDC/宿主提供 capability filtering 或 policy hook。

## v0.14.0 — 2026-09-21

- Bridge API v9 增加 `terminal_program_profile`。
- 首批提供 TestDisk/PhotoRec CLI、CMD、batch 能力选路。
- 只读 TaskBlockRunner 精确支持 `fdisk -l`、`blkid -p`、TestDisk 版本探测和 `qemu-nbd --version`。
- 固化轻量 TUI 策略：CLI/CMD 优先，其次人类协同检查点，最后才是 Agent 受限 fallback。
- 完成会话 15 性能回归，验证无 TUI 日常工作流。
