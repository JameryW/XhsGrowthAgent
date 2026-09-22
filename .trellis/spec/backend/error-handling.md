# Error Handling & Retry

## Scope / Trigger

- Any code that raises or catches exceptions in agent nodes
- Any code that configures LangGraph retry policies
- Any code that cancels or pauses running workflows
- Any code that reads the `error` field from workflow state

## Signatures

### Exception Hierarchy

```python
class AgentError(Exception):
    """Raised by BaseAgent when execution fails after retries."""
    agent_name: str
    cause: Exception  # original exception

class WorkflowCancelledError(Exception):
    """Raised by _check_cancelled when workflow is cancelled/paused."""
    pass

class RippleTimeoutError(TimeoutError):
    """Raised when Ripple simulation exceeds max_wait. Carries job_id for cancel/recover."""
    job_id: str
    max_wait: float
```

### RippleTimeoutError Catch Order

> **Warning**: `RippleTimeoutError` is a subclass of `TimeoutError`. When catching both, **always catch the subclass first**.

```python
# WRONG — TimeoutError catches RippleTimeoutError too, losing job_id
except TimeoutError:
    ...
except RippleTimeoutError:  # UNREACHABLE
    ...

# CORRECT — subclass first
except RippleTimeoutError as e:
    # e.job_id is available for cancel/recover
    ...
except TimeoutError:
    # generic asyncio timeout (no job_id)
    ...
```

### Retry Policy Connection

```python
# backend/graph/error_handling.py — exhaustive registry keyed by REAL graph node names
RETRY_POLICIES: dict[str, RetryPolicy | None] = {
    "trend_scout": RetryPolicy(max_attempts=3),
    "publisher": None,  # side-effecting node — generic auto-retry is FORBIDDEN
    ...
}

def get_retry_policy(node_name: str) -> RetryPolicy | None:
    """RETRY_POLICIES[node_name] — raises KeyError for unregistered nodes.
    A "no framework retry" decision must be an explicit None entry, never a
    silent miss. builder registers a policy for every node in build_graph()
    (tests/unit/graph/test_retry_registry.py asserts the full inventory)."""
```

Because `BaseAgent.__call__` swallows agent-level exceptions (see below), these
policies in practice only fire on wrapper-side raises (`_check_cancelled`,
event-bus errors). Do not assume `max_attempts=N` retries the LLM call itself.

### Error Taxonomy (`error_class`)

`handle_agent_error` runs `classify_error()` and writes an additive state field
`error_class` into the checkpoint (declared in `backend/state/schema.py`):

| Class | Examples | Intended policy |
|-------|----------|-----------------|
| `transient` | network/429/timeout | stateful retry (current routers) |
| `semantic` | malformed output / no result | repair / replan (P1 structured-output) |
| `side_effect_unknown` | publish submitted but no verdict | idempotency guard + reconcile + explicit human force — never auto-retry |
| `policy_violation` / `auth_expired` | compliance, expired login | fail-closed, human required |

P0 keeps routing behavior unchanged (default `transient` = legacy path); the
taxonomy is the contract that P1c/P2a retry consolidation must consume.

## Contracts

### BaseAgent Error Behavior

- `BaseAgent.__call__` **catches** agent exceptions and routes them through
  `handle_agent_error(...)` → `phase=ERROR` + `error` + `retry_count+1` + `error_class`
  (stateful retry; explicit trade-off documented at `backend/agents/base.py` —
  the framework-level `RetryPolicy` therefore only sees wrapper-side raises).
- Successful execution clears stale `error` field from state (`result["error"] = None`)
- **No request-scoped state on agent instances.** Agents are module-level singletons
  shared by concurrent asyncio workflows. LLM perf entries live in a
  `contextvars.ContextVar` scoped to `__call__`; per-request evaluation inputs use a
  frozen `EvaluationContext` passed as a local. Never add `self._<something>` writes
  inside `execute()`/`__call__` paths (P0 fix W1; regression-locked by
  `tests/unit/agents/test_base_agent.py`).

### Cancel/Pause Guard

