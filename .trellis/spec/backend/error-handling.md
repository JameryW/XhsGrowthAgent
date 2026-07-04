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
# backend/graph/error_handling.py
RETRY_POLICIES: dict[str, RetryPolicy] = {
    "scouting": RetryPolicy(max_attempts=3),
    "writing": RetryPolicy(max_attempts=2),
    ...
}

def get_retry_policy(node_name: str) -> RetryPolicy | None:
    """Used in builder.add_node(..., retry=...)"""
```

## Contracts

### BaseAgent Error Behavior

- `BaseAgent.__call__` raises `AgentError` on failure (does NOT swallow)
- LangGraph's `RetryPolicy` catches and retries based on exception type
- After max retries, `AgentError` propagates — graph does NOT continue through fixed edges
- Successful execution clears stale `error` field from state (`result["error"] = None`)

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
