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
    AWAITING_BRIEF = "awaiting_brief"
    AWAITING_RIPPLE_DECISION = "awaiting_ripple_decision"
    AWAITING_BLOGGER_SELECTION = "awaiting_blogger_selection"
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
3. `next` contains gate name (`review_gate`, `choice_gate`, `draft_gate`, `brief_gate`, `ripple_gate`, `blogger_gate`) → corresponding `awaiting_*`
4. Interrupt with gate value fallback (dynamic `interrupt()` only) → `awaiting_review` / `awaiting_choice` / `awaiting_draft` / `awaiting_ripple_decision` / `awaiting_blogger_selection` / `awaiting_brief`
5. `error` present AND (`phase == ERROR` OR `next` empty) → `error`
6. `phase == COMPLETED` → `completed`
7. `next` non-empty AND `has_active_task=False` → `stale`
8. `next` non-empty AND `has_active_task=True` → `running`
9. Fallback → `completed`

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

### Gate Classification: Static vs Dynamic Interrupt

**Two gate types exist, each using a different interrupt strategy:**

| Gate Type | Nodes | Interrupt Style | Why |
|-----------|-------|----------------|-----|
| **Always-pause** | `review_gate`, `choice_gate`, `draft_gate` | `interrupt_before` in `graph.compile()` | These always need human input — no auto-accept logic |
| **Conditional-pause** | `ripple_gate`, `blogger_gate` | Dynamic `interrupt(payload)` inside node body | These have auto-accept/skip paths — interrupt only when user decision is needed |
| **Auto-routing** | `evaluator_gate` | No interrupt | AI judge panel (`agent-as-a-judge`) auto-routes by its own verdict — no human input needed. Node degrades to pass-through on failure (non-blocking). Decision read by router from `evaluation_result.decision`. |

**Critical Rule:** `interrupt_before` blocks the node body from running at all. If a node has conditional logic to auto-accept (like ripple_gate when results are good, or blogger_gate when no candidates exist), it MUST use dynamic `interrupt()` instead. Otherwise the auto-accept path never executes and the graph always pauses.

### Two interrupt styles compared

| Style | How | Re-executes on resume? | Side effects before pause? | `snapshot.interrupts` populated? |
|-------|-----|----------------------|---------------------------|-------------------------------|
| `interrupt_before=["node"]` | Static, in `graph.compile()` | No (node never ran) | No | **No** (empty tuple) |
| `interrupt(value)` inside node | Dynamic, in node body | **Yes** (node re-runs from top) | **Yes**, if code runs before `interrupt()` | Yes |

**For always-pause gates (`interrupt_before`):** The node body does NOT call `interrupt()`. The graph pauses before the node runs (via `interrupt_before` in `graph.compile()`). The submit endpoint writes the decision to state via `aupdate_state`, then advances the graph with `ainvoke(None)`. The node reads the decision from state and sets the phase. Do NOT use `Command(resume=value)` — it only works for dynamic `interrupt()`, not `interrupt_before`.

**For conditional-pause gates (dynamic `interrupt()`):** Put auto-accept/skip logic BEFORE the `interrupt()` call. Code before `interrupt()` runs on initial execution but is safe to re-run on resume because the auto-accept conditions will have been cleared by the resume value.

### Always-pause gate resume pattern (方案 B)

Always-pause gates (`review_gate`, `choice_gate`, `draft_gate`) use a unified resume pattern:

1. **Submit endpoint** writes the decision to state via `aupdate_state`
2. **Submit endpoint** advances the graph with `ainvoke(None)` (NOT `Command(resume=value)`)
3. **Gate node** reads the decision from state and sets the phase

