# Workflow Bug Fix Design — 9 Critical Issues

**Date:** 2026-05-31
**Approach:** Unified Status Derivation + Incremental Fixes
**Scope:** P0 (correctness) + P1 (stability) + P2 (flow semantics)

## Overview

Nine bugs in the XHS Growth Agent workflow system cause incorrect status reporting,
broken human-in-the-loop, SSE re-execution, unclosed optimization loops, swallowed
errors, duplicate version history, unreliable persistence, non-functional pause/cancel,
and no clear completion path. This design fixes all nine with a unified state machine,
dynamic interrupts, EventBus-driven SSE, new optimization API endpoints, proper error
propagation, and a two-mode execution topology.

---

## 1. Unified State Machine + Status Derivation

**Bug:** `graph.ainvoke()` return is misclassified — interrupts treated as completions.
Registry shows `phase=reviewing, status=completed`.

**Fix:** Create `backend/state/machine.py` with a single `derive_status()` function.

```python
class WorkflowStatus(StrEnum):
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    AWAITING_CHOICE = "awaiting_choice"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"

def derive_status(snapshot: GraphStateSnapshot) -> WorkflowStatus:
    """Single source of truth. Priority:
    1. Cancelled (phase flag)
    2. Paused (phase flag)
    3. Interrupt at review_gate → awaiting_review
    4. Interrupt at choice_gate → awaiting_choice
    5. Error in state → error
    6. Phase is completed → completed
    7. Has next nodes → running
    8. No next nodes + no interrupt → completed
    """
```

All API endpoints and registry updates call `derive_status()` instead of ad-hoc logic.
The `_run_and_persist` function in `workflow.py` uses `derive_status()` to classify
`ainvoke` results. The `get_workflow_status` endpoint uses it to compute status from
live graph state.

**Files changed:**
- `backend/state/machine.py` (new)
- `backend/state/__init__.py` (export `WorkflowStatus`, `derive_status`)
- `backend/api/routes/workflow.py` (replace all ad-hoc status logic)

---

## 2. HITL Mechanism — Dynamic `interrupt()` Only

**Bug:** `interrupt_before=["review_gate", "choice_gate"]` prevents nodes from
executing, so `REVIEW_PENDING`/`CHOICE_PENDING` events never fire. Nodes also call
`interrupt()` internally, creating a conflict.

**Fix:** Remove `interrupt_before` from graph compilation. Nodes handle their own
interrupts via `interrupt()`.

```python
# builder.py — no interrupt_before
graph = builder.compile(checkpointer=checkpointer, store=store)

# review_gate_node — event fires, then interrupt pauses
EventBusService.emit(EventType.REVIEW_PENDING, ...)
decision = interrupt(review_payload)
# resume continues from here
```

Resume uses `Command(resume=decision)` as already implemented in `review.py`.

**Files changed:**
- `backend/graph/builder.py` (remove `interrupt_before` from both compile functions)
- `backend/agents/nodes/review_gate.py` (no change — already uses `interrupt()`)
- `backend/agents/nodes/optimization/choice_gate.py` (no change — already uses `interrupt()`)

---

## 3. SSE — EventBus-Driven, Not Graph-Driven

**Bug:** `/stream/{thread_id}` calls `graph.astream_events(None, config)` which
re-drives the graph. Multiple clients cause duplicate execution.

**Fix:** Replace with EventBus subscription. `EventBusService` gets
`subscribe(thread_id)` / `unsubscribe(thread_id, queue)` methods using `asyncio.Queue`.

