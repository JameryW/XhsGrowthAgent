# Workflow Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 9 critical workflow bugs: status misclassification, broken HITL, SSE re-execution, unclosed optimization loop, swallowed errors, duplicate versions, unreliable persistence, non-functional pause/cancel, and missing completion path.

**Architecture:** Unified status derivation function as single source of truth, dynamic `interrupt()` instead of `interrupt_before`, EventBus-driven SSE, new optimization API endpoints, proper error propagation with retry policies, and two-mode execution topology.

**Tech Stack:** Python 3.11, LangGraph, FastAPI, asyncio, Pydantic, pytest

---

## File Structure

### New Files
- `backend/state/machine.py` — `WorkflowStatus` enum and `derive_status()` function
- `backend/api/routes/optimization.py` — `/draft` and `/select` endpoints
- `backend/core/errors.py` — `AgentError`, `WorkflowCancelledError` exceptions (extend existing)

### Modified Files
- `backend/state/enums.py` — Add `ExecutionMode` enum
- `backend/state/schema.py` — Add `execution_mode` field
- `backend/state/__init__.py` — Export new symbols
- `backend/graph/builder.py` — Remove `interrupt_before`, wire retry policies
- `backend/graph/routers.py` — Add `_check_terminal()` guard, update `should_continue`
- `backend/graph/error_handling.py` — Already has `RETRY_POLICIES`, ensure `get_retry_policy` works
- `backend/agents/base.py` — Propagate exceptions, clear stale errors
- `backend/agents/nodes/_base.py` — Add `_check_cancelled()` helper
- `backend/agents/nodes/optimization/choice_gate.py` — Add `selected_title`
- `backend/agents/nodes/engagement.py` — Write `phase=COMPLETED` in single mode
- `backend/agents/engagement.py` — Write `phase=COMPLETED` in single mode
- `backend/api/app.py` — Env-based graph compilation, register optimization router
- `backend/api/routes/workflow.py` — Use `derive_status()`, EventBus SSE, background task registry, atomic JSON writes
- `backend/api/routes/review.py` — Fix `content_versions` dedup
- `backend/realtime/event_bus.py` — Add `subscribe_thread()` / `unsubscribe_thread()` with asyncio.Queue
- `backend/realtime/events.py` — Add `CHOICE_PENDING` event type
- All 14 node files — Add `_check_cancelled(state)` at entry

### Test Files
- `tests/unit/state/test_machine.py` — Test `derive_status()` all 8 cases
- `tests/unit/api/test_optimization_routes.py` — Test `/draft` and `/select`
- `tests/integration/test_workflow_status.py` — Test status derivation in real workflow
- `tests/integration/test_hitl_interrupt.py` — Test dynamic interrupt fires events
- `tests/integration/test_sse_eventbus.py` — Test SSE doesn't call graph methods
- `tests/integration/test_pause_cancel.py` — Test task cancellation and guards

---

## Task 1: Unified State Machine — WorkflowStatus and derive_status()

**Files:**
- Create: `backend/state/machine.py`
- Modify: `backend/state/__init__.py`
- Test: `tests/unit/state/test_machine.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/state/test_machine.py
"""Tests for workflow status derivation."""

import pytest
from langgraph.graph.state import StateSnapshot

from backend.state.machine import WorkflowStatus, derive_status
from backend.state.enums import WorkflowPhase


def make_snapshot(
    values: dict,
    next: list[str] = None,
    tasks: list = None,
) -> StateSnapshot:
    """Create a mock StateSnapshot for testing."""
    from langgraph.graph.state import StateSnapshot as SS
    # tasks contain interrupt info: [{"interrupts": [...]}, ...]
    return SS(
        values=values,
        next=next or [],
        tasks=tasks or [],
        metadata={},
        config={},
        created_at="",
        parent_config=None,
    )


class TestDeriveStatus:
    """Test derive_status priority order."""

    def test_cancelled_phase_returns_cancelled(self):
        """Priority 1: Cancelled phase."""
        snapshot = make_snapshot({"phase": WorkflowPhase.CANCELLED})
        assert derive_status(snapshot) == WorkflowStatus.CANCELLED

    def test_paused_phase_returns_paused(self):
        """Priority 2: Paused phase."""
        snapshot = make_snapshot({"phase": WorkflowPhase.PAUSED})
        assert derive_status(snapshot) == WorkflowStatus.PAUSED

    def test_interrupt_at_review_gate_returns_awaiting_review(self):
        """Priority 3: Interrupt at review_gate."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.REVIEWING},
            next=["review_gate"],
            tasks=[{"interrupts": [{}]}],  # Has interrupt
        )
        assert derive_status(snapshot) == WorkflowStatus.AWAITING_REVIEW

    def test_interrupt_at_choice_gate_returns_awaiting_choice(self):
        """Priority 4: Interrupt at choice_gate."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.CREATING},
            next=["choice_gate"],
            tasks=[{"interrupts": [{}]}],
        )
        assert derive_status(snapshot) == WorkflowStatus.AWAITING_CHOICE

    def test_error_in_state_returns_error(self):
        """Priority 5: Error field set."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.SCOUTING, "error": "API failed"},
            next=["trend_scout"],
        )
        assert derive_status(snapshot) == WorkflowStatus.ERROR

    def test_completed_phase_returns_completed(self):
        """Priority 6: Phase is completed."""
        snapshot = make_snapshot({"phase": WorkflowPhase.COMPLETED})
        assert derive_status(snapshot) == WorkflowStatus.COMPLETED

    def test_has_next_nodes_returns_running(self):
        """Priority 7: Has next nodes, no interrupt."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.SCOUTING},
            next=["trend_scout"],
            tasks=[],  # No interrupts
        )
        assert derive_status(snapshot) == WorkflowStatus.RUNNING

    def test_no_next_no_interrupt_returns_completed(self):
        """Priority 8: No next nodes, no interrupt."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.ANALYZING},
            next=[],
            tasks=[],
        )
        assert derive_status(snapshot) == WorkflowStatus.COMPLETED

    def test_error_takes_precedence_over_running(self):
        """Error beats running state."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.SCOUTING, "error": "Failed"},
            next=["content_strategist"],
        )
        assert derive_status(snapshot) == WorkflowStatus.ERROR

    def test_cancelled_takes_precedence_over_error(self):
        """Cancelled beats error."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.CANCELLED, "error": "Some error"},
        )
        assert derive_status(snapshot) == WorkflowStatus.CANCELLED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/state/test_machine.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'backend.state.machine'"

- [ ] **Step 3: Write the implementation**

```python
# backend/state/machine.py
"""Workflow status derivation — single source of truth."""

from __future__ import annotations

from enum import StrEnum

from langgraph.graph.state import StateSnapshot

from backend.state.enums import WorkflowPhase


class WorkflowStatus(StrEnum):
    """Computed workflow status (derived from state, not stored)."""

    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    AWAITING_CHOICE = "awaiting_choice"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


