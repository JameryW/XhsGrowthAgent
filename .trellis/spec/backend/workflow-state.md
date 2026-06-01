# Workflow State & Status Derivation

## Scope / Trigger

- Any code that reads or writes workflow status (`running`, `completed`, `awaiting_review`, `awaiting_choice`, `error`, `cancelled`, `paused`)
- Any code that uses `StateSnapshot` from LangGraph to determine workflow state
- Any code that adds interrupt nodes or modifies the review/choice gate flow

## Signatures

### derive_status(snapshot: StateSnapshot) -> WorkflowStatus

The single source of truth for computing workflow status from a LangGraph StateSnapshot.

```python
class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    AWAITING_CHOICE = "awaiting_choice"
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
- `interrupts: tuple[Interrupt, ...]` — interrupt objects from `interrupt()` calls

**Output:** A `WorkflowStatus` enum value.

**Priority chain** (checked in order, first match wins):
1. `snapshot.interrupts` non-empty → inspect `.value["gate"]` → `awaiting_review` or `awaiting_choice`
2. `phase == COMPLETED` and `next` empty → `completed`
3. `phase == CANCELLED` → `cancelled`
4. `phase == PAUSED` → `paused`
5. `error` present and terminal → `error`
6. `next` non-empty and phase not terminal → `running`
7. Fallback → `completed`

## Validation & Error Matrix

| Condition | Status | Notes |
|-----------|--------|-------|
| `snapshot.interrupts` has items, gate="review" | `awaiting_review` | Human-in-the-loop at review gate |
| `snapshot.interrupts` has items, gate="choice" | `awaiting_choice` | Human-in-the-loop at choice gate |
| `snapshot.interrupts` has items, gate unknown | Falls to phase check | Unknown gate type does NOT default to review |
| `phase=COMPLETED, next=[]` | `completed` | Normal terminal state |
| `phase=CANCELLED` | `cancelled` | Takes priority over error |
| `phase=PAUSED` | `paused` | Takes priority over error |
| `error` present, `next=[]` | `error` | Error in terminal node |
| `error` present, `next` non-empty | `running` | Error in non-terminal — may retry |
| `next` non-empty, phase not terminal | `running` | Normal in-progress |
| `next=[], no error, phase not terminal` | `completed` | Fallback |

## Wrong vs Correct

### Wrong: Treating PregelTask as a dict
```python
# WRONG — PregelTask is a dataclass, not a dict
for task in snapshot.tasks:
    if isinstance(task, dict) and task.get("interrupts"):
        ...
```

### Correct: Use snapshot.interrupts
```python
# CORRECT — StateSnapshot has a top-level interrupts field
has_interrupt = bool(snapshot.interrupts)
if has_interrupt:
    interrupt_val = snapshot.interrupts[0].value
    if isinstance(interrupt_val, dict):
        gate_type = interrupt_val.get("gate")
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

## Interrupt Mechanism

### Two interrupt styles (use dynamic only)

| Style | How | Re-executes on resume? | Events emitted twice? |
|-------|-----|----------------------|----------------------|
| `interrupt_before=["node"]` | Static, in `graph.compile()` | No (node never ran) | N/A |
| `interrupt(value)` inside node | Dynamic, in node body | **Yes** (node re-runs from top) | **Yes**, if events emitted before `interrupt()` |

**Convention:** Use dynamic `interrupt()` only. `interrupt_before` was removed to fix event timing issues.

**Critical:** Code before `interrupt()` inside a node runs TWICE — once on initial execution (interrupt raises `GraphInterrupt`) and once on resume (interrupt returns the resume value). Events must NOT be emitted from inside interrupt nodes.

### Event emission pattern

Events like `REVIEW_PENDING` and `WORKFLOW_DATA_UPDATED` (choice_pending) must be emitted from the API layer (`workflow.py`) when `derive_status` detects a status transition, NOT from inside the interrupt node.

```
Node calls interrupt() → graph pauses → API calls derive_status() →
  detects AWAITING_REVIEW → emits REVIEW_PENDING event
```

## Tests Required

- `test_derive_status_running`: scouting phase with next nodes, no interrupts → RUNNING
- `test_derive_status_awaiting_review`: snapshot with interrupts, gate="review" → AWAITING_REVIEW
- `test_derive_status_awaiting_choice`: snapshot with interrupts, gate="choice" → AWAITING_CHOICE
- `test_derive_status_interrupt_unknown_gate`: interrupts with unknown gate → falls to phase check
- `test_derive_status_completed`: phase=COMPLETED, next=[] → COMPLETED
- `test_derive_status_cancelled_over_error`: phase=CANCELLED + error → CANCELLED (not ERROR)
- `test_derive_status_paused_over_error`: phase=PAUSED + error → PAUSED (not ERROR)