```python
@router.get("/stream/{thread_id}")
async def stream_workflow_progress(thread_id, request):
    async def event_generator():
        bus = EventBusService.get_instance()
        queue = bus.subscribe(thread_id)
        try:
            while True:
                event = await queue.get()
                yield f"event: {event.type}\ndata: {json.dumps(event.payload)}\n\n"
                if event.type in (EventType.WORKFLOW_COMPLETED, EventType.WORKFLOW_ERROR):
                    break
        finally:
            bus.unsubscribe(thread_id, queue)
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

Nodes emit `WORKFLOW_COMPLETED` and `WORKFLOW_ERROR` events at terminal states.

**Files changed:**
- `backend/realtime/eventbus.py` (add subscribe/unsubscribe with asyncio.Queue)
- `backend/api/routes/workflow.py` (rewrite `/stream` endpoint)
- `backend/agents/nodes/review_gate.py` (emit terminal events)
- `backend/agents/analyst.py` (emit WORKFLOW_COMPLETED)

---

## 4. Optimization Frontend-Backend Closure + choice_gate Fix

**Bug 1:** Frontend `submitDraft`/`selectVersion` only update local state — API
calls are commented out. If graph stops at `choice_gate`, user selection doesn't
resume it.

**Bug 2:** `choice_gate` writes `copy_content` without `selected_title`, publisher
gets empty title.

**Fix A — New API endpoints in `backend/api/routes/optimization.py`:**

```python
@router.post("/draft/{thread_id}")
async def submit_draft(thread_id, draft: DraftSubmission, request):
    """Submit user's draft content — updates state."""
    await graph.aupdate_state(config, {
        "draft_content": draft.model_dump(),
        "user_viral_links": draft.viral_links,
    })
    return success(data={"status": "draft_submitted"})

@router.post("/select/{thread_id}")
async def select_version(thread_id, choice: VersionChoice, request):
    """Select A/B/C version — resumes graph from choice_gate interrupt."""
    state = await graph.aget_state(config)
    if "choice_gate" not in state.next:
        raise ChoiceNotPendingError(thread_id)
    result = await graph.ainvoke(Command(resume=choice.model_dump()), config)
    return success(data={"status": "resumed", "next_phase": result.get("phase")})
```

**Fix B — Add `selected_title` to choice_gate output:**

```python
# choice_gate_node — when selected version found
result = {
    "copy_content": {
        "selected_title": selected_version.get("title", ""),  # NEW
        "title_candidates": [selected_version.get("title", "")],
        "body_text": selected_version.get("body", ""),
        ...
    },
}
```

**Fix C — Wire frontend to new APIs:**

```typescript
// optimization.ts — uncomment and implement API calls
async function submitDraft(draft, viralLinks) {
    await workflowApi.submitDraft({ thread_id: threadId, draft, viral_links: viralLinks })
    draftContent.value = draft
}
async function selectVersion(choice) {
    await workflowApi.selectVersion({ thread_id: threadId, choice })
    selectedVersion.value = choice.version_id
}
```

**Files changed:**
- `backend/api/routes/optimization.py` (new)
- `backend/api/app.py` (register optimization router)
- `backend/agents/nodes/optimization/choice_gate.py` (add `selected_title`)
- `frontend/src/stores/optimization.ts` (wire API calls)
- `frontend/src/api/workflow.ts` (add `submitDraft`, `selectVersion` methods)

---

## 5. Error Handling + Retry Policy Fix

**Bug 1:** `BaseAgent.__call__` catches exceptions, writes `error`/`retry_count`,
returns normally — graph follows fixed edges to next node.

**Bug 2:** `RETRY_POLICIES` defined but never wired to `add_node()`.

**Bug 3:** Successful nodes don't clear old `error`.

**Fix A — Wire retry policies to nodes:**

```python
# builder.py
from backend.graph.error_handling import get_retry_policy

builder.add_node("trend_scout", trend_scout_node, retry=get_retry_policy("trend_scout"))
builder.add_node("publisher", publisher_node, retry=get_retry_policy("publisher"))
# ... for all nodes with retry policies
```

**Fix B — Let exceptions propagate, clear stale errors:**

```python
# base.py
async def __call__(self, state, *, store):
    try:
        result = await self.execute(state, store)
        result["current_agent"] = self.agent_name
        result["error"] = None  # Clear stale error on success
        return result
    except Exception as e:
        logger.error(f"Agent {self.agent_name} failed: {e}", exc_info=True)
        raise AgentError(self.agent_name, e) from e  # Propagate to LangGraph retry
