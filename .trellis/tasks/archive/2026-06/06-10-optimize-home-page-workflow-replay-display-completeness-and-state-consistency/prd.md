# Optimize Home Page Workflow Replay Display Completeness and State Consistency

## Goal

Fix the Showcase.vue workflow cards so they show complete, consistent content across all statuses (running, completed, error, paused, etc.) — and fix WorkflowReplay.vue node status logic for edge-case phases.

## Decisions

- **otherWorkflows cards**: expanded display — show phase, error, and available data summary (same layout as running/completed)
- **Pipeline progress bar**: keep 6 steps, map `briefing` → scouting position, `engaging` → publishing position

## Requirements

### Showcase.vue — Card Content Consistency

1. **Unify card body template** — extract a shared rendering block so running, completed, and other cards use the same data sections
2. **Add missing sections to running cards** (currently only completed cards show these):
   - `analytics`: views, likes, collects, comments, engagement_rate, insights
   - `publish_result`: post_id, status, published_at, post_url
   - `competitor_posts`: top competitor post with likes/comments
3. **Expand `otherWorkflows` cards** from compact (thread_id only) to full card layout:
   - Header: phase label + status badge + error message (if any)
   - Body: same data summary as running/completed cards
   - Pipeline progress bar
4. **Ripple data consistency** — both running and completed cards show the same Ripple fields (prediction + PMF score)
5. **Phase mapping for progress bar** — `pipelineProgress()` maps `briefing` → index 0 (scouting), `engaging` → index 4 (publishing)

### WorkflowReplay.vue — Node Status Fix

6. **Fix `getNodeStatus()`** — handle phases outside the 6-step pipeline:
   - `briefing`: treat as scouting index for progress
   - `engaging`: treat as publishing index for progress
   - `paused`/`cancelled`: use the stored phase to determine completed nodes
   - `error`: mark current phase as error, prior phases as completed
7. **Add `briefing` agent label** — `agentLabels` and `phaseAgentMap` should map briefing phase

## Acceptance Criteria

- [ ] Running and completed cards show identical data sections when the underlying data exists
- [ ] `otherWorkflows` (error/paused/cancelled/stale/awaiting_*) cards show full card layout with phase, status, error, and data preview
- [ ] Pipeline progress bar correctly handles `briefing` and `engaging` phases
- [ ] WorkflowReplay `getNodeStatus()` returns correct status for `briefing`, `engaging`, `paused`, `cancelled`, `error`
- [ ] No visual regression on existing working cards
- [ ] No TypeScript errors

## Definition of Done

- Visual verification on running, completed, error, and paused workflows
- No TypeScript errors
- Both en and zh-CN locales render correctly

## Out of Scope

- Backend data model changes
- New API endpoints
- Real-time WebSocket updates on Showcase page
- Dashboard or Review page changes
- `blogger_candidates` / `selected_blogger` display (separate feature)
- `draft_content` / `optimization_analysis` / `content_versions` display (separate feature)

## Technical Approach

### Showcase.vue card refactor

1. Extract a reusable `renderCardBody(detail)` section (via a `<template>` slot or inline conditional block) shared by all 3 card types
2. Add analytics, publish_result, competitor_posts rendering to this shared block
3. Convert `otherWorkflows` from compact to full card layout using the same block
4. Update `pipelineProgress()` to map `briefing` → 1, `engaging` → 5

### WorkflowReplay.vue status fix

1. Create a `phaseToIndex()` helper that maps any WorkflowPhase to pipeline index:
   - `briefing` → 0 (same as scouting)
   - `engaging` → 4 (same as publishing)
   - standard 6 phases → their natural index
   - `completed` → 6, `error`/`paused`/`cancelled` → use stored phase index
2. Rewrite `getNodeStatus()` using `phaseToIndex()`

## Technical Notes

- Key files: `frontend/src/views/Showcase.vue`, `frontend/src/views/WorkflowReplay.vue`
- Data types: `WorkflowStateResponse` in `frontend/src/types/workflow.ts`
- Phase enum: `WorkflowPhase` in `backend/state/enums.py` and `frontend/src/types/workflow.ts`
- Dashboard ContentCards.vue already renders analytics, publish_result etc. — use as reference for card layout
