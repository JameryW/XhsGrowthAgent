# Free-mode TUI: /mode switch i18n + /drafts empty-state hint

## Problem

原 free-mode TUI 优化 campaign（#215-245，全 merged）i18n 了 free 命令文案，但漏了 `/mode`（free + workflow 共用路径）的切换消息与 `/help` 文案，仍硬编码英文。free 模式默认 zh-CN，故体验不一致。另 `/drafts` 空列表仅显 `（无）`，无下一步 hint——与其余命令 cue 模式不一致（空 list 是发现断点）。

## Slice 1 — `/mode` switch i18n

硬编码英文（`frontend/src/views/AgentTUI.vue`）：
- 行 869（agent→cmd）: `Switched to command mode`
- 行 999（cmd→agent）: `Switching to agent mode...`
- 行 1608/1634/1643（`/help` 的 `/mode` 行）: `Switch to command mode` / `Switch to agent mode`
- 行 1663（`modeLabel`）: `AGENT` / `CMD`

已有兄弟路径 i18n'd（`agentDisconnectedMax` 行 2039）。新增 keys（zh + en）：
- `tui.modeSwitchedToCommand` — agent→cmd 消息
- `tui.modeSwitchingToAgent` — cmd→agent 消息
- `tui.helpSwitchToCommand` / `tui.helpSwitchToAgent` — /help 文案
- `tui.modeLabelAgent` / `tui.modeLabelCmd` — statusbar badge

`/help` 的 `/mode` 行可能复用 `freeCmdMode` 或新独立 key——决策时取最小（复用现有 freeCmdMode 不行因 workflow 模式也用 /help，文案应通用）→ 新独立 help* key。

## Slice 2 — `/drafts` empty-state hint

`draftsNone` = `（无）`。空列表无 actionable hint。改为带下一步提示：无草稿时追加 dim 行指向"直接输入文字创作"或 `/suggest`（free 默认 agent mode，typing 即创建）。新增 key `tui.draftsNoneHint`。非空不变。

## Scope (non-goals)

- 不改后端、不改 agent 工具链、不改 TS extension。
- 不碰 `/mode` 逻辑、不改 reconnect 行为（只 i18n 文案）。
- `modeLabel` AGENT/CMD：i18n 但保留英文 token（badge 是空间受限的 UI token，zh 用 `代理`/`命令` 可能更清晰——决策时取 zh 友好短词）。

## Acceptance

- free 模式 zh-CN 下 `/mode` 切换、`/help` 的 /mode 行、statusbar badge 均显示中文。
- `/drafts` 空列表显示 hint 行。
- en locale 同步。
- vue-tsc 绿（前端 gate，[[vite-build-oom-low-ram-box]]）。
- 现有 frontend 测试不回归。

## PR 拆分

按 [[separate-pr-per-feature]]：Slice 1 与 Slice 2 各从 main 新建分支、各提 PR（用户选择"两切片合并一轮"= 同轮两个 PR，非一个 PR 装两个特性）。
