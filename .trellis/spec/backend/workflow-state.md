# Workflow State & Status Derivation

## Scope / Trigger

- Any code that reads or writes workflow status (`running`, `completed`, `awaiting_review`, `awaiting_choice`, `error`, `cancelled`, `paused`)
- Any code that uses `StateSnapshot` from LangGraph to determine workflow state
- Any code that adds interrupt nodes or modifies the review/choice gate flow

## Signatures

### derive_status(snapshot: StateSnapshot, *, has_active_task: bool = True) -> WorkflowStatus

The single source of truth for computing workflow status from a LangGraph StateSnapshot.

```python
class WorkflowStatus(StrEnum):
    RUNNING = "running"
    STALE = "stale"
    AWAITING_REVIEW = "awaiting_review"
    AWAITING_CHOICE = "awaiting_choice"
    AWAITING_DRAFT = "awaiting_draft"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    ERROR = "error"
    COMPLETED = "completed"
```

Location: `backend/state/machine.py`

### Contracts

**Input:** A `langgraph.types.StateSnapshot` with fields:
- `values: dict` — current graph state (phase, error, execution_mode, etc.)
- `next: tuple[str, ...]` — node names scheduled to run next
- `tasks: tuple[PregelTask, ...]` — task objects (dataclass, NOT dict)
- `interrupts: tuple[Interrupt, ...]` — interrupt objects (empty with `interrupt_before`)

**Output:** A `WorkflowStatus` enum value.

**Priority chain** (checked in order, first match wins):
1. `phase == CANCELLED` → `cancelled`
2. `phase == PAUSED` → `paused`
3. `next` contains `"review_gate"` (with interrupt or interrupt_before) → `awaiting_review`
4. `next` contains `"choice_gate"` (with interrupt or interrupt_before) → `awaiting_choice`
5. Interrupt with gate value fallback (dynamic `interrupt()` only) → `awaiting_review` or `awaiting_choice`
6. `error` present AND (`phase == ERROR` OR `next` empty) → `error`
7. `phase == COMPLETED` → `completed`
8. `next` non-empty AND `has_active_task=False` → `stale`
9. `next` non-empty AND `has_active_task=True` → `running`
10. Fallback → `completed`

## Validation & Error Matrix

| Condition | Status | Notes |
|-----------|--------|-------|
| `phase=CANCELLED` | `cancelled` | Takes priority over everything |
| `phase=PAUSED` | `paused` | Takes priority over error |
| `next` contains `"review_gate"` | `awaiting_review` | Works for both `interrupt_before` and dynamic `interrupt()` |
| `next` contains `"choice_gate"` | `awaiting_choice` | Works for both `interrupt_before` and dynamic `interrupt()` |
| `snapshot.interrupts` has items, gate="review" | `awaiting_review` | Fallback when `next` doesn't contain gate name |
| `snapshot.interrupts` has items, gate="choice" | `awaiting_choice` | Fallback when `next` doesn't contain gate name |
| `snapshot.interrupts` has items, gate unknown | Falls to phase check | Unknown gate type does NOT default to review |
| `phase=COMPLETED, next=[]` | `completed` | Normal terminal state |
| `error` present, `phase=ERROR` | `error` | Explicit error phase |
| `error` present, `next=[]`, phase≠ERROR | `error` | Terminal error (no retry possible) |
| `error` present, `next` non-empty, phase≠ERROR | `running` | **Non-terminal error — may retry** |
| `next` non-empty, `has_active_task=True` | `running` | Normal in-progress |
| `next` non-empty, `has_active_task=False` | `stale` | **Background task gone but checkpoint remains — resumable** |
| `next=[], no error, phase not terminal` | `completed` | Fallback |

## Wrong vs Correct

### Wrong: Treating PregelTask as a dict
```python
# WRONG — PregelTask is a dataclass, not a dict
for task in snapshot.tasks:
    if isinstance(task, dict) and task.get("interrupts"):
        ...
```

### Correct: Use snapshot.interrupts + next_nodes
```python
# CORRECT — Two signals for gate detection:
# 1. snapshot.interrupts (non-empty with dynamic interrupt())
# 2. snapshot.next containing gate name (works with interrupt_before too)
has_interrupt = bool(snapshot.interrupts)
is_awaiting_gate = has_interrupt or bool(snapshot.next)
if is_awaiting_gate and snapshot.next:
    if "review_gate" in snapshot.next:
        return WorkflowStatus.AWAITING_REVIEW
    if "choice_gate" in snapshot.next:
        return WorkflowStatus.AWAITING_CHOICE
```

