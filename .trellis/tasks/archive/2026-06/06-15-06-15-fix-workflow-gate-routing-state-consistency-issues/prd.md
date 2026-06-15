# PRD: Fix Workflow Gate, Routing, State Consistency Issues

## Problem Statement

7 bugs in the workflow execution chain cause gate misbehavior, routing loops, premature termination, and state inconsistencies.

## Issues & Fixes

### Issue 1: ripple_gate unconditional interrupt_before (HIGH)

**Root cause:** `builder.py:361` puts `ripple_gate` in `interrupt_before`, so LangGraph pauses before the node body runs. The node body at `ripple_gate.py:54` has logic to auto-accept when results are good, but it never executes.

**Fix:** Remove `ripple_gate` from `interrupt_before` in both `compile_graph_dev()` and `compile_graph_prod()`. The node already uses dynamic `interrupt()` (line 89) when results are suboptimal.

### Issue 2: blogger_gate unconditional interrupt_before + skip loop (HIGH)

**Root cause:** Same as Issue 1 — `blogger_gate` in `interrupt_before` prevents the "no candidates → skip" path (line 38-45) from executing. Additionally, when the user skips blogger selection, `blogger_gate_router` sends trend mode to `draft_gate`, but `draft_gate_router` at line 230 sends it back to `viral_matcher` → `blogger_scout` → `blogger_gate`, creating a loop.

**Fix:**
1. Remove `blogger_gate` from `interrupt_before`. The node already uses dynamic `interrupt()` (line 48).
2. When blogger is skipped (no candidates or user skip), set `blogger_skipped=True` in state.
3. Update `draft_gate_router` to check `blogger_skipped` and route to `shooting_planner` instead of `viral_matcher`.

### Issue 3: trend_data field contract drift (HIGH)

**Root cause:** `should_plan` at `routers.py:70` only checks `trend_data.hot_topics`, but `TrendScoutAgent.execute()` at `trend_scout.py:152` reads `trending_topics` or `topics`. LLM output may use any of these field names.

**Fix:** In `should_plan`, normalize: check `hot_topics`, `trending_topics`, or `topics` — any non-empty list means we have trends. Also update `trend_scout.py:152` to write `hot_topics` as the canonical field.

### Issue 4: phase/progress inconsistency (HIGH)

**Root cause A:** `_run_graph_and_persist` at `_runner.py:221` sets `progress=100` only when `final_status == "completed"`, otherwise `progress=0`. So workflows awaiting review/choice get progress reset to 0.

**Root cause B:** `get_workflow_status` at `workflow.py:444` uses `get_progress(phase)` which is phase-based, but the DB gets `0` from the runner for non-completed states. Also, `PHASE_PROGRESS` doesn't include `briefing` phase.

**Root cause C:** END-branching routers don't set `phase=completed`.

**Fix:**
1. In `_run_graph_and_persist`, compute progress from `PHASE_PROGRESS` based on phase, not binary 0/100.
2. Add `briefing` to `PHASE_PROGRESS` dict.
3. In `get_workflow_status`, use derived status to override: if `completed`, always 100; if `awaiting_*`, use the phase-based progress.
4. For END-branching routers that don't set `phase=completed`, the `derive_status` priority 10 already handles "no next nodes → completed". The real fix is ensuring the runner doesn't reset progress to 0 for awaiting states.

### Issue 5: review/ripple decision swallows exceptions (MEDIUM)

**Root cause:** `review.py:123` and `review.py:235` catch all exceptions from `_run_graph_and_persist` and return `status: "resumed"`, `next_phase: "unknown"`. The caller (frontend) thinks the resume succeeded but the DB may already be `error`.

**Fix:** Don't swallow the exception. Let it propagate to the global error handler. The `_run_graph_and_persist` already sets `phase=error` in the graph state and DB on exception, so the caller should get an error response, not a fake success.

### Issue 6: brief mode start returns wrong phase + stale status (MEDIUM)

**Root cause A:** `start_workflow` at `workflow.py:407` returns `req.phase.value` (the original request phase) instead of the actual `BRIEFING` phase for async starts.

**Root cause B:** When `brief_waiting_for_upload=True`, the function writes initial state via `aupdate_state` but returns `status: "running"`. There's no active task, so the next `status` call will see `next_nodes` with no active task → `stale`.

**Fix:**
1. For async start, return `initial_state["phase"]` (which is already set to BRIEFING) instead of `req.phase.value`.
2. For `brief_waiting_for_upload`, return `status: "awaiting_brief"` instead of `"running"`.

### Issue 7: CLI resume doesn't pass Command (MEDIUM)

**Root cause:** `cli/main.py:274` calls `graph.ainvoke(None, config)`. When the graph is paused at an interrupt (e.g., `review_gate`), the node's `interrupt(None)` returns `None`, which means no decision → defaults to rejected.

**Fix:** Before invoking, check if the workflow is at an interrupt. If so, prompt the user for a decision or warn them. At minimum, pass a sensible default `Command(resume=...)` value instead of `None` for known gate types.

## Files Modified

1. `backend/graph/builder.py` — Remove `ripple_gate` and `blogger_gate` from `interrupt_before`
2. `backend/agents/nodes/ripple_gate.py` — Already uses dynamic interrupt(), no change needed
3. `backend/agents/nodes/blogger_gate.py` — Set `blogger_skipped=True` when skipping
4. `backend/graph/routers.py` — Fix `should_plan` field aliasing; fix `draft_gate_router` for `blogger_skipped`
5. `backend/agents/trend_scout.py` — Write `hot_topics` as canonical field
6. `backend/api/routes/_runner.py` — Fix progress calculation
7. `backend/api/routes/workflow.py` — Fix async start phase; fix brief waiting status; add `briefing` to PHASE_PROGRESS
8. `backend/api/routes/review.py` — Don't swallow exceptions
9. `backend/state/schema.py` — Add `blogger_skipped` field (if not existing)
10. `backend/cli/main.py` — Handle gate interrupts properly in resume

## Testing

- Unit tests for `should_plan` with all field aliases
- Unit tests for `draft_gate_router` with `blogger_skipped`
- Unit tests for `derive_status` with dynamic interrupt gates
- Integration test: brief mode start → awaiting_brief status
- Integration test: ripple_gate auto-accept path (no interrupt)
- Integration test: blogger_gate skip → shooting_planner (no loop)
