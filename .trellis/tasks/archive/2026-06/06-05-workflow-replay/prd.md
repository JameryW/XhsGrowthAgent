# Workflow Replay

## Goal

Support workflow replay capability — allow users to click into a completed (or in-progress) workflow step and view the exact execution results at that point in time.

## What I already know

* LangGraph `CompiledStateGraph` exposes `aget_state_history(config, *, filter=None, before=None, limit=None)` which returns `AsyncIterator[StateSnapshot]`
* Each `StateSnapshot` has: `values` (state dict), `next` (upcoming nodes), `config`, `metadata` (CheckpointMetadata: source/step/writes), `created_at` (timestamp), `parent_config`, `tasks`, `interrupts`
* Current `GET /status/{thread_id}` only returns the latest state snapshot via `aget_state()`
* History page (`History.vue`) shows a flat list of workflows; "View" navigates to dashboard with only the latest state
* Completed workflows are saved to `.xhs/history/{thread_id}.json` as a single final-state dump
* Backend uses `MemorySaver` (dev) or `AsyncPostgresSaver` (prod) checkpointer — both support `aget_state_history()`
* `performance_log` in state tracks agent execution timeline (agent name, started_at, completed_at, duration, status)
* `WorkflowStatusResponse` includes `agent_timeline` built from `performance_log`
* Frontend types already have `AgentTimelineEntry` with started_at/completed_at/duration_seconds/status
* Dashboard has `WorkflowTimeline.vue` showing phase progression with `WorkflowNode` components — currently only shows live state, not historical
* `ContentCards.vue` shows trend_data/content_plan/copy_content/visual_plan based on current phase
* Dashboard already has a tab system (`WorkflowTabBar`) for multi-workflow switching

## Decision (ADR-lite)

**Context**: Need to choose UX pattern for workflow replay — users click a step to view its execution results.
**Decision**: Hybrid approach — timeline stepper in Dashboard + History page "Replay" button that navigates to Dashboard in replay mode.
**Consequences**: Reuses existing Dashboard layout (ContentCards etc.), avoids a separate route/page. History "Replay" button loads the workflow and auto-enters replay mode. One code path to maintain.

**Context**: Visual indicator for historical state viewing.
**Decision**: Top banner + timeline node highlight (both).
**Consequences**: Clear visual distinction at both the content area (banner) and navigation area (timeline highlight).

**Context**: Running workflow in replay mode.
**Decision**: Pause live WS updates while in replay mode, resume on exit.
**Consequences**: Prevents confusing state jumps between historical and live data.

**Context**: Long workflows with many checkpoints.
**Decision**: Backend `limit` param + frontend lazy-load.
**Consequences**: Avoids large payloads; initial load is fast.

## Requirements

* Backend: new endpoint `GET /workflow/history/{thread_id}` to fetch checkpoint snapshots
* Backend: return structured per-step state snapshots (phase, agent, data produced, timestamp, checkpoint_id)
* Backend: `limit` query param for pagination; `before` param for cursor-based loading
* Frontend: Dashboard gains "Replay mode" toggle — timeline nodes become clickable, clicking one shows state at that checkpoint
* Frontend: History page gets "Replay" button that navigates to Dashboard and auto-enters replay mode for that thread
* Frontend: ContentCards renders historical state data when in replay mode
* Frontend: Replay mode shows top banner ("正在查看历史状态") + selected timeline node highlight
* Frontend: Entering replay mode on running workflow pauses live WS updates; exiting resumes
* Graceful fallback when checkpoints unavailable (MemorySaver restart → use history JSON)

## Acceptance Criteria

* [ ] `GET /workflow/history/{thread_id}` returns ordered list of checkpoint snapshots
* [ ] Each snapshot includes: checkpoint_id, step, source node, phase, timestamp, state values (trend_data, content_plan, etc.)
* [ ] Backend `limit` param works; returns `has_more` flag for pagination
* [ ] Dashboard timeline nodes are clickable in replay mode
* [ ] Clicking a node updates ContentCards to show that checkpoint's state
* [ ] History page "Replay" button navigates to Dashboard in replay mode
* [ ] Visual indicator shows when viewing historical (non-live) state: top banner + timeline node highlight
* [ ] Graceful fallback when checkpoints unavailable (shows "no checkpoint data" message)
* [ ] Running workflow: entering replay mode pauses live updates; exiting resumes them
* [ ] Frontend lazy-loads older checkpoints on scroll/demand