```python
# submit endpoint (e.g., submit_review)
await graph.aupdate_state(config, {
    "human_feedback": decision.model_dump(),  # decision written to state
}, as_node=_get_as_node(state))
result = await _run_graph_and_persist(
    thread_id, graph, config,
    None,  # ainvoke(None) — NOT Command(resume=...)
    source="review",
)

# gate node (e.g., review_gate_node)
async def review_gate_node(state, *, store):
    _check_cancelled(state)
    # Decision is already in state (human_feedback), written by submit endpoint.
    # Just set the phase — the router reads human_feedback.decision.
    return NodeResult({"phase": WorkflowPhase.REVIEWING}, "review_gate").to_dict()
```

**Decision field per gate:**

| Gate | Submit writes | Node reads |
|------|--------------|------------|
| `review_gate` | `human_feedback` (dict with `decision` field) | Router `review_outcome` reads `human_feedback.decision` |
| `choice_gate` | `selected_version` (version_id string) | Node reads `state.selected_version`, finds version, fills `copy_content` |
| `draft_gate` | `draft_content` (dict with `source="user_submitted"`) | Node just sets phase — `draft_content` already in state |

**Critical:** `Command(resume=value)` only works for dynamic `interrupt()` inside a node body. For `interrupt_before`, the node never ran, so there's no `interrupt()` to resume from. Use `ainvoke(None)` to advance past the pause point.

### Interrupt payload contract for dynamic gates

Dynamic interrupt payloads MUST include a `"gate"` field so `derive_status` can identify the gate type from `snapshot.interrupts`:

```python
# ripple_gate — interrupt only when results are suboptimal
if not _is_ripple_suboptimal(state):
    return NodeResult({"ripple_decision": {"action": "accept", "source": "auto"}, ...})
# Results suboptimal — interrupt for user decision
interrupt_payload = {"gate": "ripple", "ripple_summary": {...}}
decision = interrupt(interrupt_payload)

# blogger_gate — interrupt only when candidates exist
if not candidates:
    return NodeResult({"blogger_skipped": True, ...})
# Candidates exist — interrupt for user selection
interrupt_payload = {"gate": "blogger", "blogger_candidates": candidates}
decision = interrupt(interrupt_payload)
```

### Detecting gate pauses in API routes

API routes that check whether a workflow is paused at a specific gate must handle BOTH interrupt styles:

```python
def _is_at_ripple_gate(state: StateSnapshot) -> bool:
    # Style 1: interrupt_before — gate name appears in next_nodes
    if "ripple_gate" in (state.next or []):
        return True
    # Style 2: dynamic interrupt() — gate type in interrupt payload
    if state.interrupts:
        for intr in state.interrupts:
            if isinstance(intr.value, dict) and intr.value.get("gate") == "ripple":
                return True
    return False
```

**Why both checks:** With `interrupt_before`, `snapshot.interrupts` is always empty and the gate name appears in `next_nodes`. With dynamic `interrupt()`, `next_nodes` may be empty (the node is mid-execution) but `snapshot.interrupts` is populated with the payload.

`derive_status` already handles this internally — it checks `next_nodes` first, then falls back to `snapshot.interrupts` gate type.

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

### Recover: checkpoint_lost diagnostic (not 404)

`POST /recover/{thread_id}` checks for a live LangGraph checkpoint first. When
`aget_state` returns no state (checkpoint lost — e.g. after a container restart
where the checkpoint DB was wiped but the `workflows` metadata row survived),
it does NOT immediately 404. Instead:

1. If `is_pool_ready()`, query the DB row via `db_get(thread_id)`.
2. If the DB row exists AND its status is non-terminal (running/stale/paused/
   awaiting_*) AND there is no active background task → return 200 with
   `{recovered: False, status: "checkpoint_lost", message: "...建议 /resume restart 重新开始"}`.
3. If the DB row is terminal (completed/cancelled/error) or missing entirely →
   `WorkflowNotFoundError` 404 (truly nonexistent or already finished).

**Why:** A bare 404 on `/recover` for a workflow that `/status` shows as
"checkpoint_lost / recoverable" is a broken UX — the user sees "可恢复" then
gets 404 on the recover attempt. The diagnostic tells them to use `/resume`
with a restart strategy instead.

