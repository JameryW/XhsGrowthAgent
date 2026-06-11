# Fix Creating Phase Replay Display & Brief Card Logic

## Goal

修复 WorkflowReplay 和 Dashboard 中"创作"阶段（creating phase）的数据展示问题：商单模式下的节点数据无法正确映射和显示，同时确保 trend/brief 两种工作流模式下各节点数据展示逻辑完整准确。

## Requirements

* R1: 修复 `phaseAgentMap.creating` 映射——改为 `shooting_planner`（brief 模式的创作阶段核心节点），并在 replay 中根据 `workflow_mode` 动态选择
* R2: CREATING 模板增加 `brief_content` 和 `shooting_plan` 的展示区域（商单内容卡片 + 拍摄计划卡片）
* R3: CREATING 模板的 `v-if` agent 列表补充 brief 模式节点（brief_analyzer, brief_gate, shooting_planner）
* R4: ContentCards.vue 在 brief 模式下展示 shooting_plan 数据（当 copy_content 为空时）
* R5: WorkflowTimeline.vue 补充 brief 模式节点的完成状态判断

## Acceptance Criteria

* [ ] WorkflowReplay 中点击"创作"节点能正确选中对应 checkpoint（brief 模式 → shooting_planner，trend 模式 → copywriter）
* [ ] brief 模式工作流在 creating 阶段展示 brief_content 商单摘要卡片 + shooting_plan 拍摄计划卡片
* [ ] trend 模式工作流不受影响，copy_content 仍正常展示
* [ ] WorkflowTimeline 中 brief 模式节点（brief_analyzer, brief_gate, shooting_planner）的完成状态正确显示
* [ ] ContentCards 中 shooting_plan 数据有对应展示（当 copy_content 为空时仍可见）

## Definition of Done

* Lint / typecheck green
* 手动验证两种工作流模式在 Dashboard 和 WorkflowReplay 页面的展示正确性

## Technical Approach

### 核心修改

**1. WorkflowReplay.vue — phaseAgentMap 动态映射**

将 `phaseAgentMap.creating` 从硬编码 `version_generator` 改为根据 `workflow_mode` 动态选择：
- trend 模式 → `copywriter`
- brief 模式 → `shooting_planner`

```typescript
const phaseAgentMap = computed(() => ({
  scouting: 'trend_scout',
  planning: 'content_strategist',
  creating: effectiveState.value?.workflow_mode === 'brief' ? 'shooting_planner' : 'copywriter',
  reviewing: 'review_gate',
  publishing: 'publisher',
  analyzing: 'analyst',
  engaging: 'engagement',
}))
```

**2. WorkflowReplay.vue — CREATING 模板扩展**

在 CREATING 模板中增加 brief 模式的展示区域：
- `v-if` agent 列表补充 `brief_analyzer`, `brief_gate`, `shooting_planner`
- 在 copy_content 区域之前，增加 brief_content 摘要卡片（brand_name, product_name, selling_points）
- 增加 shooting_plan 卡片（title_candidates, body_copy, shooting_angles, outfits）
- 两者用 `v-if="effectiveState?.brief_content"` / `v-if="effectiveState?.shooting_plan"` 条件渲染

**3. ContentCards.vue — brief 模式兼容**

当 `copy_content` 为空但 `shooting_plan` 有数据时，展示 shooting_plan 的核心字段。

**4. WorkflowTimeline.vue — 补充 brief 节点**

在 `isSubStepCompleted` 或 subSteps 定义中补充 brief 模式节点。

## Decision (ADR-lite)

**Context**: creating 阶段的 agent 映射只考虑了 trend 模式，phaseAgentMap 硬编码为 `version_generator`，模板中也只展示 copy_content。
**Decision**: 根据 workflow_mode 动态映射 creating 阶段的核心 agent，模板增加 brief 模式专属数据展示。
**Consequences**: 代码逻辑略微复杂（需要 workflow_mode 判断），但两种模式的数据展示清晰分离，互不影响。

## Out of Scope

* 后端数据产出逻辑修改
* 新增 API 接口
* checkpoint history 接口修改

## Technical Notes

### 关键文件
* `frontend/src/views/WorkflowReplay.vue` — replay 页面，phaseAgentMap + CREATING 模板
* `frontend/src/components/dashboard/ContentCards.vue` — Dashboard 内容卡片
* `frontend/src/components/dashboard/WorkflowTimeline.vue` — 时间线节点状态
* `frontend/src/components/dashboard/ShootingPlanPanel.vue` — 拍摄计划面板（已独立组件）
* `frontend/src/stores/workflow.ts` — effectiveState / replayState 数据流

### 数据结构
* `CopyContent`: selected_title, body_text, hashtags, cta, emoji_usage, tone, title_candidates
* `BriefContent`: brand_name, product_name, selling_points, required_hashtags, content_direction, confidence
* `ShootingPlan`: creator_nickname, content_direction, title_candidates, body_copy, shooting_angles, outfits
* `CheckpointSnapshot`: 包含 copy_content + brief_content + shooting_plan

### Brief 模式 Graph 路径
```
orchestrator → brief_analyzer → brief_gate → shooting_planner → draft_gate → copywriter → review_gate
```
Trend 模式 Graph 路径
```
orchestrator → trend_scout → content_strategist → copywriter → visual_designer → review_gate
```
两者共享 copywriter 节点，但 brief 模式在 copywriter 之前有 shooting_planner 产出 shooting_plan。