### Wrong: Hardcoding status after graph.ainvoke()
```python
# WRONG — doesn't detect interrupts or errors
result = await graph.ainvoke(state, config)
status = "completed"  # Interrupts return here too!
```

### Correct: Use derive_status
```python
result = await graph.ainvoke(state, config)
snapshot = await graph.aget_state(config)
status = derive_status(snapshot)
```

### Wrong: Returning ERROR for any truthy error field
```python
# WRONG — stale error from a previous node causes false ERROR
if values.get("error"):
    return WorkflowStatus.ERROR
```

### Correct: Only return ERROR when terminal
```python
# CORRECT — error is terminal only when phase=ERROR or no next nodes
if values.get("error") and (phase == WorkflowPhase.ERROR or not next_nodes):
    return WorkflowStatus.ERROR
# Non-terminal error with next nodes → RUNNING (may retry)
```

## Common Mistake: Mock StateSnapshot without interrupts field

When mocking `StateSnapshot` in tests, `MagicMock()` returns a truthy mock for any attribute access. This means `bool(snapshot.interrupts)` returns `True` even when no interrupts exist.

**Fix:** Always explicitly set `interrupts=[]` on mock snapshots:
```python
def make_snapshot(values, next=None, interrupts=None):
    snapshot = MagicMock()
    snapshot.values = values
    snapshot.next = next or []
    snapshot.tasks = []
    snapshot.interrupts = interrupts or []  # CRITICAL: must be explicit
    return snapshot
```

## Common Mistake: Stale error field overrides current phase

`BaseAgent.__call__` sets `result["error"] = None` on success, but if a snapshot is taken between nodes or a reducer partially merges, `values.get("error")` can be truthy even when the workflow has recovered. Always check `phase` and `next_nodes` alongside the error field.

**Symptom:** `derive_status` returns `ERROR` for a workflow that is actually running or completed.

**Fix:** Only return ERROR when `phase == ERROR` or `next` is empty (terminal).

## Interrupt Mechanism

### Two interrupt styles (use `interrupt_before`)

| Style | How | Re-executes on resume? | Side effects before pause? | `snapshot.interrupts` populated? |
|-------|-----|----------------------|---------------------------|-------------------------------|
| `interrupt_before=["node"]` | Static, in `graph.compile()` | No (node never ran) | No | **No** (empty tuple) |
| `interrupt(value)` inside node | Dynamic, in node body | **Yes** (node re-runs from top) | **Yes**, if code runs before `interrupt()` | Yes |

**Convention:** Use `interrupt_before=["review_gate", "choice_gate"]` in `graph.compile()`. Inside the node, `interrupt(None)` is a pure resume-receiver — it receives the value from `Command(resume=value)`. Do NOT put any side-effect code before `interrupt()` inside the node.

**Why `interrupt_before`:** Dynamic `interrupt()` inside nodes causes code before the call to execute twice (once on initial execution, once on resume). This leads to double event emission, double payload construction, and other side-effect bugs. `interrupt_before` prevents the node from executing at all until resumed, eliminating these issues.

**Critical:** With `interrupt_before`, `snapshot.interrupts` is always an empty tuple. The graph pause must be detected via `snapshot.next` containing the gate node name (e.g., `"review_gate"`). `derive_status` uses `next_nodes` as the primary detection signal, with `snapshot.interrupts` as a fallback.

### Event emission pattern

Events like `REVIEW_PENDING` and `WORKFLOW_DATA_UPDATED` (choice_pending) must be emitted from the API layer (`workflow.py`) when `derive_status` detects a status transition, NOT from inside the interrupt node.

```
Graph pauses at review_gate (interrupt_before) → API calls derive_status() →
  next contains "review_gate" → returns AWAITING_REVIEW →
  _emit_status_transition() emits REVIEW_PENDING event
```

The `_emit_status_transition` function in `_runner.py` handles this automatically. It tracks the last known status per thread and only emits on transitions.

## Workflow Metadata Persistence

### Status writes go to DB

All status updates (phase, status, progress_percent, error) are persisted to the `workflows` PostgreSQL table via `_db_upsert()` in `backend/api/routes/_runner.py`. The old JSON file registry (`_persist_registry` / `_save_registry`) has been removed.

### Status reads: live snapshot first, DB/history fallback

The `/status/{thread_id}` endpoint checks in order:
1. **Live LangGraph snapshot** (`graph.aget_state`) — authoritative for active workflows
2. **History file** (`_load_history_file`) — completed workflow results (pre-DB or fallback)
3. **DB row** (`db_get`) — metadata-only entries (workflow created but not yet checkpointed)

### Background task done callback

`_on_task_done` runs as a sync callback from `asyncio.Task.add_done_callback`. It cannot `await` — use `asyncio.ensure_future()` to schedule DB updates on the running event loop.

