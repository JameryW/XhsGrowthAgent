# Error Handling & Retry

## Scope / Trigger

- Any code that raises or catches exceptions in agent nodes
- Any code that configures LangGraph retry policies
- Any code that cancels or pauses running workflows

## Signatures

### Exception Hierarchy

```python
class AgentError(Exception):
    """Raised by BaseAgent when execution fails after retries."""
    agent_name: str
    task_type: str

class WorkflowCancelledError(Exception):
    """Raised by _check_cancelled when workflow is cancelled/paused."""
    thread_id: str
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
- Successful execution clears stale `error` field from state

### Cancel/Pause Guard

- `_check_cancelled(state)` in `backend/agents/nodes/_base.py` raises `WorkflowCancelledError` at node entry
- `cancel_workflow` cancels the background `asyncio.Task` via `task.cancel()`
- `pause_workflow` also cancels the background task (same as cancel)
- Resume re-invokes the graph from the last checkpoint

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

## Tests Required

- `test_cancel_cancels_background_task`: cancel_workflow calls task.cancel()
- `test_pause_cancels_background_task`: pause_workflow calls task.cancel()
- `test_check_cancelled_raises`: _check_cancelled raises WorkflowCancelledError when phase=cancelled
- `test_agent_error_propagates`: AgentError is not swallowed, graph stops