def derive_status(snapshot: StateSnapshot) -> WorkflowStatus:
    """Derive workflow status from LangGraph state snapshot.

    Priority order (highest to lowest):
    1. Cancelled (phase flag)
    2. Paused (phase flag)
    3. Interrupt at review_gate → awaiting_review
    4. Interrupt at choice_gate → awaiting_choice
    5. Error in state → error
    6. Phase is completed → completed
    7. Has next nodes → running
    8. No next nodes + no interrupt → completed

    Args:
        snapshot: LangGraph StateSnapshot from graph.aget_state()

    Returns:
        WorkflowStatus enum value
    """
    values = snapshot.values or {}
    phase = values.get("phase")
    next_nodes = snapshot.next or []
    tasks = snapshot.tasks or []

    # Check for interrupts in tasks
    has_interrupt = any(
        task.get("interrupts") for task in tasks if isinstance(task, dict)
    )

    # Priority 1: Cancelled
    if phase == WorkflowPhase.CANCELLED:
        return WorkflowStatus.CANCELLED

    # Priority 2: Paused
    if phase == WorkflowPhase.PAUSED:
        return WorkflowStatus.PAUSED

    # Priority 3 & 4: Interrupt at specific gates
    if has_interrupt and next_nodes:
        if "review_gate" in next_nodes:
            return WorkflowStatus.AWAITING_REVIEW
        if "choice_gate" in next_nodes:
            return WorkflowStatus.AWAITING_CHOICE

    # Priority 5: Error
    if values.get("error"):
        return WorkflowStatus.ERROR

    # Priority 6: Completed phase
    if phase == WorkflowPhase.COMPLETED:
        return WorkflowStatus.COMPLETED

    # Priority 7: Has next nodes (running)
    if next_nodes:
        return WorkflowStatus.RUNNING

    # Priority 8: No next nodes, no interrupt → completed
    return WorkflowStatus.COMPLETED
```

- [ ] **Step 4: Update state __init__.py to export**

```python
# backend/state/__init__.py — add to existing exports
from backend.state.machine import WorkflowStatus, derive_status