```python
# CORRECT pattern for sync callbacks
def callback(task):
    async def _do_update():
        existing = await db_get(thread_id)
        if existing and existing.status == "running":
            await db_update(thread_id, status="stale")
    asyncio.ensure_future(_do_update())
```

## Engagement Routing

### Single-exec vs continuous mode

The engagement node's outgoing edge is **conditional**, not fixed:

- **Single-exec** mode (default): `engagement → END` — workflow terminates after engagement
- **Continuous** mode: `engagement → orchestrator` — loops back for the next cycle

```python
# backend/graph/routers.py
def engagement_router(state: XHSGrowthState) -> Literal["orchestrator", "__end__"]:
    if terminal := _check_terminal(state):
        return terminal
    mode = state.get("execution_mode", "single")
    if mode == "continuous":
        return "orchestrator"
    return "__end__"
```

**Common Mistake:** Using `add_edge("engagement", "orchestrator")` creates an infinite loop in single-exec mode because engagement always routes back to orchestrator.

**Fix:** Use `add_conditional_edges("engagement", engagement_router, ...)` instead.

## Tests Required

- `test_derive_status_running`: scouting phase with next nodes, no interrupts → RUNNING
- `test_derive_status_awaiting_review`: next contains "review_gate" → AWAITING_REVIEW
- `test_derive_status_awaiting_choice`: next contains "choice_gate" → AWAITING_CHOICE
- `test_derive_status_awaiting_review_from_interrupt_value`: snapshot.interrupts with gate="review" → AWAITING_REVIEW
- `test_derive_status_awaiting_choice_from_interrupt_value`: snapshot.interrupts with gate="choice" → AWAITING_CHOICE
- `test_derive_status_interrupt_unknown_gate`: interrupts with unknown gate → falls to phase check
- `test_derive_status_completed`: phase=COMPLETED, next=[] → COMPLETED
- `test_derive_status_cancelled_over_error`: phase=CANCELLED + error → CANCELLED (not ERROR)
- `test_derive_status_paused_over_error`: phase=PAUSED + error → PAUSED (not ERROR)
- `test_derive_status_error_terminal`: phase=ERROR or next=[] + error → ERROR
- `test_derive_status_stale_no_active_task`: next non-empty + has_active_task=False → STALE
- `test_derive_status_stale_with_active_task`: next non-empty + has_active_task=True → RUNNING
- `test_derive_status_stale_not_override_gates`: STALE does not override awaiting_review/awaiting_choice
- `test_derive_status_stale_not_override_error`: STALE does not override ERROR/CANCELLED/PAUSED
- `test_on_task_done_records_error`: done callback records task_error on exception
- `test_on_task_done_marks_stale`: done callback marks registry as stale when task exits while running
- `test_resume_accepts_stale`: resume endpoint allows resuming from STALE status
- `test_derive_status_error_non_terminal`: error present + next non-empty + phase≠ERROR → RUNNING
- `test_engagement_router_single_mode`: execution_mode="single" → "__end__"
- `test_engagement_router_continuous_mode`: execution_mode="continuous" → "orchestrator"
- `test_engagement_router_default_single`: no execution_mode → "__end__"

## Ripple State Fields

### ripple_job_id and ripple_reason

When a Ripple simulation times out, the agent must preserve the `job_id` in state for cancel/recover:

| Field | Type | When Set | Purpose |
|-------|------|----------|---------|
| `ripple_job_id` | `str` | On timeout (even when fallback used) | Enable cancel_simulation and recover_result |
| `ripple_reason` | `str` or `None` | `"timeout"` only on actual timeout | Distinguish timeout from service-down or other failures |
| `ripple_prediction` | `dict` | On success or fallback | Prediction data (zeroed on fallback) |
| `ripple_pmf` | `dict` | On success or fallback | PMF data (zeroed on fallback) |

> **Warning**: `ripple_reason` must only be `"timeout"` when the simulation actually exceeded the wait window. Do not set it to `"timeout"` for other failures (service unavailable, no topic, etc.). This distinction matters because only timeout cases have a job_id that can be cancelled or recovered.

### Common Mistake: Discarding job_id on timeout

```python
# WRONG — returns None on timeout, job_id lost forever
except asyncio.TimeoutError:
    return None

# CORRECT — returns partial result with job_id for cancel/recover
except RippleTimeoutError as e:
    await self._ripple_cancel(e.job_id)
    return {"ripple_job_id": e.job_id, "ripple_reason": "timeout"}
except TimeoutError:
    return {"ripple_job_id": "", "ripple_reason": "timeout"}
```