- `_check_cancelled(state)` in `backend/agent/nodes/_base.py` raises `WorkflowCancelledError` at node entry
- `cancel_workflow` cancels the background `asyncio.Task` via `task.cancel()`
- `pause_workflow` also cancels the background task (same as cancel)
- Resume re-invokes the graph from the last checkpoint

### Ripple Service Error Behavior

#### Timeout → Cancel → Recover Pattern

When an agent calls Ripple and the simulation times out:

1. `RippleService.wait_for_completion` raises `RippleTimeoutError(job_id, max_wait)`
2. Agent catches `RippleTimeoutError`, extracts `job_id`
3. Agent calls `cancel_simulation(job_id)` — uses `cancel-request` + `cancel-confirm`, with legacy DELETE fallback on 405
4. Agent saves `ripple_job_id` in result dict with `ripple_reason: "timeout"`
5. Later, `recover_result(job_id)` can check if the job completed asynchronously

#### cancel_simulation Contracts

```python
async def cancel_simulation(job_id: str) -> dict[str, Any]:
    """Attempt to cancel a running Ripple simulation.

    Returns:
        {"cancelled": bool, "job_id": str, "status": str}
        status: "cancelled" | "cancelling" | "not_found" | "not_supported" | "not_cancellable" | "error"
    """
```

- `POST /cancel-request` 200/201/202 with `cancel_token`, then `POST /cancel-confirm` 200/201/202/204 → `{"cancelled": True, "job_id": ..., "status": "cancelling" | ...}`
- `POST /cancel-request` 404 → `{"cancelled": False, "job_id": ..., "status": "not_found"}`
- `POST /cancel-request` 409 → `{"cancelled": False, "job_id": ..., "status": "not_cancellable"}`
- `POST /cancel-request` 405 → fallback to legacy DELETE
- legacy DELETE 200/204 → `{"cancelled": True, "job_id": ..., "status": "cancelled"}`
- legacy DELETE 404 → `{"cancelled": False, "job_id": ..., "status": "not_found"}`
- legacy DELETE 405 → `{"cancelled": False, "job_id": ..., "status": "not_supported"}`
- Network error → `{"cancelled": False, "job_id": ..., "status": "error", "error": str}`
- Cancel failure is **never fatal** — logged but does not block the agent

#### recover_result Contracts

```python
class RecoveryStatus(BaseModel):
    job_id: str
    status: str  # "completed" | "running" | "timed_out" | "failed" | "not_found"
    result: dict[str, Any] | None = None
    error: str = ""
```

- Designed for future background polling — callers check `status` and act accordingly
- If `status == "completed"`, `result` contains the full simulation output
- If `status == "running"`, no result yet (caller can retry later)
- If `status == "timed_out"`, Ripple has reached a server-side phase/job timeout and there is no result to recover

#### ripple_reason field semantics

The `ripple_reason` field in result dicts distinguishes timeout from other failures:
- `"timeout"` — Ripple simulation exceeded the wait window
- `None` or absent — Ripple succeeded, or failed for non-timeout reasons (service down, no topic, etc.)

> **Warning**: Do NOT set `ripple_reason = "timeout"` for non-timeout failures. The content_strategist uses this field to decide whether to attempt cancel and save job_id for recovery.

Completed Ripple jobs can still contain no legacy absolute metrics. That is not an error and must not set `ripple_reason`. Parse `prediction.relative_estimate`, `prediction.verdict`, and `observation.phase_vector` as valid result data; otherwise UI and downstream agents will mistake a completed job for service fallback.

The `error` field in state can be stale — set by a failed node but not yet cleared by the next successful node. `derive_status` handles this by only returning ERROR when the error is terminal:

- `error` present + `phase == ERROR` → ERROR (explicit error phase)
- `error` present + `next == []` → ERROR (terminal, no retry possible)
- `error` present + `next` non-empty + `phase ≠ ERROR` → RUNNING (non-terminal, may retry)

## Common Mistake: Pausing doesn't stop the running task

