# free-draft-revise-next-step-hint

## Goal

`/draft <id>` 详情视图对 needs_revision/rejected 草稿显示 revision_hints 列表，但无"下一步"指引——用户看到评估建议却不知改完该重新 `/evaluate`。approved 草稿有 analytics hint、mock-published 有 re-publish hint，唯独 needs_revision/rejected 闭环断裂。加黄色 hint 指向"/edit 改后重新 /evaluate"，补全可发现性。

## What I already know

- `frontend/src/views/AgentTUI.vue` `handleDraft`（1166+）详情视图：
  - line 1214-1226：渲染 last_evaluation（score/decision）+ revision_hints（• 列表）。
  - line 1232-1241：published + post_url + analytics hint（approved 真发布）/ mock hint。
  - **缺**：decision ∈ {needs_revision, rejected} 时无 next-step hint。
- `/edit <id> <field> <value>`（#225 merged）支持改 title/niche/content_angle/target_audience。
- `/evaluate` 可对已存草稿重复跑（evaluate_draft 不限次数，回写 last_evaluation）。
- revision_hints 持久化在 last_evaluation（#222）。
- i18n 模式：hint 用 `t('tui.xxx')`，中英双 locale。

## Requirements

- `/draft <id>` 详情视图：当 `last_evaluation.decision` ∈ {needs_revision, rejected} 且 `revision_hints` 非空时，在 hints 列表后加黄色 next-step hint：指向 `/edit` 改字段 + 重新 `/evaluate`。
- 文案含 draft_id 占位（指向具体命令 `/edit <id> ...`）。
- approved 草稿不变（已有 analytics hint）；无 revision_hints 的 needs_revision 不显示（无内容可指引）。
- i18n 中英双 locale 新增 1 key。
- spec 同步：free-creation.md handleDraft detail 子节加 next-step hint 行为。

## Acceptance Criteria

- [ ] decision=needs_revision + 有 hints → 详情显示 next-step hint（黄）
- [ ] decision=rejected + 有 hints → 同上
- [ ] decision=approved → 不显示 next-step hint（保持 analytics hint）
- [ ] needs_revision 但无 revision_hints → 不显示 next-step hint
- [ ] 无 last_evaluation → 不显示
- [ ] hint 文案含 draft_id
- [ ] 中英 i18n key 齐
- [ ] vue-tsc typecheck 绿

## Definition of Done

- TUI handleDraft + i18n 中英 + spec 同步
- vue-tsc 绿（前端 gate，build 留 CI 因 OOM）

## Technical Approach

`handleDraft` 渲染 revision_hints 循环后，加条件：
```js
if ((decision === 'needs_revision' || decision === 'rejected') && hints && hints.length > 0) {
  writeLine(`  ${Y}${t('tui.draftDetailReviseHint', { id: data.draft_id })}${R}`)
}
```
文案：`按上方 hints 用 /edit <id> <field> <value> 修改后重新 /evaluate`（中）/ `Use /edit <id> <field> <value> to revise per the hints above, then /evaluate again`（英）。

## Out of Scope

- 一键应用 revision_hints（自动 /edit）——hints 是自然语言建议，无法机械映射字段，YAGNI。
- evaluate 后自动跳详情——破坏命令式 UX。
- revision_hints 之外其他 next-step（approved→publish 等）——已有路径。

## Technical Notes

- `frontend/src/views/AgentTUI.vue` handleDraft（~1214-1245）
- `frontend/src/locales/zh-CN.json` + `en.json`（draftDetail* 区块）
- `.trellis/spec/backend/free-creation.md` handleDraft detail 子节
- vue-tsc gate（[[vite-build-oom-low-ram-box]]）
- 从 main 新建分支 [[separate-pr-per-feature]]