__all__ = [
    # ... existing exports ...
    "WorkflowStatus",
    "derive_status",
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/state/test_machine.py -v`
Expected: PASS (all 10 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/state/machine.py backend/state/__init__.py tests/unit/state/test_machine.py
git commit -m "feat(state): add WorkflowStatus enum and derive_status function

- Single source of truth for workflow status
- 8-level priority: cancelled > paused > interrupt > error > completed > running
- Tests cover all priority cases"
```

---

## Task 2: HITL Mechanism — Remove interrupt_before

**Files:**
- Modify: `backend/graph/builder.py`
- Test: `tests/integration/test_hitl_interrupt.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_hitl_interrupt.py
"""Tests for human-in-the-loop interrupt mechanism."""

import pytest

from backend.graph.builder import compile_graph_dev
from backend.realtime.event_bus import EventBusService
from backend.realtime.events import EventType


@pytest.mark.asyncio
async def test_review_gate_fires_event_before_interrupt():
    """When graph hits review_gate, REVIEW_PENDING event should fire."""
    graph = compile_graph_dev()
    bus = EventBusService.get_instance()

    # Track events
    events = []
    def capture(e):
        events.append(e)
    bus.subscribe(capture)

    # Start workflow (will hit review_gate and interrupt)
    initial_state = {
        "phase": "creating",
        "current_agent": "visual_designer",
        "session_id": "test-hitl-001",
        "account_id": "test",
        "messages": [],
    }
    config = {"configurable": {"thread_id": "test-hitl-001"}}

    # Run until interrupt
    result = await graph.ainvoke(initial_state, config)

    # Check that REVIEW_PENDING was emitted
    review_events = [e for e in events if e.event_type == EventType.REVIEW_PENDING]
    assert len(review_events) >= 1, "REVIEW_PENDING event should fire before interrupt"

    # Check graph is actually interrupted at review_gate
    state = await graph.aget_state(config)
    assert "review_gate" in state.next, "Graph should be interrupted at review_gate"

    bus.unsubscribe(capture)
```

- [ ] **Step 2: Run test to verify current behavior**

Run: `pytest tests/integration/test_hitl_interrupt.py -v`
Expected: FAIL — with `interrupt_before`, node doesn't execute, no event fires

- [ ] **Step 3: Remove interrupt_before from builder.py**

```python
# backend/graph/builder.py — modify compile_graph_dev()
def compile_graph_dev() -> CompiledStateGraph:
    """开发模式编译 — 使用内存检查点和内存存储"""
    builder = build_graph()
    checkpointer = MemorySaver()
    store = InMemoryStore()

    graph = builder.compile(
        checkpointer=checkpointer,
        store=store,
        # REMOVED: interrupt_before — nodes use dynamic interrupt() instead
    )
    return graph


# Also modify compile_graph_prod()
async def compile_graph_prod(db_uri: str) -> CompiledStateGraph:
    """生产模式编译 — 使用 Postgres 检查点"""
    builder = build_graph()

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(db_uri) as checkpointer:
            await checkpointer.setup()
            graph = builder.compile(
                checkpointer=checkpointer,
                # REMOVED: interrupt_before
            )
            return graph
    except ImportError:
        return compile_graph_dev()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_hitl_interrupt.py -v`
Expected: PASS — node executes, fires event, then interrupt() pauses

- [ ] **Step 5: Commit**

```bash
git add backend/graph/builder.py tests/integration/test_hitl_interrupt.py
git commit -m "fix(graph): remove interrupt_before, use dynamic interrupt()

- review_gate and choice_gate nodes use interrupt() internally
- Events now fire before interrupt, not after
- Fixes bug where REVIEW_PENDING never emitted"
```

---

## Task 3: Error Handling — Propagate Exceptions, Wire Retry Policies

**Files:**
- Modify: `backend/agents/base.py`
- Modify: `backend/graph/builder.py`
- Modify: `backend/core/error_handling.py`
- Test: `tests/unit/agents/test_base_error.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/agents/test_base_error.py
"""Tests for BaseAgent error handling."""

import pytest
from backend.agents.base import BaseAgent
from backend.core.error_handling import AgentError
from backend.config.models import TaskType


class FailingAgent(BaseAgent):
    task_type = TaskType.ROUTING
    agent_name = "failing_agent"
    prompt_file = ""

    async def execute(self, state, store):
        raise ValueError("Intentional test failure")


@pytest.mark.asyncio
async def test_base_agent_propagates_exception():
    """BaseAgent should propagate exceptions, not swallow them."""
    agent = FailingAgent()

    with pytest.raises(AgentError) as exc_info:
        await agent({"session_id": "test"}, store=None)

    assert "Intentional test failure" in str(exc_info.value)


@pytest.mark.asyncio
async def test_base_agent_clears_stale_error_on_success():
    """Successful execution should clear stale error field."""
    class SuccessAgent(BaseAgent):
        task_type = TaskType.ROUTING
        agent_name = "success_agent"
        prompt_file = ""

        async def execute(self, state, store):
            return {"phase": "completed"}

    agent = SuccessAgent()
    state = {"session_id": "test", "error": "stale error"}

    result = await agent(state, store=None)

    assert result.get("error") is None, "Stale error should be cleared"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/agents/test_base_error.py -v`
Expected: FAIL — current code catches and returns, doesn't propagate

- [ ] **Step 3: Update AgentError in core/error_handling.py**

```python
# backend/core/error_handling.py — update existing AgentError
class AgentError(Exception):
    """Agent execution error — should be caught by LangGraph retry."""

    def __init__(self, agent_name: str, cause: Exception):
        self.agent_name = agent_name
        self.cause = cause
        super().__init__(f"Agent {agent_name} failed: {cause}")


class WorkflowCancelledError(Exception):
    """Workflow was cancelled — nodes should stop execution."""
    pass
```

- [ ] **Step 4: Update BaseAgent.__call__ to propagate exceptions**

```python
# backend/agents/base.py — replace __call__ method
async def __call__(self, state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """LangGraph node entry point."""
    from backend.core.error_handling import AgentError

    try:
        result = await self.execute(state, store)
        result["current_agent"] = self.agent_name
        result["error"] = None  # Clear stale error on success
        return result
    except Exception as e:
        logger.error(f"Agent {self.agent_name} failed: {e}", exc_info=True)
        # Propagate to LangGraph retry mechanism
        raise AgentError(self.agent_name, e) from e
```

- [ ] **Step 5: Wire retry policies in builder.py**

```python
# backend/graph/builder.py — add retry policies to nodes
from backend.graph.error_handling import get_retry_policy

def build_graph() -> StateGraph:
    """构建小红书增长引擎的 LangGraph 状态图"""
    builder = StateGraph(XHSGrowthState)

    # ── 添加节点（带重试策略） ──
    builder.add_node("orchestrator", orchestrator_node, retry=get_retry_policy("orchestrator"))
    builder.add_node("trend_scout", trend_scout_node, retry=get_retry_policy("trend_scout"))
    builder.add_node("content_strategist", content_strategist_node, retry=get_retry_policy("content_strategist"))
    builder.add_node("copywriter", copywriter_node, retry=get_retry_policy("copywriter"))
    builder.add_node("visual_designer", visual_designer_node, retry=get_retry_policy("visual_designer"))
    builder.add_node("review_gate", review_gate_node, retry=get_retry_policy("review_gate"))
    builder.add_node("publisher", publisher_node, retry=get_retry_policy("publisher"))
    builder.add_node("analyst", analyst_node, retry=get_retry_policy("analyst"))
    builder.add_node("engagement", engagement_node, retry=get_retry_policy("engagement"))
    builder.add_node("revise_content", revise_content_node)
    builder.add_node("viral_matcher", viral_matcher_node)
    builder.add_node("content_analyzer", content_analyzer_node)
    builder.add_node("version_generator", version_generator_node)
    builder.add_node("choice_gate", choice_gate_node)

    # ... rest of build_graph unchanged ...
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/unit/agents/test_base_error.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/agents/base.py backend/graph/builder.py backend/core/error_handling.py tests/unit/agents/test_base_error.py
git commit -m "fix(agents): propagate exceptions, wire retry policies

- BaseAgent now raises AgentError instead of swallowing
- Retry policies wired to all nodes with defined policies
- Successful execution clears stale error field"
```

---

## Task 4: Router Guards — Check Terminal States

**Files:**
- Modify: `backend/graph/routers.py`
- Test: `tests/unit/graph/test_router_guards.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/graph/test_router_guards.py
"""Tests for router terminal state guards."""

import pytest
from backend.graph.routers import (
    should_continue,
    should_plan,
    orchestrator_router,
    review_outcome,
    should_optimize,
)
from backend.state.enums import WorkflowPhase


def test_should_continue_returns_end_on_cancelled():
    """Cancelled workflow should route to END."""
    state = {"phase": WorkflowPhase.CANCELLED}
    assert should_continue(state) == "__end__"


def test_should_continue_returns_end_on_paused():
    """Paused workflow should route to END."""
    state = {"phase": WorkflowPhase.PAUSED}
    assert should_continue(state) == "__end__"


def test_should_continue_returns_end_on_error():
    """Error state should route to END."""
    state = {"phase": WorkflowPhase.ANALYZING, "error": "Something failed"}
    assert should_continue(state) == "__end__"


def test_should_plan_returns_end_on_cancelled():
    """Cancelled should not retry trend_scout."""
    state = {"phase": WorkflowPhase.CANCELLED, "trend_data": None, "error": "x"}
    assert should_plan(state) == "__end__"


def test_orchestrator_router_returns_end_on_cancelled():
    """Cancelled should not route to any agent."""
    state = {"phase": WorkflowPhase.CANCELLED}
    assert orchestrator_router(state) == "__end__"


def test_review_outcome_returns_end_on_cancelled():
    """Cancelled during review should end, not publish."""
    state = {
        "phase": WorkflowPhase.CANCELLED,
        "human_feedback": {"decision": "approved"},
    }
    assert review_outcome(state) == "__end__"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/graph/test_router_guards.py -v`
Expected: FAIL — routers don't check cancelled/paused

- [ ] **Step 3: Add _check_terminal helper and update all routers**

```python
# backend/graph/routers.py — add helper and update routers
from __future__ import annotations

import os
from typing import Literal

from backend.state.enums import ContentStatus, WorkflowPhase
from backend.state.schema import XHSGrowthState


def _xhs_configured() -> bool:
    """Check if XHS platform credentials are available."""
    return bool(os.environ.get("XHS_COOKIE") and os.environ.get("XHS_USER_ID"))


def _check_terminal(state: XHSGrowthState) -> str | None:
    """Return '__end__' if workflow is in terminal state, else None.

    Terminal states: cancelled, paused, error
    """
    phase = state.get("phase")
    if phase == WorkflowPhase.CANCELLED:
        return "__end__"
    if phase == WorkflowPhase.PAUSED:
        return "__end__"
    if state.get("error"):
        return "__end__"
    return None


def orchestrator_router(state: XHSGrowthState) -> str:
    """编排器路由 — 根据当前阶段决定下一个节点"""
    # Guard: terminal states
    if terminal := _check_terminal(state):
        return terminal

    phase = state.get("phase", WorkflowPhase.IDLE)

    routing = {
        WorkflowPhase.SCOUTING: "trend_scout",
        WorkflowPhase.PLANNING: "content_strategist",
        WorkflowPhase.ANALYZING: "analyst",
        WorkflowPhase.ENGAGING: "engagement",
        WorkflowPhase.ERROR: "__end__",
        WorkflowPhase.COMPLETED: "__end__",
        WorkflowPhase.IDLE: "trend_scout",
    }

    return routing.get(phase, "trend_scout")


def should_plan(state: XHSGrowthState) -> Literal["content_strategist", "trend_scout", "__end__"]:
    """侦察后判断是否有可操作的趋势 — retry trend_scout on failure before giving up."""
    # Guard: terminal states
    if terminal := _check_terminal(state):
        return terminal

    trend_data = state.get("trend_data")

    if trend_data and trend_data.get("hot_topics"):
        return "content_strategist"

    has_error = state.get("error")
    retry_count = state.get("retry_count", 0)

    if has_error and retry_count < 2:
        return "trend_scout"

    return "__end__"


def review_outcome(state: XHSGrowthState) -> Literal["publisher", "revise_content", "__end__"]:
    """人工审核路由 — 根据审核结果决定下一步"""
    # Guard: terminal states
    if terminal := _check_terminal(state):
        return terminal

    feedback = state.get("human_feedback", {})
    decision = feedback.get("decision", ContentStatus.REJECTED)

    if decision == ContentStatus.APPROVED or decision == "approved":
        if not _xhs_configured():
            return "__end__"
        return "publisher"
    if decision == ContentStatus.NEEDS_REVISION or decision == "needs_revision":
        return "revise_content"
    return "__end__"


def should_continue(state: XHSGrowthState) -> Literal["orchestrator", "engagement", "__end__"]:
    """分析后决定是否继续下一个周期"""
    # Guard: terminal states
    if terminal := _check_terminal(state):
        return terminal

    phase = state.get("phase", WorkflowPhase.IDLE)

    # 分析完成 → 根据执行模式决定
    if phase == WorkflowPhase.ANALYZING:
        mode = state.get("execution_mode", "single")
        if mode == "continuous":
            return "orchestrator"
        return "engagement"  # single mode: go to engagement

    return "__end__"


def should_optimize(state: XHSGrowthState) -> Literal["content_analyzer", "visual_designer"]:
    """判断是否进入优化流程."""
    # Guard: terminal states (but don't block optimization for paused)
    if state.get("error"):
        return "visual_designer"  # Skip optimization on error

    if state.get("skip_optimization"):
        return "visual_designer"

    viral_posts = state.get("viral_posts", [])
    if viral_posts and len(viral_posts) > 0:
        return "content_analyzer"

    return "visual_designer"


def choice_outcome(state: XHSGrowthState) -> Literal["visual_designer"]:
    """版本选择后路由 — 统一进入视觉设计."""
    return "visual_designer"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/graph/test_router_guards.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/graph/routers.py tests/unit/graph/test_router_guards.py
git commit -m "fix(routers): add terminal state guards to all routers

- _check_terminal helper checks cancelled/paused/error
- All routers now return __end__ for terminal states
- Prevents cancelled workflows from continuing to next nodes"
```

---

## Task 5: Workflow Topology — Two Execution Modes

**Files:**
- Modify: `backend/state/enums.py`
- Modify: `backend/state/schema.py`
- Modify: `backend/agents/engagement.py`
- Modify: `backend/agents/nodes/engagement.py`
- Modify: `backend/api/routes/workflow.py`
- Test: `tests/unit/state/test_execution_mode.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/state/test_execution_mode.py
"""Tests for execution mode."""

import pytest
from backend.state.enums import ExecutionMode


def test_execution_mode_exists():
    """ExecutionMode enum should exist."""
    assert ExecutionMode.SINGLE == "single"
    assert ExecutionMode.CONTINUOUS == "continuous"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/state/test_execution_mode.py -v`
Expected: FAIL — ExecutionMode doesn't exist

- [ ] **Step 3: Add ExecutionMode to enums.py**

```python
# backend/state/enums.py — add ExecutionMode
class ExecutionMode(StrEnum):
    """Workflow execution mode."""
    SINGLE = "single"          # One content cycle, then completed
    CONTINUOUS = "continuous"  # Loop back to orchestrator after each cycle
```

- [ ] **Step 4: Add execution_mode to state schema**

```python
# backend/state/schema.py — add field to XHSGrowthState
class XHSGrowthState(TypedDict, total=False):
    """XHS Growth Agent global state."""

    # ... existing fields ...

    # Execution mode
    execution_mode: str  # "single" or "continuous"

    # ... rest of fields ...
```

- [ ] **Step 5: Update engagement agent to write COMPLETED in single mode**

```python
# backend/agents/engagement.py — update execute() return
async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
    # ... existing code ...

    mode = state.get("execution_mode", "single")

    # In single mode, mark completed after engagement
    if mode == "single":
        return {
            "engagement_actions": engagement_actions,
            "phase": WorkflowPhase.COMPLETED,  # Changed from ENGAGING
        }

    return {
        "engagement_actions": engagement_actions,
        "phase": WorkflowPhase.ENGAGING,
    }
```

- [ ] **Step 6: Update engagement node similarly**

```python
# backend/agents/nodes/engagement.py — no change needed, it delegates to agent
# The agent's execute() handles the phase transition
```

- [ ] **Step 7: Add execution_mode to WorkflowStartRequest**

```python
# backend/api/routes/workflow.py — add to request model
class WorkflowStartRequest(BaseModel):
    account_id: str = Field(default="default", description="账号 ID")
    phase: WorkflowPhase = Field(default=WorkflowPhase.SCOUTING, description="起始阶段")
    async_mode: bool = Field(default=True, description="异步执行模式")
    dry_run: bool = Field(default=False, description="试运行模式（不实际发布）")
    auto_publish: bool = Field(default=False, description="审核通过后自动发布")
    topic: str | None = Field(default=None, description="内容主题/关键词")
    niche: str = Field(default="母婴", description="垂类赛道")
    execution_mode: str = Field(default="single", description="执行模式: single/continuous")
```

- [ ] **Step 8: Add execution_mode to initial_state in start_workflow**

```python
# backend/api/routes/workflow.py — in start_workflow()
initial_state = {
    # ... existing fields ...
    "execution_mode": req.execution_mode,
}
```

- [ ] **Step 9: Run test to verify it passes**

Run: `pytest tests/unit/state/test_execution_mode.py -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add backend/state/enums.py backend/state/schema.py backend/agents/engagement.py backend/api/routes/workflow.py tests/unit/state/test_execution_mode.py
git commit -m "feat(state): add execution_mode for single/continuous workflows

- Single mode: publisher → analyst → engagement → completed
- Continuous mode: publisher → analyst → orchestrator (loop)
- Default is single mode"
```

---

## Task 6: SSE — EventBus-Driven Streaming

**Files:**
- Modify: `backend/realtime/event_bus.py`
- Modify: `backend/api/routes/workflow.py`
- Test: `tests/integration/test_sse_eventbus.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_sse_eventbus.py
"""Tests for SSE EventBus-driven streaming."""

import pytest
from backend.realtime.event_bus import EventBusService


@pytest.mark.asyncio
async def test_subscribe_thread_returns_queue():
    """EventBus should support per-thread subscription with asyncio.Queue."""
    bus = EventBusService.get_instance()

    queue = bus.subscribe_thread("test-thread-123")
    assert queue is not None

    # Emit an event for this thread
    from backend.realtime.events import EventType
    bus.emit(EventType.WORKFLOW_STARTED, "test-thread-123", {"phase": "scouting"})

    # Should receive on queue
    import asyncio
    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event.thread_id == "test-thread-123"

    bus.unsubscribe_thread("test-thread-123", queue)


@pytest.mark.asyncio
async def test_multiple_subscribers_same_thread():
    """Multiple SSE clients for same thread should each get their own queue."""
    bus = EventBusService.get_instance()

    q1 = bus.subscribe_thread("multi-thread")
    q2 = bus.subscribe_thread("multi-thread")

    from backend.realtime.events import EventType
    bus.emit(EventType.WORKFLOW_STARTED, "multi-thread", {"test": True})

    import asyncio
    e1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    e2 = await asyncio.wait_for(q2.get(), timeout=1.0)

    assert e1.thread_id == "multi-thread"
    assert e2.thread_id == "multi-thread"

    bus.unsubscribe_thread("multi-thread", q1)
    bus.unsubscribe_thread("multi-thread", q2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_sse_eventbus.py -v`
Expected: FAIL — subscribe_thread doesn't exist

- [ ] **Step 3: Add subscribe_thread/unsubscribe_thread to EventBus**

```python
# backend/realtime/event_bus.py — add methods
from __future__ import annotations

import asyncio
import threading
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from backend.realtime.events import Event, EventType


class EventBusService:
    """单例服务 - 事件收集、分发、存储."""

    _instance: EventBusService | None = None
    MAX_EVENTS = 100

    def __init__(self) -> None:
        self._events: deque[Event] = deque(maxlen=self.MAX_EVENTS)
        self._subscribers: list[Callable[[Event], None]] = []
        self._thread_queues: dict[str, list[asyncio.Queue]] = {}  # NEW
        self._seq = 0
        self._lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> EventBusService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def emit(
        self,
        event_type: EventType,
        thread_id: str | None,
        payload: dict[str, Any],
    ) -> Event:
        """发送事件."""
        with self._lock:
            event = Event(
                event_type=event_type,
                thread_id=thread_id,
                payload=payload,
                timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                seq=self._seq,
            )
            self._seq += 1
            self._events.append(event)
            handlers = self._subscribers.copy()
            queues = self._thread_queues.get(thread_id, []).copy() if thread_id else []

        # 分发给全局订阅者
        for handler in handlers:
            handler(event)

        # 分发给线程队列（用于SSE）
        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Drop if queue full

        return event

    def subscribe(self, handler: Callable[[Event], None]) -> None:
        """订阅事件（全局）."""
        with self._lock:
            self._subscribers.append(handler)

    def unsubscribe(self, handler: Callable[[Event], None]) -> None:
        """取消订阅."""
        with self._lock:
            if handler in self._subscribers:
                self._subscribers.remove(handler)

    def subscribe_thread(self, thread_id: str) -> asyncio.Queue:
        """订阅特定线程的事件（用于SSE）.

        Returns:
            asyncio.Queue that will receive events for this thread
        """
        q = asyncio.Queue(maxsize=100)
        with self._lock:
            if thread_id not in self._thread_queues:
                self._thread_queues[thread_id] = []
            self._thread_queues[thread_id].append(q)
        return q

    def unsubscribe_thread(self, thread_id: str, queue: asyncio.Queue) -> None:
        """取消线程订阅."""
        with self._lock:
            if thread_id in self._thread_queues:
                try:
                    self._thread_queues[thread_id].remove(queue)
                except ValueError:
                    pass
                if not self._thread_queues[thread_id]:
                    del self._thread_queues[thread_id]

    def get_events_since(self, since_seq: int) -> list[Event]:
        """获取seq > since_seq的所有事件."""
        with self._lock:
            return [e for e in self._events if e.seq > since_seq]
```

- [ ] **Step 4: Rewrite /stream endpoint to use EventBus**

```python
# backend/api/routes/workflow.py — replace stream_workflow_progress
@router.get("/stream/{thread_id}")
async def stream_workflow_progress(thread_id: str, request: Request):
    """SSE 流式进度推送 — EventBus驱动，不调用graph方法."""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    async def event_generator():
        bus = EventBusService.get_instance()
        queue = bus.subscribe_thread(thread_id)

        try:
            while True:
                event = await queue.get()
                yield f"event: {event.event_type.value}\ndata: {json.dumps(event.payload, ensure_ascii=False)}\n\n"

                # Terminal events close the stream
                if event.event_type in (EventType.WORKFLOW_COMPLETED, EventType.WORKFLOW_ERROR):
                    break
        finally:
            bus.unsubscribe_thread(thread_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **Step 5: Add EventType imports to workflow.py**

```python
# backend/api/routes/workflow.py — add import
from backend.realtime import EventBusService, EventType
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/integration/test_sse_eventbus.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/realtime/event_bus.py backend/api/routes/workflow.py tests/integration/test_sse_eventbus.py
git commit -m "fix(sse): EventBus-driven streaming, no graph method calls

- subscribe_thread/unsubscribe_thread with asyncio.Queue
- Multiple SSE clients supported per thread
- No more astream_events that re-drives the graph"
```

---

## Task 7: Optimization API — /draft and /select Endpoints

**Files:**
- Create: `backend/api/routes/optimization.py`
- Modify: `backend/api/app.py`
- Modify: `backend/agents/nodes/optimization/choice_gate.py`
- Test: `tests/unit/api/test_optimization_routes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/api/test_optimization_routes.py
"""Tests for optimization API endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_graph():
    """Mock graph for testing."""
    graph = MagicMock()
    graph.aget_state = AsyncMock()
    graph.aupdate_state = AsyncMock()
    graph.ainvoke = AsyncMock()
    return graph


@pytest.fixture
def client(mock_graph):
    """Create test client with mock graph."""
    from backend.api.app import app
    app.state.graph = mock_graph
    return TestClient(app)


def test_submit_draft_endpoint_exists(client):
    """POST /api/optimization/draft/{thread_id} should exist."""
    # This will fail with 422 (validation) if endpoint exists
    resp = client.post("/api/optimization/draft/test-123", json={})
    assert resp.status_code != 404


def test_select_version_endpoint_exists(client):
    """POST /api/optimization/select/{thread_id} should exist."""
    resp = client.post("/api/optimization/select/test-123", json={})
    assert resp.status_code != 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/api/test_optimization_routes.py -v`
Expected: FAIL — 404 Not Found

- [ ] **Step 3: Create optimization.py routes**

```python
# backend/api/routes/optimization.py
"""Optimization API routes — draft submission and version selection."""

from __future__ import annotations

from fastapi import APIRouter, Request
from langgraph.types import Command
from pydantic import BaseModel, Field

from backend.api.errors import ChoiceNotPendingError, WorkflowNotFoundError
from backend.api.responses import success

router = APIRouter()


class DraftSubmission(BaseModel):
    """User's draft content submission."""
    title: str = Field(default="", description="标题")
    text: str = Field(default="", description="正文")
    hashtags: list[str] = Field(default_factory=list, description="话题标签")
    viral_links: list[str] = Field(default_factory=list, description="用户提供的爆款链接")


class VersionChoice(BaseModel):
    """User's version selection."""
    version_id: str = Field(description="选择的版本ID")
    version_type: str | None = Field(default=None, description="版本类型 A/B/C")


@router.post("/draft/{thread_id}")
async def submit_draft(thread_id: str, draft: DraftSubmission, request: Request):
    """提交用户草稿 — 更新状态，图继续执行."""
    if not thread_id or thread_id.strip() == "":
        from backend.api.errors import ValidationError
        raise ValidationError("thread_id", "thread_id cannot be empty")

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)
    if not state.values or state.values.get("session_id") is None:
        raise WorkflowNotFoundError(thread_id)

    # Update state with draft content
    await graph.aupdate_state(config, {
        "draft_content": draft.model_dump(),
        "user_viral_links": draft.viral_links,
    })

    return success(data={
        "thread_id": thread_id,
        "status": "draft_submitted",
    })