Pausing only sets `phase="paused"` in state. The background asyncio task continues executing until `_check_cancelled` is checked at the next node entry. Mid-execution LLM calls are NOT interrupted.

**Fix:** Cancel the background task on pause:
```python
bg_task = _background_tasks.get(thread_id)
if bg_task and not bg_task.done():
    bg_task.cancel()
```

## Common Mistake: Exception in node flows through conditional edges

In LangGraph, an unhandled exception in a node does NOT route through conditional edges. The graph stops execution. The `_check_terminal` router only applies to normal (non-error) state transitions.

## Common Mistake: Stale error field causes false ERROR status

The `error` field persists in state across node transitions. If node A fails (sets `error`), then node B succeeds (sets `error=None`), but a snapshot is read between these updates, `error` may still be truthy. Additionally, the `merge_dict` reducer may partially merge, leaving stale error values.

**Symptom:** `derive_status` returns ERROR for a workflow that is actually running.

**Fix:** `derive_status` only returns ERROR when `phase == ERROR` or `next` is empty. A truthy `error` field with non-empty `next` and non-error `phase` returns RUNNING.

```python
# WRONG — any truthy error returns ERROR
if values.get("error"):
    return WorkflowStatus.ERROR

# CORRECT — only terminal errors return ERROR
if values.get("error") and (phase == WorkflowPhase.ERROR or not next_nodes):
    return WorkflowStatus.ERROR
```

## Scenario: Publish Side-Effect Outcomes, Idempotency & Quality-Gate Pause (P0-W4/W5)

### Contracts

- **No generic retry around the submit action.** `XHSClient.publish_post` must not carry a blanket `@retry` — a post-click retry can double-post. Only pre-submit/read phases may retry.
- **Outcome trichotomy** in `run_publish`: definite pre-submit failure → `status="failed"` (guard released); post-click timeout / no verdict → `status="unknown"` with typed `error_type="publish_result_unknown"` and `result_known=False` (guard stays armed). Never map ambiguous outcomes to `failed`.
- **Idempotency record:** before a real (non-dry-run) submit, a record keyed by `compute_publish_id` (sha256 of account + content + images + time window) is pre-written as `"unknown"`, then upgraded/downgraded. A second real publish hitting an armed `published`/`unknown` record is blocked with structured `error_type="duplicate_publish_blocked"` recovery.
- **`force_publish` is one-shot:** consumed on every execution outcome and cleared from state/publish_options afterwards — it must never persistently disarm the guard for later publishes on the same thread.
- **`/publish-retry` for `unknown`:** reconcile first (idempotency record + ContentHistory trail); only `confirm-published` or an explicit body `{"force": true}` proceeds. Dry-run double guard (`state.dry_run` OR `publish_options.dry_run`) is untouched and outranks everything above.

### Quality-gate fail-closed continuation

- `evaluator_requires_human` (backend/graph/routers.py) is the SINGLE predicate for "human required"; the evaluator node stamps `phase=PAUSED` + `pause_reason="evaluator_fail_closed"` with it, and the router returns `__end__` with it — the two can never diverge.
- Resume of such a terminal thread REQUIRES body `{"human_decision": "approve"|"revise"}`: approve patches `evaluation_result` (cleared `failed_dimensions`, `degraded=False`, `decision=approved`) via `aupdate_state(as_node="evaluator_gate")` so the conditional edge goes straight to `publisher` without re-running upstream; revise grants a fresh revision budget. Missing/invalid decision → 4xx structured error — never the legacy whole-pipeline restart. Legacy pauses (no `pause_reason`) keep old resume behavior.

### Tests Required

`tests/unit/agents/test_run_publish.py` (timeout→unknown, duplicate blocked, force one-shot), `tests/unit/services/test_xhs_publisher.py` (submit contract, no `.retry` on publish_post), `tests/integration/test_evaluator_pause_resume.py` + `tests/unit/api/test_resume_evaluator_pause.py` (decision-gated resume, no restart), `tests/unit/graph/test_retry_registry.py` (full node inventory, publisher None, KeyError).

## Scenario: Publish Failure Recovery Shape (Cross-Layer Contract)