**Consistency:** The `checkpoint_lost` condition uses the same non-terminal
status set and `has_active_task` check as the `/status` route's
`checkpoint_lost` field — the two routes agree on what constitutes "lost but
recoverable."

## Progress Calculation

### PHASE_PROGRESS mapping

```python
PHASE_PROGRESS = {
    "idle": 0,
    "briefing": 15,
    "scouting": 10,
    "planning": 20,
    "creating": 40,
    "reviewing": 60,
    "publishing": 80,
    "analyzing": 90,
    "engaging": 95,
    "completed": 100,
    "error": 0,
}
```

### Progress rules

1. **Completed** (`derive_status` returns `COMPLETED`) → always 100%, regardless of phase
2. **Error** → always 0%
3. **All other states** (running, awaiting_*, paused, stale) → `PHASE_PROGRESS[phase]`

**Common Mistake:** Using binary `0/100` for non-completed states. This causes progress to reset to 0% when a workflow is awaiting review (phase=reviewing, progress should be 60%).

```python
# WRONG — resets progress to 0 for awaiting states
progress = 100 if final_status == "completed" else 0

# CORRECT — use phase-based progress for non-terminal states
if final_status == "completed":
    progress = 100
elif final_status == "error":
    progress = 0
else:
    progress = get_progress(final_phase)
```

### Brief mode awaiting_brief status

When brief mode starts without `brief_text` (waiting for PDF upload), the start endpoint must return `status="awaiting_brief"` (not `"running"`). There is no active background task, so returning `"running"` causes `derive_status` to see `next_nodes` without `has_active_task` → `stale`.

## TrendData Field Contract

### Canonical field: `hot_topics`

The `should_plan` router checks `trend_data` for actionable trends. The LLM may output `hot_topics`, `trending_topics`, or `topics` as the key name. Both the router and the trend_scout agent must handle all aliases:

```python
# should_plan — check all aliases
if trend_data:
    has_topics = bool(
        trend_data.get("hot_topics")
        or trend_data.get("trending_topics")
        or trend_data.get("topics")
    )

# trend_scout — normalize to canonical hot_topics after parsing
if not trend_data.get("hot_topics"):
    trend_data["hot_topics"] = (
        trend_data.get("trending_topics")
        or trend_data.get("topics")
        or []
    )
```

**Why normalization:** Without it, `{"trending_topics": [...]}` causes `should_plan` to return `__end__`, terminating the workflow after scouting even though trends were found.

## User Topic Override (`state["topic"]`)

`/workflow/start` accepts a `topic` param, stored as `initial_state["topic"]` (field declared `topic: str` in `XHSGrowthState`). It is an **optional user-provided topic override**. Two agents consume it:

### `trend_scout`
`_fetch_real_data(niche, account_id, user_topic)` builds the `keyword_monitor` seed as `[niche]` with `user_topic` **prepended** (first, when non-empty) so trend/keyword scouting revolves around the user's topic, not just the niche. `xhs_trending` still queries by `niche` (the trend category is niche-scoped; the topic seeds keyword monitoring).

### `content_strategist` — selection core + drift-guard bypass
`execute()` reads `user_topic = state.get("topic")`. Behavior branches on it:

- **`user_topic` set (non-empty):** the user topic is the selection core.
  - Injected into `user_msg` as `用户指定主题：{user_topic}`.
  - A `【用户指定主题】` branch is prepended to `memory_context` (→ system prompt `extra_context`) instructing the LLM that `selected_topic` must revolve around the user topic, trend data is only a borrow-momentum/angle reference.
  - The `content_strategist.yaml` hard constraint (select from trend candidates) has an explicit exception clause for this case.
  - **The candidate-set drift guard is SKIPPED** — `if user_topic:` logs and returns; no retry regen. A user topic that is not in the trend candidate set is *expected*, not drift.