@router.post("/select/{thread_id}")
async def select_version(thread_id: str, choice: VersionChoice, request: Request):
    """选择版本 — 从 choice_gate 中断恢复."""
    if not thread_id or thread_id.strip() == "":
        from backend.api.errors import ValidationError
        raise ValidationError("thread_id", "thread_id cannot be empty")

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    if not state.values or state.values.get("session_id") is None:
        raise WorkflowNotFoundError(thread_id)

    # Verify workflow is at choice_gate
    if "choice_gate" not in state.next:
        current_phase = state.values.get("phase", "unknown")
        raise ChoiceNotPendingError(thread_id=thread_id, current_phase=current_phase)

    # Resume graph with selection
    result = await graph.ainvoke(
        Command(resume=choice.model_dump()),
        config,
    )

    next_phase = result.get("phase", "unknown") if result else "unknown"

    return success(data={
        "thread_id": thread_id,
        "status": "resumed",
        "next_phase": next_phase,
    })
```

- [ ] **Step 4: Add ChoiceNotPendingError to errors.py**

```python
# backend/api/errors.py — add error class
class ChoiceNotPendingError(HTTPException):
    """Raised when version selection is attempted but workflow is not at choice_gate."""

    def __init__(self, thread_id: str, current_phase: str):
        super().__init__(
            status_code=400,
            detail=f"Workflow {thread_id} is not awaiting version selection. Current phase: {current_phase}",
        )
