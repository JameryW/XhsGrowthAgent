# blogger 选择后增加选笔记风格环节 (draft_gate)

## Goal

在用户选择博主后、进入 shooting_planner/content_analyzer 之前，插入 draft_gate 中断点，让用户可以确认/编辑笔记风格（标题、正文、标签），与 trend 模式中 copywriter 之后的 draft_gate 体验一致。

## What I already know

- **当前 flow**：blogger_gate → blogger_gate_router → shooting_planner → content_analyzer → version_generator → choice_gate → visual_designer
- **缺失环节**：trend 模式中 copywriter → draft_gate（用户确认/编辑草稿），但 blogger 路径没有这个环节
- `draft_gate_node` 已有完整实现：从 copy_content 构建 default_draft，interrupt 等待用户确认/编辑
- `shooting_planner` 输出的 `shooting_plan` 包含 `title_candidates`, `body_copy`, `required_hashtags` 等字段，可作为 draft_gate 的默认草稿来源
- `blogger_gate_router` 当前签名只返回 `shooting_planner | content_analyzer | visual_designer`，需扩展支持 `draft_gate`
- 前端已有 `DraftInput.vue` + `isAwaitingDraft` 状态 + `submitDraft` API，可直接复用

## Assumptions (validated)

- draft_gate 在 blogger 路径中的行为与 copywriter 路径一致：展示默认草稿、用户可编辑、提交后继续
- brief 模式也需要此环节（blogger 选择后同理需要确认笔记风格）
- shooting_plan 中的 body_copy / title_candidates 可直接映射为 draft_content 的 text / title
- default_draft 优先用 copy_content，若为空则从 shooting_plan 构建
- 用户跳过博主选择时也进入 draft_gate
- draft_gate_router 通过 state 中是否存在 `selected_blogger`（非空 dict）判断来源

## Open Questions

(All resolved)

## Requirements

1. 修改 `blogger_gate_router`，选择博主后路由到 `draft_gate` 而非直接到 `shooting_planner`
2. 修改 `draft_gate_node`，当 copy_content 为空时从 shooting_plan 构建 default_draft
3. 确认 `draft_gate → viral_matcher` 的边已存在于 builder 中（当前是 `draft_gate → viral_matcher`，blogger 路径已走过 viral_matcher，需避免循环）
4. 新增边：`draft_gate → shooting_planner`（blogger 路径走这条，跳过 viral_matcher）

## Acceptance Criteria

- [ ] blogger 选择后，工作流在 draft_gate 暂停，前端显示 DraftInput 面板
- [ ] DraftInput 预填充的数据来自 shooting_plan（title_candidates → title, body_copy → text, required_hashtags → hashtags）
- [ ] 用户提交草稿后，工作流继续到 shooting_planner → content_analyzer
- [ ] 用户跳过博主选择时也进入 draft_gate
- [ ] trend 模式 copywriter → draft_gate 的原有流程不受影响
- [ ] 前端 isAwaitingDraft 状态正确触发

## Definition of Done

- 后端路由逻辑修改 + draft_gate_node 适配
- 前端 DraftInput 在新路径下正确工作
- Lint / typecheck 通过
- 手动验证 blogger 选择后出现 draft_gate 中断

## Out of Scope

- draft_gate UI 重新设计（复用现有 DraftInput）
- choice_gate / version_generator 的逻辑变更
- ripple_gate 相关修改

## Technical Notes

### 关键文件

- `backend/graph/routers.py` — blogger_gate_router 需修改返回值和签名
- `backend/graph/builder.py` — 需新增 draft_gate → shooting_planner 边
- `backend/agents/nodes/optimization/draft_gate.py` — 需扩展从 shooting_plan 构建 default_draft
- 前端无需修改（DraftInput + isAwaitingDraft 已就绪）

### 流程对比

**修改前 (blogger 路径)**：
blogger_gate → shooting_planner → content_analyzer → version_generator → choice_gate → visual_designer

**修改后 (blogger 路径)**：
blogger_gate → draft_gate → shooting_planner → content_analyzer → version_generator → choice_gate → visual_designer

**trend 路径不变**：
copywriter → draft_gate → viral_matcher → blogger_scout → blogger_gate → (新路径如上)

### 注意：draft_gate 的出边

当前 builder 中只有 `draft_gate → viral_matcher` 这一条边。blogger 路径不能走 viral_matcher（会产生循环：viral → blogger_scout → blogger_gate → draft_gate → viral → ...）。

需要新增条件边：draft_gate_router 根据 state 判断下一步：
- trend 模式（从 copywriter 来，`selected_blogger` 为空）→ viral_matcher（现有逻辑）
- brief/blogger 模式（从 blogger_gate 来，`selected_blogger` 非空或已走过 blogger 路径）→ shooting_planner

## Decision (ADR-lite)

**Context**: blogger 选择后缺少笔记风格确认环节，用户体验断裂
**Decision**: 在 blogger_gate 与 shooting_planner 之间插入 draft_gate，新增 draft_gate_router 条件边区分来源
**Consequences**: 
  - 增加了 draft_gate_router 路由逻辑的复杂度
  - draft_gate_node 需支持从 shooting_plan 构建 default_draft
  - 前端无需修改，DraftInput + isAwaitingDraft 已可复用
