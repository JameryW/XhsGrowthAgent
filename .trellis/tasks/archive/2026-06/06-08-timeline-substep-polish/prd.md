# Timeline Substep Polish

## Goal

优化 WorkflowTimeline 的子步骤体验：精简标签、多阶段子步骤支持、视觉打磨、回放模式完善。

## What I already know

* 当前只有 creating 阶段有子步骤展开（6 个：copywriter/draft_gate/viral_matcher/blogger_scout/blogger_gate/visual_designer）
* 后端图拓扑：
  - **reviewing**: review_gate → [publisher | revise_content → copywriter]
  - **publishing**: publisher → analyst
  - **engagement**: engagement → [orchestrator | END]（已在后端但前端未在 analyzing 后显示）
* 子步骤标签当前用的是主阶段的 i18n key，偏长（如"博主发现""博主选择"）
* expandedPhase 只在 creating/reviewing 阶段展开 creating 子步骤
* 回放模式：主节点可点击跳转 checkpoint，子步骤也已绑定点击但标签区域小
* 无展开/折叠动画过渡（v-if 硬切换）

## Assumptions (temporary)

* reviewing 和 publishing 阶段可以各定义子步骤
* 子步骤标签用更短的 i18n key
* 展开/折叠用 Vue transition 组件实现动画

## Open Questions

* (none blocking — all derivable or preference-based)

## Requirements (evolving)

1. **标签精简**: 子步骤标签缩短为 2 字（文案/草稿/爆款/发现/选择/视觉），新增 i18n key
2. **多阶段子步骤**:
   - reviewing: review_gate, revise_content
   - publishing: publisher, engagement
3. **视觉打磨**:
   - 子步骤间连接线（虚线箭头）
   - 展开/折叠用 `<Transition>` 平滑动画
   - 移动端适配（子步骤更紧凑）
4. **回放模式**: 子步骤可点击跳转到对应 agent 的 checkpoint，选中态高亮

## Acceptance Criteria (evolving)

- [ ] 子步骤标签均为短标签（中文 ≤3 字，英文 ≤12 chars）
- [ ] reviewing/publishing 阶段有子步骤展开
- [ ] 子步骤区域展开/折叠有平滑过渡动画
- [ ] 回放模式下子步骤可点击跳转并高亮
- [ ] 移动端子步骤不溢出、不横向滚动
- [ ] pnpm build 无错误

## Definition of Done

* pnpm build 通过
* 手动验证各阶段展开/折叠
* 回放模式点击子步骤跳转正常

## Out of Scope

* 修改后端图拓扑或 API
* 修改 Agent Timeline 详情区域
* 新建独立子步骤组件（保持内联）

## Technical Notes

* 主文件: `frontend/src/components/dashboard/WorkflowTimeline.vue`
* i18n: `frontend/src/locales/zh-CN.json`, `frontend/src/locales/en.json`
* 后端图: `backend/graph/builder.py`
* 当前子步骤用 v-if 硬切，改用 `<Transition name="expand">` + max-height 动画
