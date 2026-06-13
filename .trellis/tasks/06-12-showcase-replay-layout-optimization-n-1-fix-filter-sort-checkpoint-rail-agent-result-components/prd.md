# Showcase & Replay Layout Optimization

## Problem
1. Showcase.vue N+1: loads all workflow details before rendering, blocking first paint
2. Marketing-first layout buries real workflow content below heavy animation
3. No filter/sort/search on workflow list
4. Detail page lacks checkpoint rail — can't browse all checkpoints
5. WorkflowReplay.vue monolith: all agent results in one huge template

## Implementation Order

### Phase 1: Showcase data + layout
- Remove global wait for all details; render cards immediately with basic info
- Lazy-load detail for visible cards (first 6-8, then on scroll)
- Add filter bar: All / Running / Completed / Needs Attention + mode filter + sort
- Restructure: stats header → compact process strip → card grid → load more
- Card shows most valuable content first (title > topic > brand > publish > analytics)

### Phase 2: Detail page shell
- 12-column grid: header(full) → timeline(full) → rail(3col) | detail(6col) | summary(3col)
- Sticky checkpoint rail: agent label, phase, time, data badge
- Connect to existing replayCheckpoints/activeCheckpointId/loadMoreCheckpoints
- Right sidebar: final title, body summary, tags, publish link, core metrics

### Phase 3: Agent result components
- Extract from WorkflowReplay.vue into:
  AgentResultTrend, AgentResultPlan, AgentResultCreative,
  AgentResultShooting, AgentResultVisual, AgentResultPublish,
  AgentResultRipple, AgentResultAnalytics
- Shared composable: useWorkflowReplay.ts (phaseToIndex, getNodeStatus, hasDataForAgent)

### Phase 4: Responsive + polish
- Mobile: single column, horizontal step chips, bottom drawer for rail
- Desktop: sticky rail
- Reduce decorative background/animation weight

## Acceptance
- / renders without waiting for all detail requests
- Desktop first screen shows stats + process strip + ≥2 real workflow cards
- /replay/:threadId can browse all checkpoints with load more
- Detail page shows phase/agent/step/key output without scrolling to top
- `npm -C frontend run build` and `npm -C frontend run type-check` pass
- Desktop + mobile viewport layout verified