```

**Fix C — Router guards for cancelled/paused/error:**

```python
# routers.py — add guards to all routers
def _check_terminal(state) -> str | None:
    """Return '__end__' if workflow is in terminal state, else None."""
    if state.get("error"):
        return "__end__"
    if state.get("phase") in (WorkflowPhase.CANCELLED, WorkflowPhase.PAUSED):
        return "__end__"
    return None

def should_continue(state):
    if terminal := _check_terminal(state):
        return terminal
    # ... rest of routing logic
```

Apply `_check_terminal` guard to: `orchestrator_router`, `should_plan`,
`review_outcome`, `should_continue`, `should_optimize`.

**Fix D — `AgentError` exception class:**

```python
# backend/core/errors.py
class AgentError(Exception):
    def __init__(self, agent_name: str, cause: Exception):
        self.agent_name = agent_name
        self.cause = cause
        super().__init__(f"Agent {agent_name} failed: {cause}")
```

**Files changed:**
- `backend/graph/builder.py` (wire retry policies)
- `backend/agents/base.py` (propagate exceptions, clear stale errors)
- `backend/graph/routers.py` (add terminal state guards)
- `backend/core/errors.py` (add `AgentError`)

---

## 6. Version History Dedup

**Bug:** `content_versions` uses `append_list` reducer, but `review.py:97` passes
`existing_versions + [version_entry]`. Reducer produces `old + old + new`.

**Fix:** Pass only the new entry to `aupdate_state`, let the reducer append:

```python
# review.py — submit_review, needs_revision branch
await graph.aupdate_state(config, {
    "content_versions": [version_entry],  # reducer appends to existing
})
```

**Files changed:**
- `backend/api/routes/review.py` (line 97-99)

---

## 7. Persistence + Recovery

**Bug 1:** API always uses `compile_graph_dev()` — `compile_graph_prod()` never called.

**Bug 2:** Registry/history uses lockless JSON writes — race conditions.

**Bug 3:** Process restart loses LangGraph interrupt state (memory checkpointer).

**Fix A — Environment-based graph compilation:**

```python
# app.py
@asynccontextmanager
async def lifespan(app):
    db_uri = os.environ.get("POSTGRES_URI")
    if db_uri:
        app.state.graph = await compile_graph_prod(db_uri)
    else:
        app.state.graph = compile_graph_dev()
    yield
```

**Fix B — Atomic JSON writes with file lock:**

```python
import fcntl