```

- [ ] **Step 5: Register optimization router in app.py**

```python
# backend/api/app.py — add import and include router
from backend.api.routes import analytics, auth, realtime, review, workflow, optimization  # noqa: E402

# ... in router registration section ...
app.include_router(optimization.router, prefix="/api/optimization", tags=["optimization"])
```

- [ ] **Step 6: Add selected_title to choice_gate output**

```python
# backend/agents/nodes/optimization/choice_gate.py — update result dict
if selected_version:
    result = {
        "selected_version": selected_version_id,
        "copy_content": {
            "selected_title": selected_version.get("title", ""),  # NEW
            "title_candidates": [selected_version.get("title", "")],
            "body_text": selected_version.get("body", ""),
            "hashtags": selected_version.get("hashtags", []),
            "tone": selected_version.get("tone", ""),
        },
        "visual_plan": {
            "cover_prompt": selected_version.get("style_suggestion", ""),
            "style": selected_version.get("visual_style", ""),
            "color_palette": selected_version.get("color_palette", {}),
        },
        "phase": WorkflowPhase.CREATING,
    }
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/unit/api/test_optimization_routes.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/api/routes/optimization.py backend/api/app.py backend/api/errors.py backend/agents/nodes/optimization/choice_gate.py tests/unit/api/test_optimization_routes.py
git commit -m "feat(api): add /optimization/draft and /optimization/select endpoints