## Definition of Done

* Tests added/updated (unit/integration where appropriate)
* Lint / typecheck / CI green
* Docs/notes updated if behavior changes

## Out of Scope (explicit)

* Re-executing workflow steps (this is view-only replay)
* Diffing between checkpoints (future enhancement)
* Modifying past checkpoint state
* Sharing replay links with team members
* Replay for sub-graph checkpoints (only top-level workflow)

## Technical Approach

### Backend

1. **New endpoint**: `GET /workflow/history/{thread_id}?limit=20&before=<checkpoint_id>`
   - Calls `graph.aget_state_history(config, limit=limit, before=before_config)`
   - Iterates snapshots, extracts per-checkpoint summary
   - Returns `CheckpointSnapshot[]` + `has_more` flag

2. **Response model** (`CheckpointSnapshot`):
   ```python
   class CheckpointSnapshot(BaseModel):
       checkpoint_id: str          # from snapshot.config["configurable"]["checkpoint_id"]
       step: int                   # from snapshot.metadata["step"]
       source: str                 # from snapshot.metadata["source"] (which node wrote)
       phase: str                  # from snapshot.values["phase"]
       current_agent: str          # from snapshot.values["current_agent"]
       created_at: str             # from snapshot.created_at
       next_nodes: list[str]       # from snapshot.next
       # Stage data (only include non-empty)
       trend_data: dict = {}
       content_plan: dict = {}
       copy_content: dict = {}
       visual_plan: dict = {}
       publish_result: dict = {}
       analytics: dict = {}
       ripple_prediction: dict = {}
       ripple_pmf: dict = {}
   ```

3. **Fallback**: If `aget_state_history` yields nothing (MemorySaver lost), try `_load_history_file(thread_id)` and return a single-entry list with the final state.

### Frontend

1. **New types**: `CheckpointSnapshot`, `CheckpointHistoryResponse` in `workflow.ts`
2. **New API call**: `getCheckpointHistory(threadId, { limit, before })` in `api/workflow.ts`
3. **Workflow store additions**:
   - `isReplayMode: ref(false)`
   - `replayCheckpoints: ref<CheckpointSnapshot[]>([])`
   - `activeCheckpointId: ref<string | null>(null)`
   - `replayState: computed` — returns the selected checkpoint's state or live state
   - `enterReplayMode()` / `exitReplayMode()` — toggle, pause/resume WS
   - `selectCheckpoint(id)` — set active checkpoint, update ContentCards
   - `loadMoreCheckpoints()` — lazy-load with `before` cursor
4. **WorkflowTimeline.vue changes**:
   - In replay mode, nodes become clickable
   - Selected node gets highlight style (ring/glow)
   - Click emits `select-checkpoint` event
5. **Dashboard.vue changes**:
   - Replay banner component (top, dismissible)
   - Pass `replayState` to ContentCards instead of live state
   - Replay mode toggle button in WorkflowHeader
6. **History.vue changes**:
   - Add "Replay" button alongside existing "View" button
   - On click: `setThreadId` → navigate to `/dashboard?replay=true`

## Technical Notes

* Key files: `backend/api/routes/workflow.py`, `frontend/src/views/History.vue`, `frontend/src/stores/workflow.ts`, `frontend/src/types/workflow.ts`, `frontend/src/components/dashboard/WorkflowTimeline.vue`, `frontend/src/components/dashboard/ContentCards.vue`, `frontend/src/views/Dashboard.vue`
* LangGraph API: `graph.aget_state_history(config, limit=N, before=config)` returns async iterator of `StateSnapshot`
* Each `StateSnapshot` has: `.values`, `.next`, `.metadata` (source, step, writes), `.config` (contains checkpoint_id), `.created_at`
* Dev mode (MemorySaver) checkpoints lost on restart — fallback to `.xhs/history/{thread_id}.json`
* `before` param in `aget_state_history` takes a `RunnableConfig` with checkpoint_id for cursor-based pagination