- **`user_topic` empty/absent:** behavior unchanged. `selected_topic` must come from `_extract_candidate_topics(trend_data)`; if it misses the candidate set, a retry regen forces it back (sets `content_plan["topic_revised"] = True`).

```python
user_topic = str(state.get("topic") or "").strip()
...
if user_topic:
    memory_context = (f"\n【用户指定主题】{user_topic}" + ...) + memory_context
...
candidates = self._extract_candidate_topics(trend_data)
if user_topic:
    logger.info(...)  # skip drift guard
elif candidates and content_plan.get("selected_topic") not in candidates:
    # retry regen with correction hint
```

**Why this exists:** before the fix, `state["topic"]` was dead data — no agent read it, and the dual drift guard (YAML hard constraint + code retry regen) actively pulled the LLM back to the trend candidate set, so a user-specified topic was silently ignored.

**Tests** (`tests/unit/agents/test_content_strategist.py`, `test_trend_scout.py`):
- `test_user_topic_skips_drift_guard`: topic not in candidates → `ainvoke.await_count == 1` (no retry), topic present in user_msg, `selected_topic` honored, `topic_revised` absent.
- `test_no_user_topic_keeps_drift_guard`: no topic + miss → `await_count == 2`, `topic_revised is True`.
- `test_user_topic_added_to_keyword_seed`: `keyword_monitor` invoked with `keywords[0] == user_topic`.

## Blogger Skip Routing

### Infinite loop prevention

When blogger selection is skipped (no candidates or user skips), the routing must NOT go back through `viral_matcher`. The loop would be:

```
draft_gate → viral_matcher → blogger_scout → blogger_gate (skip) →
draft_gate → viral_matcher → ... (infinite)
```

**Fix:** Set `blogger_skipped=True` in state when skipping, and check it in `draft_gate_router`:

```python
def draft_gate_router(state):
    if selected_blogger and selected_blogger.get("user_id"):
        return "shooting_planner"
    # Blogger was skipped → go directly to shooting_planner
    if state.get("blogger_skipped"):
        return "shooting_planner"
    if mode == "brief":
        return "shooting_planner"
    return "viral_matcher"
```

## Exception Handling in API Routes

### Don't swallow _run_graph_and_persist exceptions

The `_run_graph_and_persist` function already handles errors: it sets `phase=error` in graph state and DB, then re-raises. API routes that catch this exception and return fake success hide the error from the client.

```python
# WRONG — hides execution failure, returns "resumed" even when DB has error status
try:
    result = await _runner._run_graph_and_persist(...)
except Exception:
    result = {}
next_phase = result.get("phase", "unknown")  # always "unknown" on error
return success(data={"status": "resumed", "next_phase": next_phase})

# CORRECT — let exception propagate to global error handler
result = await _runner._run_graph_and_persist(...)
next_phase = result.get("phase", "unknown") if result else "unknown"
return success(data={"status": "resumed", "next_phase": next_phase})
```

The global FastAPI exception handler converts `APIError` subclasses into proper error responses.

## CLI Resume and Gate Interrupts

The CLI `resume` command must not blindly call `graph.ainvoke(None, config)` when the workflow is paused at a gate. Passing `None` as input to an interrupted graph causes `interrupt()` to receive `None`, which may default to rejected/invalid.

**Rules for CLI resume:**
1. **Always-pause gates** (review_gate, draft_gate, choice_gate): Refuse auto-resume — these need human input via API/frontend
2. **Conditional-pause gates** (ripple_gate, blogger_gate): Auto-resume with sensible defaults (`accept` for ripple, `skip` for blogger)
3. **Non-gate nodes** (stale/error resume): Use `ainvoke(None, config)` as before