### 1. Scope / Trigger
- Trigger: Any code path that sets `publish_result["recovery"]` in `PublisherAgent` or any agent returning a publish-style failure. This is a cross-layer contract — the frontend `Dashboard.vue` consumes `publishError.recovery` as a structured object, not a string.

### 2. Signatures
- `backend/api/errors.py: classify_publish_error(error_msg: str) -> tuple[PublishErrorType, dict]`
- `PublisherAgent.execute` returns `publish_result["recovery"]` consumed by `frontend/src/views/Dashboard.vue` via `publishError.recovery.{hint,action,action_label}` and `frontend/src/stores/workflow.ts:329`.

### 3. Contracts
`recovery` MUST be a dict with these fields (matches `_PUBLISH_RECOVERY_ACTIONS` shape):
- `message: str` — human-readable explanation
- `action: str` — one of `"reconfigure"` | `"retry"` | `"wait"` | `"contact_support"` (frontend routes `reconfigure` → `/start`)
- `action_label: str` — button label
- `hint: str` — actionable guidance

```python
# WRONG — string breaks Dashboard.vue rendering (empty hint, no button)
publish_result = {
    "status": "failed",
    "error_type": "no_cookie",
    "recovery": "请在设置页为该账号配置 XHS_COOKIE",
}

# CORRECT — structured dict, same shape as classify_publish_error()
publish_result = {
    "status": "failed",
    "error_type": "no_cookie",
    "recovery": {
        "message": "该账号未配置 XHS_COOKIE，无法发布",
        "action": "reconfigure",
        "action_label": "重新配置",
        "hint": "请在设置页为该账号配置 XHS_COOKIE",
    },
}
```

### 4. Validation & Error Matrix
- account has no cookie AND no CDP endpoint (pre-publish) → `error_type="no_cookie"`, structured `recovery` dict, `XHSClient` NOT constructed (fail fast). Recovery hint mentions both "配置 XHS_COOKIE" and "扫码登录写入 profile".
- account has no cookie BUT per-account CDP endpoint present → **NOT a fail**. CDP mode (`xhs_publisher._ensure_page` CDP branch) uses the profile's login state and ignores `self.cookie`, so the cookie check is skipped. Empty cookie is passed through to `XHSClient` (harmless under CDP). `run_publish` logs "靠 CDP profile 登录态发布".
- account is_active=False (pre-publish) → `error_type="account_inactive"`, structured `recovery` dict, `XHSClient` NOT constructed (fail fast). Checked BEFORE the cookie/CDP check (cheaper, avoids a wasted real-Chrome publish).
- cookie present but publish throws auth error → `classify_publish_error` maps to `error_type="auth_expired"`, structured `recovery` dict (from `_PUBLISH_RECOVERY_ACTIONS`)
- any new failure path returning `recovery` → MUST be a dict, never a bare string

### 5. Good/Base/Bad Cases
- Good: `recovery` is a dict on every publish-failure path; frontend renders hint + reconfigure button.
- Base: `classify_publish_error` path (the original) returns dict correctly.
- Bad: a new inline failure path (e.g. `no_cookie`) returns a string → frontend renders empty hint paragraph, no recovery button. (This bug actually shipped and was caught in review.)

### 6. Tests Required
`tests/unit/agents/test_publisher_account.py`:
- `test_no_cookie_when_account_unconfigured`: assert `recovery` is `dict`, `recovery["action"]=="reconfigure"`, non-empty `hint` and `action_label`. Mocks `get_account` (active) + both CDP endpoints empty, so the no-cookie-and-no-CDP fail path triggers.
- `test_selected_account_expired_cookie_classified`: assert `error_type=="auth_expired"` and `recovery` is `dict` with `action=="reconfigure"`.

`tests/unit/agents/test_run_publish.py`:
- `test_no_cookie_returns_failed_no_cookie`: no cookie + no CDP endpoint (global resolver mocked to `""`) → `no_cookie` fail, `XHSClient` NOT constructed.
- `test_no_cookie_with_cdp_endpoint_proceeds`: no cookie + per-account CDP endpoint present → NO fail, `XHSClient` constructed with `cookie=""` and the endpoint, publish proceeds. Locks the "CDP profile covers missing cookie" contract.