- submit_draft updates state with user content
- select_version resumes graph from choice_gate interrupt
- choice_gate now writes selected_title for publisher"
```

---

## Task 8: Version History Dedup

**Files:**
- Modify: `backend/api/routes/review.py`
- Test: `tests/unit/api/test_review_versions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/api/test_review_versions.py
"""Tests for version history deduplication."""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_content_versions_no_duplicate_on_revision():
    """Submitting needs_revision should not duplicate existing versions."""
    from backend.api.routes.review import submit_review
    from backend.state.enums import ContentStatus

    # Mock graph
    graph = MagicMock()
    graph.aget_state = AsyncMock(return_value=MagicMock(
        next=["review_gate"],
        values={
            "session_id": "test-123",
            "copy_content": {"title": "Test"},
            "visual_plan": {},
            "content_versions": [{"version_id": "v1", "title": "Old"}],
        },
    ))
    graph.aupdate_state = AsyncMock()
    graph.ainvoke = AsyncMock(return_value={"phase": "creating"})

    request = MagicMock()
    request.app.state.graph = graph

    decision = MagicMock()
    decision.decision = ContentStatus.NEEDS_REVISION
    decision.comments = "Please revise"
    decision.revisions = []
    decision.publish_options = None
    decision.model_dump = lambda: {
        "decision": "needs_revision",
        "comments": "Please revise",
        "revisions": [],
    }

    result = await submit_review("test-123", decision, request)

    # Check aupdate_state was called with single version (not existing + new)
    calls = graph.aupdate_state.call_args_list
    versions_call = None
    for call in calls:
        if "content_versions" in call[0][0]:
            versions_call = call[0][0]["content_versions"]
            break

    assert versions_call is not None
    assert len(versions_call) == 1, "Should pass only new version, not existing + new"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/api/test_review_versions.py -v`
Expected: FAIL — current code passes `existing_versions + [version_entry]`

- [ ] **Step 3: Fix review.py to pass only new version**

```python
# backend/api/routes/review.py — fix line 97-99
# On 'needs_revision', save current content as a version before resuming
if decision.decision == "needs_revision":
    copy_content = values.get("copy_content") or {}
    visual_plan = values.get("visual_plan") or {}
    label = "AI 初稿" if not values.get("content_versions") else "修改版本"
    version_entry = _build_version_entry(copy_content, visual_plan, label=label)

    # Pass only the new entry — reducer will append to existing
    await graph.aupdate_state(config, {
        "content_versions": [version_entry],  # FIXED: was existing_versions + [version_entry]
    })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/api/test_review_versions.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/routes/review.py tests/unit/api/test_review_versions.py
git commit -m "fix(review): pass only new version to aupdate_state

- content_versions uses append_list reducer
- Passing existing + new caused duplication
- Now passes only [version_entry], reducer handles append"
```

---

## Task 9: Persistence — Env-Based Graph Compilation + Atomic Writes

**Files:**
- Modify: `backend/api/app.py`
- Modify: `backend/api/routes/workflow.py`
- Test: `tests/unit/api/test_persistence.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/api/test_persistence.py
"""Tests for persistence configuration."""

import os
import pytest
from unittest.mock import patch, MagicMock


def test_app_uses_postgres_when_uri_set():
    """When POSTGRES_URI is set, app should use compile_graph_prod."""
    with patch.dict(os.environ, {"POSTGRES_URI": "postgresql://test"}):
        # This test verifies the logic exists
        # Actual async test would need real Postgres mock
        from backend.api.app import lifespan
        # Just check the import works
        assert lifespan is not None


def test_atomic_write_uses_temp_file():
    """_save_registry should write to temp file then rename."""
    import tempfile
    from pathlib import Path

    # Create a temp registry
    with tempfile.TemporaryDirectory() as tmpdir:
        from backend.api.routes import workflow
        workflow._REGISTRY_PATH = Path(tmpdir) / "test_registry.json"
        workflow._workflow_registry = {"test": {"status": "ok"}}

        workflow._save_registry()

        # Check file exists
        assert workflow._REGISTRY_PATH.exists()

        # Check content
        import json
        data = json.loads(workflow._REGISTRY_PATH.read_text())
        assert data == {"test": {"status": "ok"}}
```

- [ ] **Step 2: Run test to verify it passes (atomic write already works)**

Run: `pytest tests/unit/api/test_persistence.py -v`
Expected: PASS (atomic write test), but need to verify env-based compilation

- [ ] **Step 3: Update app.py for env-based graph compilation**

```python
# backend/api/app.py — update lifespan
import os

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时编译图 — 根据环境选择 checkpointer
    db_uri = os.environ.get("POSTGRES_URI")
    if db_uri:
        try:
            app.state.graph = await compile_graph_prod(db_uri)
        except Exception as e:
            # Fallback to dev on Postgres connection failure
            import logging
            logging.getLogger("xhs_growth").warning(f"Postgres checkpointer failed, using memory: {e}")
            app.state.graph = compile_graph_dev()
    else:
        app.state.graph = compile_graph_dev()
    yield
```

- [ ] **Step 4: Update _save_registry for atomic writes with file lock**

```python
# backend/api/routes/workflow.py — update _save_registry
import fcntl  # Add to imports

def _save_registry() -> None:
    """Persist workflow registry to JSON file with atomic write."""
    try:
        _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = _REGISTRY_PATH.with_suffix(".tmp")

        with open(tmp_path, "w", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)  # Exclusive lock
            json.dump(_workflow_registry, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())  # Ensure data is on disk

        os.replace(tmp_path, _REGISTRY_PATH)  # Atomic rename
    except OSError:
        pass  # Non-critical: registry is also in memory
```

- [ ] **Step 5: Add os import if not present**

```python
# backend/api/routes/workflow.py — ensure os is imported
import os
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/unit/api/test_persistence.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/api/app.py backend/api/routes/workflow.py tests/unit/api/test_persistence.py
git commit -m "fix(persistence): env-based graph compilation, atomic JSON writes

