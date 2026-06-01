# Workflow Bug Audit — Remaining Gaps Fix Design

**Date:** 2026-06-01
**Status:** Draft
**Scope:** Fix 6 remaining gaps found during audit of 9 previously-identified workflow bugs

## Context

Prior commits fixed most of the 9 workflow bugs, but an audit revealed 6 remaining gaps at varying priority levels. This spec covers all 6.

## Gap 1 (P0): `derive_status` interrupt detection is broken

**File:** `backend/state/machine.py:49-50`

**Problem:** The code checks `task.get("interrupts")` with `isinstance(task, dict)`, but `PregelTask` is a dataclass with `.interrupts` as an attribute. The dict check never matches, so interrupts are never detected. `derive_status` always falls through to the phase-based logic and returns `running` or `completed` instead of `awaiting_review`/`awaiting_choice`.

**Fix:** Use `snapshot.interrupts` (top-level list field on `StateSnapshot`) instead of iterating `snapshot.tasks`:

```python
# Before (broken):
for task in snapshot.tasks:
    if isinstance(task, dict) and task.get("interrupts"):
        ...

# After (correct):
has_interrupt = bool(snapshot.interrupts)
if has_interrupt:
    # Determine which gate: inspect the interrupt value
    interrupt_value = snapshot.interrupts[0].value if snapshot.interrupts else None
    if isinstance(interrupt_value, dict):
        gate_type = interrupt_value.get("gate", "review")
    else:
        gate_type = "review"
    return WorkflowStatus.AWAITING_REVIEW if gate_type == "review" else WorkflowStatus.AWAITING_CHOICE
```

Also simplify the existing phase-based logic to remove the dead interrupt-detection code.

## Gap 2 (P0): Sync path, `/status`, and `/list` bypass `derive_status`

**Files:** `backend/api/routes/workflow.py:291,330-350,634-648`

**Problem:** Three code paths bypass `derive_status`:
- Sync invoke (line 291): hardcodes `"completed"` for anything without error
- `/status` endpoint (line 330-350): reads phase from state values, maps to status naively, misses `awaiting_review`/`awaiting_choice`
- `/list` endpoint (line 634-648): maps history phase to status directly

**Fix:**

### Sync path (workflow.py:291)
After `graph.invoke()`, call `graph.get_state(config)` (sync version) and use `derive_status(snapshot)`:
```python
snapshot = graph.get_state(config)
final_status = derive_status(snapshot)
```

### `/status` endpoint (workflow.py:330-350)
Replace the phase-to-status mapping with `derive_status`:
```python
snapshot = await graph.aget_state(config)
status = derive_status(snapshot)
```

### `/list` endpoint (workflow.py:634-648)
For live entries (thread still in checkpointer), derive from snapshot. For history-only entries, accept best-effort mapping from phase.

## Gap 3 (P1): Double event emission on interrupt resume

**Files:** `backend/agents/nodes/review_gate.py:23`, `backend/agents/nodes/optimization/choice_gate.py:23`

**Problem:** When `Command(resume=...)` resumes an interrupted node, LangGraph re-executes the node from the start. Both nodes emit events before calling `interrupt()`, so events fire again on resume, causing duplicate notifications.

**Root cause:** LangGraph's `interrupt()` raises `GraphInterrupt` on first call (stopping the node). On resume, the node re-runs from the top, `interrupt()` returns the resume value immediately, and execution continues past it. Code before `interrupt()` runs both times.

**Fix:** Move event emission out of the interrupt nodes. Instead, emit events from the workflow API layer when `derive_status` detects a status transition to `awaiting_review` or `awaiting_choice`.

### Implementation

1. Remove `EventBusService.emit()` calls from `review_gate_node` and `choice_gate_node`
2. Add a helper `_emit_status_transition(old_status, new_status, thread_id)` in `workflow.py`
3. Call it after `derive_status` in the async start path and SSE status updates
4. Event types map:
   - `awaiting_review` → emit `REVIEW_PENDING`
   - `awaiting_choice` → emit `WORKFLOW_DATA_UPDATED` with optimization data
5. The helper checks `old_status != new_status` to avoid duplicate emissions