Assertion point: any test covering a publish-failure path MUST assert `isinstance(recovery, dict)` — this is the regression guard.

### 7. Wrong vs Correct
See §3 Contracts — the Wrong/Correct pair is the string-vs-dict `recovery`.

> **Gotcha**: When adding a NEW publish-failure short-circuit (before `classify_publish_error` runs), it's easy to write `"recovery": "<string>"` by instinct. The frontend silently degrades (no crash, just missing UI), so the bug is invisible without a test. Always mirror the dict shape and add an `isinstance` assertion.

## Tests Required

- `test_cancel_cancels_background_task`: cancel_workflow calls task.cancel()
- `test_pause_cancels_background_task`: pause_workflow calls task.cancel()
- `test_check_cancelled_raises`: _check_cancelled raises WorkflowCancelledError when phase=cancelled
- `test_agent_error_propagates`: AgentError is not swallowed, graph stops
- `test_error_with_next_nodes_returns_running`: error + next non-empty + phase≠ERROR → RUNNING
- `test_error_with_no_next_nodes_returns_error`: error + next empty → ERROR
- `test_error_phase_returns_error`: phase=ERROR → ERROR

## Scenario: Honest RQGM degraded and partial results

### 1. Scope / Trigger
- Trigger: evaluator timeout, model/JSON failure, missing dimensions, missing
  niche context, or unavailable image input reaches an API/UI consumer.

### 2. Signatures
- `EvaluatorAgent.execute(state, store) -> dict[str, Any]`
- `POST /api/evaluation/note`, `POST /api/evaluation/run/{thread_id}`
- `GET /api/evaluation/list`, `GET /api/evaluation/trend`

### 3. Contracts
- `degraded|failed` means `overall_score=null`, `decision=null`,
  `degraded=true`; include coverage and a retryable summary.
- `partial` may carry a normalized score only when copywriting and compliance
  are available and weighted coverage is at least `MIN_EVALUATION_COVERAGE`.
- Missing dimensions use `available=false, score=null`; visual/image-quality
  and no-niche audience/reach are explicitly unavailable for historical notes.
- List/KPI/pass-rate/trend aggregation skips degraded, failed, running and
  scoreless rows. Frontend treats `degraded=true` as scoreless even for legacy payloads.

### 4. Validation & Error Matrix
- LLM timeout (60s) → degraded/null, no publish-blocking approval.
- Evaluator exception/no result → API boundary converts to degraded/null.
- Missing required dimensions or coverage below threshold → partial/null.
- Malformed/legacy score without usable coverage → excluded from aggregates.

### 5. Good/Base/Bad Cases
- Good: UI renders `—` and retry for degraded; trend omits it.
- Base: sufficiently covered partial result shows score, coverage and threshold metadata.
- Bad: any timeout path returns `100/approved`, or a missing dimension is filled with 70.

### 6. Tests Required
- Assert timeout/model errors have null score/decision and `status=degraded`.
- Assert missing dimensions have `available=false`, no 70 fill, and coverage thresholding.
- Assert list/trend/KPI exclude degraded/failed/scoreless rows.

### 7. Wrong vs Correct
```python
# Wrong: this legacy fallback becomes a false pass in KPI/trend.
{"overall_score": 100, "decision": "approved", "degraded": True}

# Correct: degradation is explicit and non-consumable.
{"overall_score": None, "decision": None, "status": "degraded",
 "degraded": True, "coverage": {"weighted_ratio": 0.0}}
```

## Scenario: Risk-gated Creator Stats sync

Creator Center imports use explicit gates because every live CDP session is a
platform-risk event.

- The account freshness check runs before login preflight and before scheduled
  light/deep mode selection. A fresh snapshot returns a successful no-op and
  does not open a browser, start the batch cooldown, or consume the scheduled
  light-run cadence.
