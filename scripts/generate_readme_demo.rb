#!/usr/bin/env ruby
# frozen_string_literal: true

require "cgi"
require "fileutils"

OUT = File.expand_path("../assets/readme-demo/frames", __dir__)
FileUtils.mkdir_p(OUT)

FRAMES = [
  {
    step: "01 连接共享终端",
    badge: "OBSERVE",
    badge_color: "#38bdf8",
    terminal: [
      ["$ stb attach local-33", "#e2e8f0"],
      ["已进入托管 tmux：local-33  pane=%3", "#94a3b8"],
      ["", "#e2e8f0"],
      ["local-33 %", "#4ade80"]
    ],
    agent: [
      ["USER", "#38bdf8"],
      ["检查磁盘占用，先不要清理。", "#f8fafc"],
      ["", "#f8fafc"],
      ["CODEX", "#a78bfa"],
      ["已连接同一个真实 Shell。", "#cbd5e1"],
      ["先只读观察，不申请写入租约。", "#cbd5e1"]
    ],
    footer: "tmux 保存真实上下文 · Human 与 Codex 看见同一份输出"
  },
  {
    step: "02 只读观察",
    badge: "NO LEASE",
    badge_color: "#38bdf8",
    terminal: [
      ["local-33 % df -h /", "#e2e8f0"],
      ["Filesystem   Size  Used Avail Capacity  Mounted on", "#94a3b8"],
      ["/dev/vda1    120G  112G  8.0G      94%  /", "#fb7185"],
      ["", "#e2e8f0"],
      ["local-33 % du -xhd1 /var 2>/dev/null | sort -h", "#e2e8f0"],
      ["8.4G   /var/cache", "#fbbf24"],
      ["12G    /var/log", "#fbbf24"],
      ["23G    /var", "#fbbf24"]
    ],
    agent: [
      ["READ DELTA", "#38bdf8"],
      ["根分区使用率 94%", "#f8fafc"],
      ["主要空间来自日志和包缓存。", "#cbd5e1"],
      ["", "#f8fafc"],
      ["下一步", "#a78bfa"],
      ["给出完整命令，等待人工批准。", "#cbd5e1"]
    ],
    footer: "观察与写入分离 · 查看历史不占用 Execution Lease"
  },
  {
    step: "03 形成任务块",
    badge: "PLAN",
    badge_color: "#a78bfa",
    terminal: [
      ["local-33 %", "#4ade80"],
      ["", "#e2e8f0"],
      ["# 当前没有命令被发送到终端", "#64748b"],
      ["# Codex 正在等待明确授权", "#64748b"]
    ],
    agent: [
      ["TERMINAL TASK BLOCK", "#a78bfa"],
      ["目标  回收磁盘空间", "#f8fafc"],
      ["证据  /var/log 12G · cache 8.4G", "#cbd5e1"],
      ["风险  删除旧日志与包缓存", "#fbbf24"],
      ["预算  预计 1–3 分钟", "#cbd5e1"],
      ["状态  等待人工批准", "#fb7185"]
    ],
    footer: "Task Block 记录目标、证据、风险和预算 · 不隐藏执行"
  },
  {
    step: "04 人工批准",
    badge: "LEASE GEN 12",
    badge_color: "#4ade80",
    terminal: [
      ["即将执行：", "#94a3b8"],
      ["sudo journalctl --vacuum-time=14d && \\", "#f8fafc"],
      ["  sudo apt-get clean", "#f8fafc"],
      ["", "#e2e8f0"],
      ["[Human approved]", "#4ade80"],
      ["local-33 % sudo journalctl --vacuum-time=14d && \\", "#e2e8f0"],
      ["  sudo apt-get clean", "#e2e8f0"]
    ],
    agent: [
      ["EXECUTION LEASE", "#4ade80"],
      ["pane      %3", "#cbd5e1"],
      ["generation 12", "#cbd5e1"],
      ["state     ACTIVE", "#4ade80"],
      ["", "#e2e8f0"],
      ["命令以可见文本进入同一 Shell。", "#f8fafc"]
    ],
    footer: "新用户意图授予新 generation · Bridge 在本地强制校验"
  },
  {
    step: "05 执行与等待",
    badge: "RUNNING",
    badge_color: "#fbbf24",
    terminal: [
      ["Vacuuming done, freed 13.2G of archived journals.", "#cbd5e1"],
      ["Cleaning package cache...", "#cbd5e1"],
      ["[██████████████████░░]  90%", "#fbbf24"],
      ["", "#e2e8f0"],
      ["Human 可随时按 Ctrl+C", "#64748b"]
    ],
    agent: [
      ["EVENT-DRIVEN WAIT", "#fbbf24"],
      ["不轮询完整 scrollback", "#f8fafc"],
      ["不持续消耗模型 Token", "#f8fafc"],
      ["", "#e2e8f0"],
      ["完成 / 取消 / Human Override", "#cbd5e1"],
      ["任一事件都会唤醒会话", "#cbd5e1"]
    ],
    footer: "长任务由本地 Bridge 等待 · 状态变化时再唤醒 Agent"
  },
  {
    step: "06 验证结果",
    badge: "COMPLETED",
    badge_color: "#4ade80",
    terminal: [
      ["local-33 % df -h /", "#e2e8f0"],
      ["Filesystem   Size  Used Avail Capacity  Mounted on", "#94a3b8"],
      ["/dev/vda1    120G   81G   39G      68%  /", "#4ade80"],
      ["", "#e2e8f0"],
      ["✓ reclaimed 31G", "#4ade80"],
      ["local-33 %", "#4ade80"]
    ],
    agent: [
      ["RESULT", "#4ade80"],
      ["磁盘使用率 94% → 68%", "#f8fafc"],
      ["释放空间约 31G", "#f8fafc"],
      ["", "#e2e8f0"],
      ["EVIDENCE", "#38bdf8"],
      ["命令、输出、租约和事件已审计", "#cbd5e1"]
    ],
    footer: "只返回有界结果与证据 · 终端历史仍完整保留在 tmux"
  },
  {
    step: "07 人类始终拥有控制权",
    badge: "HUMAN FIRST",
    badge_color: "#fb7185",
    terminal: [
      ["local-33 %", "#4ade80"],
      ["", "#e2e8f0"],
      ["Ctrl+C  →  HUMAN_INTERRUPT", "#fb7185"],
      ["           lease generation 12 REVOKED", "#fb7185"],
      ["", "#e2e8f0"],
      ["下一条旧决策：DENIED before pane", "#fbbf24"]
    ],
    agent: [
      ["SHARED TERMINAL BRIDGE", "#a78bfa"],
      ["同一个真实 Shell", "#f8fafc"],
      ["默认观察 · 明确授权", "#f8fafc"],
      ["可见执行 · 随时接管", "#f8fafc"],
      ["", "#e2e8f0"],
      ["Human intent, locally enforced.", "#4ade80"]
    ],
    footer: "Codex 执行人的意图 · Human Ctrl+C 永远具有最高优先级"
  }
].freeze

