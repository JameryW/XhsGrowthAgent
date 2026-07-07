# 自由创作模式 — 完全工作流隔离

## Goal

自由创作模式（/tui?mode=free）必须与工作流系统完全隔离：不绑定、不创建、不操作任何工作流。当前 free 模式仍会在 TUI 初始化时绑定 `workflowStore.activeThreadId` 并显示「恢复活跃工作流」，且工作流操作命令（/status /pause /resume /cancel /approve /reject）未被禁用。修复使 free 模式仅用原子能力自由编排，零工作流耦合。

## What I already know

- `AgentTUI.vue:875` `isFreeCreationEntry = computed(() => route.query.mode === 'free')`
- `AgentTUI.vue:1020-1024` onMounted 无条件检查 `workflowStore.activeThreadId`，有则绑 `activeThreadId` + 显示「恢复活跃工作流」——free 模式未跳过。
- `AgentTUI.vue:726-731` /status /pause /resume /cancel /approve /reject 未按 free 模式分流，仍操作 `activeThreadId`。
- `AgentTUI.vue:719-725` /start 已禁用 free（`freeStartDisabled`）；`701-702` 普通文本 free 模式禁用 agent（`freeAgentUnavailable`）。
- i18n：free 模式文案齐（freeFlow/freeWelcomeHint/freeTopic/freeAgentUnavailable/freeStartDisabled），缺「工作流操作命令禁用」文案。

## Requirements

- free 模式下 onMounted 跳过 `workflowStore.activeThreadId` 绑定 + 「恢复活跃工作流」提示。
- free 模式下 /status /pause /resume /cancel /approve /reject 全部禁用，提示 free 模式不操作工作流。
- `activeThreadId` 在 free 模式下保持 null（不绑任何 thread）。
- 不影响非 free 模式（普通 TUI 入口）的活跃工作流恢复 + 命令行为。

## Acceptance Criteria

- [ ] free 模式进入 TUI 不显示「恢复活跃工作流」，不绑 activeThreadId
- [ ] free 模式下 /status /pause /resume /cancel /approve /reject 提示禁用，不调工作流 API
- [ ] 非 free 模式行为不变（活跃工作流恢复 + 命令正常）
- [ ] i18n key `tui.freeWorkflowOpDisabled` 补齐（en+zh）
- [ ] npm run build 过 + typecheck 过

## Definition of Done

- npm run build + vue-tsc 绿
- 改动文件 lint 过
- 无回归（非 free 模式不受影响）

## Out of Scope

- free 模式下 agent 编排能力本身（已由 freeAgentUnavailable/freeStartDisabled 处理）
- /mode /help /clear 命令（非工作流操作，free 模式可用）

## Technical Notes

- 文件：`frontend/src/views/AgentTUI.vue`、`frontend/src/locales/{en,zh-CN}.json`
- 修复点 1：行 1020-1024 包 `if (!isFreeCreationEntry.value && workflowStore.activeThreadId)`
- 修复点 2：行 726-731 各 case 加 `if (isFreeCreationEntry.value) { writeLineColored(t('tui.freeWorkflowOpDisabled'), ANSI.YELLOW); break }`
