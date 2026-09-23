# 实操基线：查看 local-33 磁盘占用 14

日期：2026-09-21  
Codex thread：`01a0c26f-f830-7570-aa1e-cbf21b9f3c3c`  
托管会话：`verify33`  
目标 pane：`%14`

## 结论

API v8 的只读 TaskBlockRunner 已降低普通检查的模型往返；本次性能瓶颈集中在
TestDisk ncurses 全屏交互。后续不建设重型、通用 TUI 自动化，交互策略调整为：

```text
程序原生 CLI/CMD/batch 接口
        ↓ 不满足
人类操作 TUI，模型在检查点观察
        ↓ 确实无法协作
Agent 轻量、受限地操作 TUI
```

## 与会话 13 的可比改善

首次磁盘检查：

| 指标 | 会话 13 | 会话 14 | 变化 |
|---|---:|---:|---:|
| 耗时 | 30.661s | 28.471s | -7.1% |
| Input token | 247,452 | 172,781 | -30.2% |
| Output token | 932 | 771 | -17.3% |

会话 14 首轮仅使用一次 acquire 和一次 TaskBlockRunner。`进入 rescue 看下` 一轮用
两个 task block 完成目录、文件类型、实际占用、表观大小和 metadata 检查，耗时
37.946 秒。

## 整体数据

- 用户回合：15。
- 活跃执行时间：1,743.958 秒，约 29.1 分钟。
- Input token：22,439,069。
- Cached input：21,960,320，约 97.9%。
- 非缓存 input：478,749。
- Output token：29,729。
- Reasoning output：8,915。
- `terminal_submit`：41 次。
- `terminal_wait_job`：39 次。
- `terminal_task_block_execute`：6 次。
- `terminal_key`：91 次。
- `terminal_read`：28 次。

整体 input 较会话 13 下降约 10%，output 下降约 33%，但非缓存 input 增加约 57%。
主要原因是全屏内容频繁变化，难以复用 prompt cache。

## TestDisk TUI 成本

三个主要 TUI 回合合计：

- 91 次按键调用；
- 26 次全屏读取；
- 耗时约 878.9 秒，约 14.6 分钟；
- Input token 约 14.303M，占全会话 input 约 64%。

当前模式是“读整屏 → 模型判断 → 发一个键 → 再读整屏”，单个按键的 Bridge 延迟
很低，但每一步都触发模型采样，属于不合适的交互粒度。

## Runner 首版暴露的问题

六次 Runner 调用中，`fdisk`、`blkid`、`testdisk /version`、`qemu-nbd --version`
相关 block 被保守白名单拒绝，然后回退为单步执行。拒绝发生在整块预检阶段，没有
产生部分终端写入，安全行为正确；但白名单缺少明确只读的命令 profile，造成额外
模型回合。

后续只应增加精确 profile，例如：

- `fdisk -l <image-or-device>`；
- `blkid` 的探测模式；
- `testdisk /version`；
- `qemu-nbd --version`。

不将整个可执行文件笼统标记为只读。

## 全屏退出后的对齐问题

实测尺寸：

```text
tmux client: 103x30
window/pane: 103x29
stty size:   29x103
```

宽度一致，高度差一行是 tmux 状态栏，因此不是 tmux 几何尺寸不一致。更可能是
TestDisk/ncurses 在被强制中断或异常退出后没有完整恢复 alternate screen、自动换行、
光标或终端模式。随后出现的 `elsblk` 还说明 TUI 边界附近存在按键落入 shell 的风险。

`stty sane; reset` 能恢复显示，支持上述判断。今后优先通过程序自身的退出键正常离开；
强制 Ctrl+C 后不得立即发送业务命令，应先确认前台进程已回到 shell，并显式恢复显示。

## TestDisk 可用的非交互方向

TestDisk 官方支持：

```text
testdisk /cmd device command-list
```

命令集包括 `analyze`、`list`、递归 list、`advanced` 和 FAT/NTFS/exFAT 的
`undelete` 入口；PhotoRec 也支持 `/cmd` 和输出目录参数。并非所有选择性 exFAT
恢复操作都能完全批处理，因此必须先探测和小范围验证，不能假设 CMD 能覆盖全部 TUI。

参考：<https://www.cgsecurity.org/testdisk_doc/scripted_run.html>

