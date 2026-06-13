# Fix: Ripple Progress Stuck at 0% — SSE Fallback Bypassed

## Goal

Fix the bug where Ripple simulation progress stays at 0% for the entire run (350+ seconds), even though jobs are running. The root cause is that a single SSE `progress=0` event sets `last_update=True`, permanently bypassing the time-based fallback estimation. Additionally, `refreshAllTabs()` does not merge `ripple_progress` for non-active tabs, and the Dashboard does not re-subscribe WebSocket on mount for all open tabs.

## Requirements

### P1 — Backend: SSE stale-detection with time-based fallback recovery

- `progress_state["last_update"]` must be replaced with `progress_state["last_update_at"]` recording the `time.monotonic()` timestamp of the most recent SSE progress event.
- In `wait_for_completion`, the progress emission logic must check: if `last_update_at` exists AND more than `SSE_STALE_THRESHOLD` seconds (default 15s) have passed since the last SSE update, revert to time-based estimation.
- If SSE provides `progress > 0` (meaningful data), always use it regardless of staleness.
- If SSE provided only `progress=0` and it's stale, use time-based fallback.
- This ensures: one `progress=0` from SSE does NOT permanently lock out fallback.

### P2 — Frontend: refreshAllTabs must merge ripple_progress for all tabs

- `refreshAllTabs()` currently only syncs `ripple_progress` for the active tab (via `refreshStatus`).
- Add ripple_progress merge logic inside the `refreshAllTabs` loop for every tab, mirroring the logic in `refreshStatus`.

### P3 — Frontend: Dashboard mount re-subscribes WebSocket for all open tabs

- On `onMounted`, after `refreshAllTabs()`, call `realtimeStore.subscribeWorkflow(id)` for each open tab ID, so WebSocket progress events flow for all tabs, not just the active one.

## Acceptance Criteria

- [ ] When Ripple SSE sends only `progress=0` and no further events for 15+ seconds, `wait_for_completion` falls back to time-based estimation
- [ ] When SSE sends `progress > 0` (meaningful), the real SSE value is always used
- [ ] When SSE is fresh (updated within 15s), SSE data is used
- [ ] `refreshAllTabs()` merges `ripple_progress` for all tabs, not just active
- [ ] Dashboard re-subscribes WebSocket for all open tabs on mount
- [ ] Existing tests pass; new unit test for stale-detection fallback

## Definition of Done

- Backend: `ruff check` + `mypy` pass
- Frontend: `vue-tsc` + `eslint` pass
- Unit test for `_stream_progress` stale detection / fallback recovery
- Manual verification: run workflow with Ripple, confirm progress bar moves during simulation

## Out of Scope

- Changing Ripple service itself to emit more frequent events (server-side change, separate task)
- Changing `phase` / `current_agent` accuracy during Ripple runs (LangGraph snapshot limitation, separate concern)
- Adding `ripple_progress` to SSE/polling for history views

## Technical Approach

### Backend (`backend/services/ripple_service.py`)

1. Replace `progress_state["last_update"]` (bool) with `progress_state["last_update_at"]` (float, monotonic timestamp)
2. In `_stream_progress`, on each progress event, set `progress_state["last_update_at"] = time.monotonic()`
3. In `wait_for_completion` progress emission block:
   - Compute `sse_age = elapsed_since_last_update_at`
   - If `last_update_at` exists AND sse_age < SSE_STALE_THRESHOLD (15s) AND `progress > 0`: use SSE data
   - Else: use time-based fallback `min(0.95, elapsed / max_wait)`
4. Add constant `SSE_STALE_THRESHOLD = 15.0` at module level

### Frontend (`frontend/src/stores/workflow.ts`)

1. In `refreshAllTabs()`, after fetching state for each tab, merge `ripple_progress` into `rippleProgressMap` (same logic as `refreshStatus`)
2. In `Dashboard.vue` `onMounted`, after `refreshAllTabs()`, subscribe WebSocket for each open tab

### Files to modify

- `backend/services/ripple_service.py` — stale detection + fallback recovery
- `frontend/src/stores/workflow.ts` — refreshAllTabs ripple merge
- `frontend/src/views/Dashboard.vue` — mount WebSocket re-subscription

## Decision (ADR-lite)

**Context**: Ripple SSE may connect successfully (HTTP 200) but not send progress events for the entire run. A single `progress=0` event permanently blocks the time-based fallback.

**Decision**: Use timestamp-based staleness check (`last_update_at`) with a 15-second threshold. If SSE data is stale, revert to time-based estimation. This gives users visible progress (time-based) while still preferring real SSE data when available.

**Consequences**: Users will see progress move even when Ripple SSE is silent. The 15s threshold means at most 15s of "stale" display after SSE stops — acceptable for simulations running 400+ seconds. No server-side changes needed.