def esc(value)
  CGI.escapeHTML(value.to_s)
end

def text_lines(lines, x:, y:, size: 19, gap: 31)
  lines.each_with_index.map do |(text, color), i|
    next "" if text.empty?

    %(<text x="#{x}" y="#{y + i * gap}" fill="#{color}" font-size="#{size}" font-family="SFMono-Regular, Menlo, Monaco, 'PingFang SC', monospace">#{esc(text)}</text>)
  end.join("\n")
end

FRAMES.each_with_index do |frame, index|
  svg = <<~SVG
    <svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675" viewBox="0 0 1200 675">
      <defs>
        <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="#07111f"/>
          <stop offset="1" stop-color="#111827"/>
        </linearGradient>
        <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
          <feDropShadow dx="0" dy="16" stdDeviation="22" flood-color="#000" flood-opacity="0.35"/>
        </filter>
      </defs>
      <rect width="1200" height="675" fill="url(#bg)"/>
      <circle cx="1060" cy="-40" r="260" fill="#312e81" opacity="0.22"/>
      <circle cx="80" cy="690" r="250" fill="#0e7490" opacity="0.16"/>

      <text x="42" y="42" fill="#f8fafc" font-size="24" font-weight="700" font-family="Inter, 'PingFang SC', sans-serif">Shared Terminal Bridge</text>
      <text x="330" y="42" fill="#64748b" font-size="16" font-family="Inter, 'PingFang SC', sans-serif">Codex 清理磁盘 · 安全协作演示</text>
      <rect x="914" y="18" rx="15" width="244" height="32" fill="#{frame[:badge_color]}" opacity="0.14"/>
      <text x="1036" y="40" text-anchor="middle" fill="#{frame[:badge_color]}" font-size="15" font-weight="700" font-family="Inter, 'PingFang SC', sans-serif">#{esc(frame[:badge])}</text>

      <g filter="url(#shadow)">
        <rect x="42" y="72" width="720" height="528" rx="16" fill="#0b1220" stroke="#263449"/>
        <rect x="42" y="72" width="720" height="48" rx="16" fill="#151f30"/>
        <rect x="42" y="104" width="720" height="16" fill="#151f30"/>
        <circle cx="68" cy="96" r="6" fill="#fb7185"/>
        <circle cx="89" cy="96" r="6" fill="#fbbf24"/>
        <circle cx="110" cy="96" r="6" fill="#4ade80"/>
        <text x="402" y="102" text-anchor="middle" fill="#94a3b8" font-size="15" font-family="SFMono-Regular, Menlo, monospace">managed tmux · local-33 · pane %3</text>
        #{text_lines(frame[:terminal], x: 66, y: 158, size: 18, gap: 38)}
        <rect x="67" y="560" width="10" height="22" fill="#4ade80" opacity="#{index.even? ? '0.95' : '0.28'}"/>
      </g>

      <g filter="url(#shadow)">
        <rect x="782" y="72" width="376" height="528" rx="16" fill="#101827" stroke="#303d55"/>
        <rect x="782" y="72" width="376" height="48" rx="16" fill="#192338"/>
        <rect x="782" y="104" width="376" height="16" fill="#192338"/>
        <circle cx="810" cy="96" r="12" fill="#7c3aed" opacity="0.9"/>
        <text x="810" y="101" text-anchor="middle" fill="#fff" font-size="14" font-weight="700" font-family="Inter, sans-serif">C</text>
        <text x="834" y="102" fill="#e2e8f0" font-size="16" font-weight="700" font-family="Inter, 'PingFang SC', sans-serif">Codex</text>
        <text x="1132" y="102" text-anchor="end" fill="#64748b" font-size="13" font-family="Inter, 'PingFang SC', sans-serif">#{esc(frame[:step])}</text>
        #{text_lines(frame[:agent], x: 808, y: 164, size: 17, gap: 42)}
      </g>

      <rect x="42" y="620" width="1116" height="1" fill="#263449"/>
      <text x="600" y="650" text-anchor="middle" fill="#94a3b8" font-size="16" font-family="Inter, 'PingFang SC', sans-serif">#{esc(frame[:footer])}</text>
    </svg>
  SVG

  File.write(File.join(OUT, format("frame-%02d.svg", index)), svg)
end

puts "Generated #{FRAMES.length} SVG frames in #{OUT}"
