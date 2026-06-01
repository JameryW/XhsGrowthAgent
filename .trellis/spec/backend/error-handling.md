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

### Stale Error Handling

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

## Tests Required

- `test_cancel_cancels_background_task`: cancel_workflow calls task.cancel()
- `test_pause_cancels_background_task`: pause_workflow calls task.cancel()
- `test_check_cancelled_raises`: _check_cancelled raises WorkflowCancelledError when phase=cancelled
- `test_agent_error_propagates`: AgentError is not swallowed, graph stops
- `test_error_with_next_nodes_returns_running`: error + next non-empty + phase≠ERROR → RUNNING
- `test_error_with_no_next_nodes_returns_error`: error + next empty → ERROR
- `test_error_phase_returns_error`: phase=ERROR → ERROR