### Node restructuring

```python
# review_gate_node — simplified, no event emission
async def review_gate_node(state, *, store):
    _check_cancelled(state)
    review_payload = {"gate": "review", "content": state.get("copy_content", {})}
    decision = interrupt(review_payload)
    # Only reaches here on resume — process the decision
    result = {"human_feedback": decision, "phase": WorkflowPhase.REVIEWING}
    return NodeResult(result, "review_gate").to_dict()

# choice_gate_node — simplified, no event emission
async def choice_gate_node(state, *, store):
    _check_cancelled(state)
    choice_payload = {"gate": "choice", "versions": ...}
    decision = interrupt(choice_payload)
    # Only reaches here on resume — process the selection
    ...
```

## Gap 4 (P1): `compile_graph_prod` connection lifecycle bug

**File:** `backend/graph/builder.py:167`

**Problem:** Uses `async with AsyncPostgresSaver.from_conn_string(db_uri) as checkpointer`, which closes the connection pool when the `async with` block exits. The graph is returned but the checkpointer's connections are dead.

**Fix:** Create the checkpointer without `async with`, manage its lifecycle in the app:

```python
# builder.py
async def compile_graph_prod(db_uri: str) -> tuple[CompiledStateGraph, AsyncPostgresSaver]:
    checkpointer = AsyncPostgresSaver.from_conn_string(db_uri)
    await checkpointer.setup()
    graph = _build_graph().compile(checkpointer=checkpointer)
    return graph, checkpointer
```

```python
# app.py lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    db_uri = os.environ.get("POSTGRES_URI")
    if db_uri:
        graph, checkpointer = await compile_graph_prod(db_uri)
        app.state.checkpointer = checkpointer
    else:
        graph = compile_graph_dev()
    app.state.graph = graph
    yield
    # Cleanup
    if hasattr(app.state, "checkpointer") and app.state.checkpointer:
        await app.state.checkpointer.__aexit__(None, None, None)
```

## Gap 5 (P2): Pause doesn't cancel background task

**File:** `backend/api/routes/workflow.py:436`

**Problem:** `pause_workflow` only sets `phase="paused"` in state. The background asyncio task continues running until it hits `_check_cancelled` at the next node boundary. A mid-execution LLM call won't be interrupted.

**Fix:** Cancel the background task on pause, same pattern as cancel:

```python
bg_task = _background_tasks.get(thread_id)
if bg_task and not bg_task.done():
    bg_task.cancel()
```

On resume, `resume_workflow` already re-invokes the graph from the checkpoint, so the paused state is correctly restored.

## Gap 6 (P2): `choice_gate_node` missing `selected_title` on fallback

**File:** `backend/agents/nodes/optimization/choice_gate.py:94-99`

**Problem:** When `selected_version` is not found, only `phase=CREATING` is returned with no `copy_content` update. The publisher receives stale/empty data.

**Fix:** Write the original draft as fallback:

```python
else:
    logger.warning(f"Selected version not found: {selected_version_id}")
    result = {
        "phase": WorkflowPhase.CREATING,
        "copy_content": {
            **(state.get("copy_content") or {}),
            "selected_title": draft.get("title", ""),
        },
    }
```

## Testing

Each gap should have at least one test:

1. **Gap 1:** Unit test for `derive_status` with a mock `StateSnapshot` containing interrupts — verify it returns `awaiting_review`/`awaiting_choice`
2. **Gap 2:** Integration test for `/status` endpoint — start workflow, interrupt at review_gate, verify response shows `awaiting_review`
3. **Gap 3:** Test that `review_gate_node` and `choice_gate_node` do NOT emit events directly, and that event emission happens at the API layer
4. **Gap 4:** Test that `compile_graph_prod` returns a working graph with an open checkpointer
5. **Gap 5:** Test that `pause_workflow` cancels the background task
6. **Gap 6:** Test `choice_gate_node` with a non-existent version ID — verify `copy_content` has `selected_title`

## Scope

This is a correctness fix — no new features, no refactoring beyond what's needed to fix the bugs. All changes are localized to the files mentioned above.