```python
if "review_gate" in next_nodes:
    console.print("⚠️ 需要 API/前端提交审核决定")
    return
if state.interrupts:
    gate = state.interrupts[0].value.get("gate")
    if gate == "ripple":
        resume_value = Command(resume={"action": "accept"})
    elif gate == "blogger":
        resume_value = Command(resume={"skip": True})
await graph.ainvoke(resume_value, config)
```

## Post-publish and legacy engagement states

The publisher terminates the workflow after publishing. Post-publish analysis
is manual and is never followed by automatic comment or DM interaction.

Legacy checkpoints may still contain `WorkflowPhase.ENGAGING` or an
`engagement` next node from older graph versions. The orchestrator must route
the legacy phase to `__end__`, and status inference must treat the removed
next node as completed. It must never instantiate a replacement interaction
node or restart browser activity.

## Router Terminal Guard Convention

### All conditional routers must call `_check_terminal(state)` first

Every conditional edge router in `backend/graph/routers.py` MUST start with:

```python
if terminal := _check_terminal(state):
    return terminal
```

**Why:** Without the guard, a router may route to a node that overwrites the error
phase. The critical case is `content_strategist_router`: without the guard,
phase=ERROR falls through to `ripple_gate`, which auto-accepts when Ripple data
is absent (viral_prob/pmf default to 1.0), overwriting the error phase with
`creating` — silently swallowing the strategist failure.

**Convention:** The return type of a router that gets the guard must include
`"__end__"` in its `Literal[...]` annotation. Example:

```python
def content_strategist_router(
    state: XHSGrowthState,
) -> Literal["ripple_finalize", "ripple_gate", "__end__"]:
    if terminal := _check_terminal(state):
        return terminal
    ...
```

**Audit:** Most routers already have the guard (e.g. `ripple_finalize_router`,
`orchestrator_router`). If a new router is added or an
existing one is missing the guard, add it — the risk of silent error-phase
overwrite is high for any router that feeds into a node with auto-accept logic.

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
- `test_should_continue_single_mode_after_analysis`: ANALYZING → "__end__"
- `test_orchestrator_router_legacy_engaging`: ENGAGING → "__end__"

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

## Frontend Multi-Workflow Pattern

### Store Architecture

The `workflowStore` (frontend/src/stores/workflow.ts) supports multiple concurrent workflows:

| State | Type | Purpose |
|-------|------|---------|
| `workflowStates` | `Map<string, WorkflowStateResponse>` | Per-thread state cache |
| `activeThreadId` | `ref<string \| null>` | Currently viewed workflow tab |
| `openTabIds` | `ref<string[]>` | Ordered list of open tab IDs |
| `tabLabels` | `Record<string, string>` | Custom tab labels |
| `rippleProgressMap` | `Map<string, RippleProgress>` | Per-thread ripple progress |

### Computed backward-compat layer

`currentThreadId` and `workflowState` are computed from `activeThreadId` + `workflowStates` map, keeping existing component code working without changes.

### WebSocket event routing

All WS event handlers use `msg.thread_id` to route to the correct entry in `workflowStates` map. The `if (msg.thread_id === activeThreadId.value)` guard ensures progress/overlay updates only affect the visible tab.

### Tab persistence

Open tab IDs and labels are persisted to `localStorage` keys: `activeThreadId`, `openTabIds`, `tabLabels`.

### Tab fold limit

When `openTabIds.length > 8`, tabs beyond index 8 move to an overflow dropdown (`overflowTabs` computed).

### Common Mistake: Direct assignment to workflowState

After the multi-workflow refactor, `workflowState` is a computed property (derived from `workflowStates[activeThreadId]`). It cannot be directly assigned. Use `workflowStates.set(threadId, newState)` or the `updateWorkflowState()` helper instead.

```typescript
// WRONG — workflowState is a computed, read-only
workflowStore.workflowState = null

// CORRECT — remove the tab or update the map
workflowStore.closeTab(threadId)
// or
workflowStore.workflowStates.set(threadId, newState)
```