def _save_registry():
    _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _REGISTRY_PATH.with_suffix(".tmp")
    with open(tmp_path, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        json.dump(_workflow_registry, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, _REGISTRY_PATH)  # atomic rename
```

**Fix C — Recovery:** With Postgres checkpointer, interrupt state survives restarts.
For memory checkpointer (dev), document that restart loses interrupt state.

**Files changed:**
- `backend/api/app.py` (env-based graph compilation)
- `backend/api/routes/workflow.py` (atomic JSON writes)

---

## 8. Pause/Cancel — Stop Background Tasks

**Bug:** `pause`/`cancel` only update state flags. Running `asyncio.Task` continues.
No cancellation token, no router guard.

**Fix A — Background task registry:**

```python
_background_tasks: dict[str, asyncio.Task] = {}

async def _run_and_persist(thread_id, graph, config):
    try:
        result = await graph.ainvoke(initial_state, config)
        status = derive_status(await graph.aget_state(config))
        # ... update registry
    except asyncio.CancelledError:
        _workflow_registry[thread_id]["status"] = "cancelled"
        _save_registry()
    finally:
        _background_tasks.pop(thread_id, None)

# In start_workflow:
task = asyncio.create_task(_run_and_persist(...))
_background_tasks[thread_id] = task
```

**Fix B — Cancel endpoint cancels the task:**

```python
@router.post("/cancel/{thread_id}")
async def cancel_workflow(thread_id, request):
    # ... existing state update ...
    task = _background_tasks.get(thread_id)
    if task and not task.done():
        task.cancel()
    return success(data={"status": "cancelled"})
```

**Fix C — Node entry guard:**

```python
def _check_cancelled(state):
    if state.get("phase") in (WorkflowPhase.CANCELLED, WorkflowPhase.PAUSED):
        raise WorkflowCancelledError()
```

Called at the top of each node function. Combined with router guards (Section 5),
this ensures cancelled workflows don't continue executing.

**Files changed:**
- `backend/api/routes/workflow.py` (background task registry, cancel task)
- `backend/agents/nodes/_base.py` (add `_check_cancelled` helper)
- `backend/agents/nodes/orchestrator.py`, `trend_scout.py`, `content_strategist.py`,
  `copywriter.py`, `visual_designer.py`, `review_gate.py`, `publisher.py`,
  `analyst.py`, `engagement.py`, `revise_content.py`, `viral_matcher.py`,
  `content_analyzer.py`, `version_generator.py`, `choice_gate.py`
  (add `_check_cancelled(state)` at entry)

---

## 9. Workflow Topology — Clear Completion Path

**Bug:** `analyst` writes `phase=ANALYZING`, `should_continue` routes back to
`orchestrator`. `engagement` is unreachable. No stable `completed` terminal state.

**Fix A — Two execution modes:**

```python
# backend/state/enums.py
class ExecutionMode(StrEnum):
    SINGLE = "single"          # publisher → analyst → engagement → completed
    CONTINUOUS = "continuous"  # publisher → analyst → orchestrator (loop)
```

**Fix B — Updated `should_continue` router:**

```python
def should_continue(state):
    if terminal := _check_terminal(state):
        return terminal

    mode = state.get("execution_mode", "single")
    if mode == "continuous":
        return "orchestrator"

    # Single mode: analyst → engagement → completed
    phase = state.get("phase")
    if phase == WorkflowPhase.ANALYZING:
        return "engagement"
    return "__end__"
```

**Fix C — `engagement` node writes `phase=COMPLETED`** in single mode, edge goes to END.

**Fix D — `execution_mode` in `WorkflowStartRequest`**, stored in initial state.

**Files changed:**
- `backend/state/enums.py` (add `ExecutionMode`)
- `backend/state/schema.py` (add `execution_mode` field)
- `backend/graph/routers.py` (update `should_continue`)
- `backend/agents/engagement.py` (write `phase=COMPLETED` in single mode)
- `backend/api/routes/workflow.py` (add `execution_mode` to start request)

---

## Implementation Order

Dependencies between fixes require this order:

1. **State machine** (Section 1) — foundation for everything else
2. **HITL mechanism** (Section 2) — unblocks review/choice flow
3. **Error handling** (Section 5) — needed before topology changes
4. **Topology** (Section 9) — depends on error handling guards
5. **SSE** (Section 3) — depends on EventBus having proper events
6. **Optimization API** (Section 4) — depends on HITL fix
7. **Version dedup** (Section 6) — independent, quick fix
8. **Persistence** (Section 7) — independent, can be done anytime
9. **Pause/Cancel** (Section 8) — depends on state machine + error handling

## Testing Requirements

Each fix needs contract tests:

- **Status derivation:** Test all 8 priority cases in `derive_status()`
- **HITL:** Test that `interrupt()` fires events before pausing, resume works
- **SSE:** Test that `/stream` never calls graph methods, multiple clients work
- **Optimization:** Test `/draft` and `/select` endpoints, `selected_title` in output
- **Error handling:** Test that `AgentError` propagates, retry fires, stale error clears
- **Version dedup:** Test that `content_versions` doesn't duplicate on revision
- **Persistence:** Test atomic writes, Postgres compilation path
- **Pause/Cancel:** Test `task.cancel()`, node entry guard, router guard
- **Topology:** Test single mode reaches `engagement` → `completed`, continuous loops