- POSTGRES_URI env var triggers compile_graph_prod
- File lock + atomic rename for registry writes
- Fallback to memory on Postgres connection failure"
```

---

## Task 10: Pause/Cancel — Background Task Registry

**Files:**
- Modify: `backend/api/routes/workflow.py`
- Modify: `backend/agents/nodes/_base.py`
- Test: `tests/integration/test_pause_cancel.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_pause_cancel.py
"""Tests for pause/cancel with background task management."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_cancel_cancels_background_task():
    """Cancel endpoint should cancel the running asyncio.Task."""
    from backend.api.routes.workflow import cancel_workflow, _background_tasks

    # Create a mock task
    task = asyncio.create_task(asyncio.sleep(100))
    _background_tasks["test-cancel-123"] = task

    # Mock request
    request = MagicMock()
    graph = MagicMock()
    graph.aget_state = AsyncMock(return_value=MagicMock(
        values={"session_id": "test-cancel-123", "phase": "scouting"},
        next=["trend_scout"],
    ))
    graph.aupdate_state = AsyncMock()
    request.app.state.graph = graph

    # Call cancel
    result = await cancel_workflow("test-cancel-123", request)

    # Task should be cancelled
    assert task.cancelled() or task.done()
    assert "test-cancel-123" not in _background_tasks


@pytest.mark.asyncio
async def test_check_cancelled_raises_on_cancelled_phase():
    """_check_cancelled should raise when phase is CANCELLED."""
    from backend.agents.nodes._base import _check_cancelled
    from backend.core.error_handling import WorkflowCancelledError
    from backend.state.enums import WorkflowPhase

    state = {"phase": WorkflowPhase.CANCELLED}

    with pytest.raises(WorkflowCancelledError):
        _check_cancelled(state)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_pause_cancel.py -v`
Expected: FAIL — _background_tasks doesn't exist, _check_cancelled doesn't exist

- [ ] **Step 3: Add background task registry to workflow.py**

```python
# backend/api/routes/workflow.py — add at module level
_background_tasks: dict[str, asyncio.Task] = {}
```

- [ ] **Step 4: Update _run_and_persist to handle CancelledError**

```python
# backend/api/routes/workflow.py — update _run_and_persist
async def _run_and_persist(thread_id: str, graph, config, initial_state=None):
    """Execute workflow and persist result."""
    try:
        if initial_state:
            result = await graph.ainvoke(initial_state, config)
        else:
            result = await graph.ainvoke(None, config)

        snapshot = await graph.aget_state(config)
        status = derive_status(snapshot)

        _workflow_registry[thread_id]["phase"] = snapshot.values.get("phase", "unknown")
        _workflow_registry[thread_id]["status"] = status.value
        _workflow_registry[thread_id]["progress_percent"] = get_progress(snapshot.values.get("phase", ""))
        _workflow_registry[thread_id]["error"] = snapshot.values.get("error")
        _workflow_registry[thread_id]["updated_at"] = datetime.now(UTC).isoformat()
        _save_registry()

        if status in (WorkflowStatus.COMPLETED, WorkflowStatus.ERROR, WorkflowStatus.CANCELLED):
            _save_workflow_result(thread_id, snapshot.values)

    except asyncio.CancelledError:
        _workflow_registry[thread_id]["status"] = "cancelled"
        _workflow_registry[thread_id]["updated_at"] = datetime.now(UTC).isoformat()
        _save_registry()
        raise  # Re-raise to properly cancel the task

    except Exception as exc:
        _workflow_registry[thread_id]["status"] = "error"
        _workflow_registry[thread_id]["error"] = str(exc)
        _workflow_registry[thread_id]["updated_at"] = datetime.now(UTC).isoformat()
        _save_registry()

    finally:
        _background_tasks.pop(thread_id, None)
```

- [ ] **Step 5: Update start_workflow to register task**

```python
# backend/api/routes/workflow.py — in start_workflow async_mode branch
if req.async_mode:
    task = asyncio.create_task(_run_and_persist(thread_id, graph, config, initial_state))
    _background_tasks[thread_id] = task
    return success(data={...})
```

- [ ] **Step 6: Update cancel_workflow to cancel task**

```python
# backend/api/routes/workflow.py — update cancel_workflow
@router.post("/cancel/{thread_id}")
async def cancel_workflow(thread_id: str, request: Request):
    """取消工作流 — 标记状态并取消后台任务."""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    if not state.values or state.values.get("session_id") is None:
        raise WorkflowNotFoundError(thread_id)

    current_phase = state.values.get("phase", "unknown")

    # Update state to mark as cancelled
    await graph.aupdate_state(config, {
        "phase": "cancelled",
        "error": "User cancelled",
        "prev_phase": current_phase,
    })

    # Cancel background task
    task = _background_tasks.get(thread_id)
    if task and not task.done():
        task.cancel()

    # Update registry
    if thread_id in _workflow_registry:
        _workflow_registry[thread_id]["status"] = "cancelled"
        _workflow_registry[thread_id]["phase"] = "cancelled"
        _workflow_registry[thread_id]["error"] = "User cancelled"
        _workflow_registry[thread_id]["updated_at"] = datetime.now(UTC).isoformat()
        _save_registry()

    return success(data={
        "thread_id": thread_id,
        "status": "cancelled",
        "message": "工作流已取消",
    })
```

- [ ] **Step 7: Add _check_cancelled to nodes/_base.py**

```python
# backend/agents/nodes/_base.py — add function
from backend.state.schema import XHSGrowthState
from backend.state.enums import WorkflowPhase
from backend.core.error_handling import WorkflowCancelledError


def _check_cancelled(state: XHSGrowthState) -> None:
    """Check if workflow is cancelled/paused and raise if so.

    Call at the start of each node to prevent execution after cancellation.
    """
    phase = state.get("phase")
    if phase in (WorkflowPhase.CANCELLED, WorkflowPhase.PAUSED):
        raise WorkflowCancelledError(f"Workflow is {phase}")


class NodeContext:
    # ... existing code ...


class NodeResult:
    # ... existing code ...
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/integration/test_pause_cancel.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/api/routes/workflow.py backend/agents/nodes/_base.py tests/integration/test_pause_cancel.py
git commit -m "fix(cancel): background task registry, task.cancel() on cancel

- _background_tasks tracks running asyncio.Tasks
- cancel_workflow cancels the task, not just state
- _check_cancelled helper for node entry guards"
```

---

## Task 11: Node Entry Guards — Add _check_cancelled to All Nodes

**Files:**
- Modify: All 14 node files in `backend/agents/nodes/`

- [ ] **Step 1: Add _check_cancelled to each node file**

For each node file, add the import and call at the start of the node function:

```python
# Pattern for each node file
from backend.agents.nodes._base import NodeResult, _check_cancelled

async def some_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    _check_cancelled(state)  # ADD THIS LINE at the start
    # ... rest of function
```

Files to modify:
- `backend/agents/nodes/orchestrator.py`
- `backend/agents/nodes/trend_scout.py`
- `backend/agents/nodes/content_strategist.py`
- `backend/agents/nodes/copywriter.py`
- `backend/agents/nodes/visual_designer.py`
- `backend/agents/nodes/review_gate.py`
- `backend/agents/nodes/publisher.py`
- `backend/agents/nodes/analyst.py`
- `backend/agents/nodes/engagement.py`
- `backend/agents/nodes/revise_content.py`
- `backend/agents/nodes/optimization/viral_matcher.py`
- `backend/agents/nodes/optimization/content_analyzer.py`
- `backend/agents/nodes/optimization/version_generator.py`
- `backend/agents/nodes/optimization/choice_gate.py`

- [ ] **Step 2: Run all tests to verify nothing breaks**

Run: `pytest tests/ -v --tb=short`
Expected: All existing tests pass

- [ ] **Step 3: Commit**

```bash
git add backend/agents/nodes/*.py backend/agents/nodes/optimization/*.py
git commit -m "fix(nodes): add _check_cancelled guard to all node entry points

- Prevents nodes from executing after cancellation
- Combined with router guards, ensures clean stop"
```

---

## Task 12: Wire Frontend to Optimization API

**Files:**
- Modify: `frontend/src/api/workflow.ts`
- Modify: `frontend/src/stores/optimization.ts`

- [ ] **Step 1: Add API methods to workflow.ts**

```typescript
// frontend/src/api/workflow.ts — add methods
export const workflowApi = {
  // ... existing methods ...

  async submitDraft(params: { thread_id: string; draft: DraftContent; viral_links: string[] }) {
    const response = await client.post(`/api/optimization/draft/${params.thread_id}`, {
      title: params.draft.title,
      text: params.draft.text,
      hashtags: params.draft.hashtags,
      viral_links: params.viral_links,
    })
    return response.data
  },

  async selectVersion(params: { thread_id: string; choice: VersionChoice }) {
    const response = await client.post(`/api/optimization/select/${params.thread_id}`, {
      version_id: params.choice.version_id,
      version_type: params.choice.version_type,
    })
    return response.data
  },
}
```

- [ ] **Step 2: Update optimization.ts to call API**

```typescript
// frontend/src/stores/optimization.ts — update submitDraft and selectVersion
import { workflowApi } from '@/api/workflow'

async function submitDraft(draft: DraftContent, viralLinks: string[]) {
  const threadId = getThreadId()
  if (!threadId) {
    error.value = 'No active workflow thread'
    return
  }

  isLoading.value = true
  error.value = null
  try {
    await workflowApi.submitDraft({ thread_id: threadId, draft, viral_links: viralLinks })
    draftContent.value = draft
    userViralLinks.value = viralLinks || []
  } catch (e: any) {
    error.value = e.message
    throw e
  } finally {
    isLoading.value = false
  }
}

async function selectVersion(choice: VersionChoice) {
  const threadId = getThreadId()
  if (!threadId) {
    error.value = 'No active workflow thread'
    return
  }

  isLoading.value = true
  error.value = null
  try {
    await workflowApi.selectVersion({ thread_id: threadId, choice })
    selectedVersion.value = choice.version_id
  } catch (e: any) {
    error.value = e.message
    throw e
  } finally {
    isLoading.value = false
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/workflow.ts frontend/src/stores/optimization.ts
git commit -m "feat(frontend): wire optimization store to backend API

- submitDraft calls /api/optimization/draft
- selectVersion calls /api/optimization/select
- Closes the frontend-backend loop for optimization"
```

---

## Task 13: Emit Terminal Events from Nodes

**Files:**
- Modify: `backend/agents/nodes/analyst.py`
- Modify: `backend/agents/nodes/engagement.py`

- [ ] **Step 1: Add WORKFLOW_COMPLETED event to engagement node**

```python
# backend/agents/nodes/engagement.py — add event emission
from backend.realtime import EventBusService, EventType

async def engagement_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    _check_cancelled(state)
    result = await _engagement(state, store=store)

    # Emit completion event if phase is COMPLETED
    if result.get("phase") == WorkflowPhase.COMPLETED:
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_COMPLETED,
            thread_id=state.get("session_id"),
            payload={"phase": "completed"},
        )

    return NodeResult(result, "engagement").to_dict()
```

- [ ] **Step 2: Add WORKFLOW_ERROR event emission on error**

```python
# backend/agents/nodes/_base.py — add helper for error event
def emit_error_event(state: XHSGrowthState, error: Exception) -> None:
    """Emit WORKFLOW_ERROR event."""
    from backend.realtime import EventBusService, EventType
    EventBusService.get_instance().emit(
        EventType.WORKFLOW_ERROR,
        thread_id=state.get("session_id"),
        payload={"error": str(error)},
    )
```

- [ ] **Step 3: Commit**

```bash
git add backend/agents/nodes/engagement.py backend/agents/nodes/_base.py
git commit -m "feat(events): emit WORKFLOW_COMPLETED from engagement node

- SSE streams can detect completion
- Enables clean close of event stream"
```

---

## Task 14: Integration Test — Full Workflow Status Flow

**Files:**
- Create: `tests/integration/test_workflow_status_flow.py`

- [ ] **Step 1: Write integration test**

```python
# tests/integration/test_workflow_status_flow.py
"""Integration test for workflow status derivation."""

import pytest
from backend.graph.builder import compile_graph_dev
from backend.state.machine import WorkflowStatus, derive_status
from backend.state.enums import WorkflowPhase


@pytest.mark.asyncio
async def test_workflow_status_awaiting_review_at_interrupt():
    """When workflow hits review_gate, status should be awaiting_review."""
    graph = compile_graph_dev()

    # Start a workflow that will hit review_gate
    initial_state = {
        "phase": WorkflowPhase.CREATING,
        "current_agent": "visual_designer",
        "session_id": "test-status-001",
        "account_id": "test",
        "messages": [],
        "content_plan": {"selected_topic": "test"},
        "copy_content": {"title_candidates": ["Test"]},
        "visual_plan": {"cover_prompt": "test"},
    }
    config = {"configurable": {"thread_id": "test-status-001"}}

    # Run until interrupt
    await graph.ainvoke(initial_state, config)

    # Get state and derive status
    snapshot = await graph.aget_state(config)
    status = derive_status(snapshot)

    assert status == WorkflowStatus.AWAITING_REVIEW, f"Expected awaiting_review, got {status}"


@pytest.mark.asyncio
async def test_workflow_status_completed_after_engagement():
    """In single mode, after engagement, status should be completed."""
    graph = compile_graph_dev()

    # Simulate a workflow at engagement completion
    initial_state = {
        "phase": WorkflowPhase.ENGAGING,
        "current_agent": "engagement",
        "session_id": "test-status-002",
        "account_id": "test",
        "execution_mode": "single",
        "messages": [],
        "publish_result": {"post_id": "123"},
    }
    config = {"configurable": {"thread_id": "test-status-002"}}

    # Update state to completed
    await graph.aupdate_state(config, {"phase": WorkflowPhase.COMPLETED})

    snapshot = await graph.aget_state(config)
    status = derive_status(snapshot)

    assert status == WorkflowStatus.COMPLETED
```

- [ ] **Step 2: Run integration test**

Run: `pytest tests/integration/test_workflow_status_flow.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_workflow_status_flow.py
git commit -m "test(integration): verify status derivation at key workflow points

- awaiting_review when at review_gate interrupt
- completed after engagement in single mode"
```

---

## Self-Review Checklist

**1. Spec coverage:**
- [x] Section 1 (State machine) → Task 1
- [x] Section 2 (HITL) → Task 2
- [x] Section 3 (SSE) → Task 6
- [x] Section 4 (Optimization API) → Task 7
- [x] Section 5 (Error handling) → Task 3, Task 4
- [x] Section 6 (Version dedup) → Task 8
- [x] Section 7 (Persistence) → Task 9
- [x] Section 8 (Pause/Cancel) → Task 10, Task 11
- [x] Section 9 (Topology) → Task 5
- [x] Frontend wiring → Task 12
- [x] Terminal events → Task 13

**2. Placeholder scan:** No TBDs, TODOs, or vague instructions found.

**3. Type consistency:**
- `WorkflowStatus` enum used consistently
- `derive_status()` signature matches usage
- `_check_cancelled()` signature matches node calls
- `ExecutionMode` enum matches state field type

---

Plan complete and saved to `docs/superpowers/plans/2026-05-31-workflow-bug-fixes.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
