# API v9 程序能力选路验证

日期：2026-09-21  
Bridge/MCP：v0.14.0 / API v9

## 目标

在不建设通用 TUI 自动化的前提下，将全屏程序的默认选路改为：

1. 先查官方 CLI/CMD/batch/script 能力；
2. 非交互路径不足时，由人操作 TUI 到指定检查点；
3. Agent 逐键操作仅作最后 fallback。

## 已验证的不变量

- `terminal_program_profile` 不要求 lease，不读取 pane，不发送按键或命令。
- API v8 daemon 不发布该工具，API v9 才发布。
- TestDisk/PhotoRec 画像只是本地指引，需先用安全版本命令确认目标版本。
- Runner 只精确放行：
  - `fdisk -l TARGET` 或 `fdisk --list TARGET`；
  - `blkid -p TARGET` 或带非负整数 `-O OFFSET`；
  - TestDisk 版本探测；
  - `qemu-nbd --version` / `qemu-nbd -V`。
- `fdisk TARGET`、无 `-p` 的 `blkid`、`testdisk DEVICE`、`qemu-nbd --connect`
  均在写入 pane 前被拒绝。

## 自动回归

完整回归 66 项通过，包含上述放行/拒绝模板、本地画像无终端写入、
API v8/v9 发布边界、MCP 转发及隔离 tmux 端到端基线。

## 剩余范围

本轮不包含通用 TUI 控件识别、视觉理解、终端仿真或自动菜单规划。
后续只考虑前台进程生命周期保护和 changed-row snapshot 等低成本措施。