- Authentication cooldowns are account-scoped. A blocked active account must
  return `status="cooldown"` with `risk_code` and `retry_after_seconds`; it
  must not prevent a different account from syncing.
- Scheduled imports pass `prefer_light=None` and resolve the configured
  force-light policy only after eligibility checks. Failed scheduled attempts
  restore the prior light-run streak; only a real successful import starts the
  global post-sync cooldown.
- Manual `sync-all` passes `prefer_light=False` and may explicitly bypass the
  freshness window. Single-account sync honors freshness unless it is the
  explicit post-login refresh path.
- Numeric environment values are parsed defensively. Non-finite or malformed
  values fall back to finite safe defaults before they reach delay, probability,
  cap, or cooldown calculations.

Tests must cover fresh/empty/failed batches, account-scoped auth gates,
non-finite configuration, and the scheduler's finite-delay fallback. Browser
fetch failures return machine-readable `error_code` values and never persist a
partial bundle.

## Scenario: Creator Agent learning review conflicts

Learning review routes translate domain exceptions into typed API errors:

- a missing or cross-account signal is `CreatorLearningSignalNotFoundError`
  (`404`);
- a different disposition after a signal is already reviewed is
  `CreatorLearningSignalConflictError` (`409`);
- an approved review without both a complete model and `expected_revision` is a
  `ValidationError` (`400`);
- a stale model revision reuses `CreatorModelRevisionConflictError` (`409`).

The adapter must raise before committing when a revision or disposition check
fails. Routes must not catch these failures and return a successful envelope.

## Scenario: Creator Agent Evidence Graph lookup

Evidence Graph detail routes translate a missing or cross-account node into
`CreatorEvidenceNotFoundError` (`404`, code
`ERROR_CREATOR_EVIDENCE_NOT_FOUND`). List queries return an empty successful
envelope when filters match no Evidence; they must not reveal whether another
account owns a node.

## Scenario: Creator Agent Action Intent confirmation gate

Action planning rejects candidate targets that are not present in the
Decision Record's recommendations, and rejects candidate actions for
non-recommended decisions. `request_more_evidence` is the only capability that
may target an insufficient-evidence decision, and it must carry no candidates.
Resolution is side-effect free: `confirmed` authorizes only a future executor,
while `cancelled` permanently prevents execution. Missing or cross-account
intents are `CreatorActionNotFoundError` (`404`); changing the disposition of a
resolved intent is `CreatorActionConflictError` (`409`).

## Scenario: Creator Agent Decision Dataset query validation

The authenticated Decision Dataset route validates the account and optional
audience identifiers after trimming and before reading any snapshots. Blank
identifiers, malformed/version-unsupported cursors, and limits outside `1..100`
raise the typed `ValidationError` (`400`, `ERROR_VALIDATION`). Invalid cursors
must never be treated as a missing cursor, because that would silently restart
the caller at page one. Account ownership is checked before the repository
projection is read.

## Scenario: Creator Agent Action Execution Receipts

Execution routes preserve the confirmation boundary and map domain failures
into typed responses:

- missing or cross-account Action Intents are `CreatorActionNotFoundError`
  (`404`);
- pending or cancelled intents raise `CreatorActionExecutionNotAllowedError`
  (`409`, `ERROR_CREATOR_ACTION_EXECUTION_NOT_ALLOWED`) and do not create a
  receipt;
- a missing source Decision Record is `CreatorDecisionNotFoundError` (`404`);
- a missing receipt on the read route is
  `CreatorActionExecutionNotFoundError` (`404`), including foreign accounts;
- repeated execution returns the original immutable payload and is not treated
  as a conflict.

## Scenario: Context Compiler memory recall (P1b S2)

`backend.context.recall.recall_memory(store, account_id, queries, *, limit=5,
thread_id="", agent="", now=None, timeout=10.0)` returns one `RetrievalResult`
per requested namespace in request order. Namespace reads run concurrently.
All namespaces are validated before I/O; an unknown namespace raises
`UnknownMemoryNamespaceError`, including when the store is unavailable.
Blank account identifiers and nonpositive limits/timeouts fail before I/O.

