# Changelog

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
