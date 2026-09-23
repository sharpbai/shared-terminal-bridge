# 实操基线：查看 local-33 磁盘占用 15

日期：2026-09-21  
Codex thread：`01a0c412-724d-7670-a064-978be4b424cb`  
托管会话：`verify33`  
目标 pane：`%1`

## 结论

本次体感顺畅与记录一致。全程没有 TUI，没有 Human Override、lease 冲突、
MCP 错误、Runner 拒绝、空增量轮询或等待阻塞。普通诊断使用
TaskBlockRunner，高 I/O 扫描使用“登记—用户批准—提交—本地等待”，删除动作
均在精确路径确认后执行并使用只读 block 验证。

## 整体数据

- 用户回合：14。
- 活跃执行时间：604.434 秒，约 10.1 分钟。
- 平均每回合：43.174 秒；最长 69.731 秒。
- 平均首 token：5.605 秒；最长 9.364 秒。
- Input token：4,727,460。
- Cached input：4,642,304，约 98.2%。
- 非缓存 input：85,156。
- Output token：13,409。
- Reasoning output：2,815。
- MCP 调用：49 次。

MCP 分布：

| 工具 | 次数 |
|---|---:|
| `terminal_session_acquire` | 13 |
| `terminal_task_block_execute` | 10 |
| `terminal_submit` | 7 |
| `terminal_wait_job` | 7 |
| `terminal_long_run_request` | 6 |
| `terminal_long_run_approve` | 5 |
| `terminal_job_status` | 1 |

## 与会话 14 对比

| 指标 | 会话 14 | 会话 15 | 变化 |
|---|---:|---:|---:|
| 用户回合 | 15 | 14 | -6.7% |
| 活跃时间 | 1,743.958s | 604.434s | -65.3% |
| Input token | 22,439,069 | 4,727,460 | -78.9% |
| 非缓存 input | 478,749 | 85,156 | -82.2% |
| Output token | 29,729 | 13,409 | -54.9% |
| Reasoning output | 8,915 | 2,815 | -68.4% |
| TUI 按键 | 91 | 0 | -100% |
| 全屏读取 | 26 | 0 | -100% |

两次任务范围不完全相同，不应将整体降幅归因于单一代码改动。会话 14
仅 TestDisk TUI 就消耗约 878.9 秒和 14.303M input；会话 15 完全避开该路径，
是整体改善的主因。

## 可比的首次磁盘检查

| 指标 | 会话 14 | 会话 15 | 变化 |
|---|---:|---:|---:|
| 耗时 | 28.471s | 42.756s | +50.2% |
| Input token | 172,781 | 171,482 | -0.8% |
| Output token | 771 | 889 | +15.3% |

会话 15 首轮的 Bridge 工具时间只有约 7.2 秒：`acquire` 约 1.05 秒，
三步 Runner 约 6.18 秒。其余约 35.5 秒为模型首 token、工具发现与两段
编排时间，因此普通首检未继续加速，但 token 保持稳定。

## 剩余问题

1. **Skill 重复读取**：14 个回合中有 13 次读取完整 `SKILL.md`。命令耗时可忽略，
   且内容大多命中 prompt cache，但仍会扩大每次模型输入。这是 Codex Skill
   加载边界，不是 Bridge RPC 问题。
2. **一次多余 status**：`terminal_wait_job` 已返回完整输出后，又调用了一次
   `terminal_job_status(include_output=true)`。应在 `output_complete=true` 时禁止这一步。
3. **wait 预算偏短**：长任务多数显式传入 60 秒，没有采用推荐的 10 分钟本地
   等待。本次命令均在 25 秒内完成，未导致轮询；但对真正长任务仍是潜在
   额外采样点。
4. **扫描时间估计保守**：多个 `du` 按 5–10 分钟申请，实际因页缓存或目录
   结构在数十秒内完成。审批本身是正确的高 I/O 边界，后续可用历史 job
   数据改善预计，不应因本次快就取消批准。
5. **权限失败仍需一轮**：`sudo -n du ... /home` 正确地立即失败，无阻塞、无修改；
   用户进入 root shell 后才重新扫描。这符合“不对目标环境做假设”，不建议
   通过隐式提权优化。

## 下一步优先级

1. 将 `terminal_wait_job` 的工具说明和调用校验进一步收紧：长任务默认不显式
   传短 `wait_ms`；`output_complete=true` 后不再读 status。
2. 将同会话、同文件系统的历史 job 耗时用于建议预计，但不改变
   `high_io/full_scan` 的人工批准边界。
3. 后续性能基准分成“普通首检”“长扫描”“写入+验证”和“TUI”四类，
   避免用整体 token 降幅掩盖普通首检未变快的问题。