| Storage outcome | Mode | Behavior |
| --- | --- | --- |
| Valid records | `hit` | Rank, deduplicate, retain account scope and provenance |
| Successful empty search | `empty` | No error |
| Missing store, timeout, provider failure | `degraded` | Error code/type, no false empty success |
| Invalid record among valid neighbors | `degraded` | Preserve valid neighbors |
| Cancellation | Exception | Propagate; never turn into degradation |

Rank is confidence times `0.8 * relevance + 0.2 * freshness`, where freshness
decays with age over a 30-day scale. Missing timestamps have zero freshness;
naive timestamps mean UTC. Equal ranks retain store order, and duplicate
canonical JSON bodies keep their best-ranked record. Original values remain
available for the transitional Agent adapter; `ContextItem` also carries
source, timestamp, confidence, account scope and estimated token cost.

Every result emits a best-effort `kind="context"` event keyed by thread,
with agent, namespace, mode, degraded flag, item count, error type/code and
timestamp. Queries, memory bodies and provider exception messages must not
enter these events. `BaseAgent._recall_memory` returns the `RetrievalResult`
itself (read `.items`; do not iterate the model). Graph callers must pass
thread_id/session_id.

Wrong: catch a search exception and return `[]` without a result/event.
Correct: return `RetrievalMode.DEGRADED` and emit the context event, while
allowing other namespaces to complete. Strategy notes remain a valid namespace
but are not automatically recalled into unrelated agents.

Required regressions: parallel barrier (no sleeps), partial success, empty
versus degraded, cancellation, timeout, account/thread isolation, UTC ranking,
deduplication, malformed records, event redaction and BaseAgent adapter wiring.
See `tests/unit/context/test_recall.py`.

## Scenario: Context Compiler prompt layers (P1b S3–S4)

Agent prompts go through `backend.context.prompts.prepare_prompt` and
`PreparedPrompt.messages`. `RunContext` is built inside `artifact_seam` after
hydration, stored in a ContextVar, and reset on success or failure. It is not
a checkpoint field.

### Signatures

- `require_niche(state) -> str` — blank/missing niche raises `ValueError`
  (`"niche is required"`). A historical note with
  `niche_context_available` false returns `未提供赛道（不可推断）` and must
  not invent `母婴`.
- `prepare_prompt(state, template, schema, *, memory="", variables=None, budget=32768) -> PreparedPrompt`
- `PreparedPrompt.messages(task) -> [SystemMessage, HumanMessage]`
  — system message is L0–L2 only; human message is L3–L5 plus the task hint.
- YAML `context` (`TemplateContext`): `version` must be `1`; `variables` maps
  placeholder names to a `PromptLayer`; unknown keys fail at load.

### Contracts

| Layer | Role | Trim |
| --- | --- | --- |
| L0 system | Policy / identity text with no placeholder | Never |
| L1 tool schema | Empty until Tool Runtime | Never |
| L2 account | Niche and other account facts | Never |
| L3 task | User template and this step's task hint | Never |
| L4 memory | Recall and `{memory_context}` | After L5 |
| L5 observation | Ripple, live data, evaluator weights | First |

Only declared `{snake_case}` placeholders are substituted. Braces inside
inserted memory or JSON examples are literal. A segment that mixes layers
fails. L0–L2 for the same template and niche are byte-stable across task,
memory, and observation changes. Token estimate is deterministic
(CJK = 1, ASCII ≈ 1/4, round up). Budget below the required L0–L3 cost
raises `ValueError` (`Required context exceeds`).

### Wrong vs Correct

Wrong: `state.get("niche", "母婴")` or `template.replace("{account_niche}", ...)`.
Correct: `require_niche(state)` and `_prompt_messages(state, prepared, task)`.

Required regressions: every prompt YAML keeps the same token multiset as
legacy substitution, L0–L2 stability, budget order, niche fail-fast,
historical unknown niche, schema fail-closed, and per-node RunContext
isolation. See `tests/unit/context/test_prompts.py`.
