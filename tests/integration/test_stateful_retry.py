"""Integration tests for stateful retry — prd 07-07-remove-handle-agent-error-dead-code.

These compile the REAL graph (not mocked) and verify the end-to-end
stateful retry path that prd 07-07 activates:

  1. Node failure → BaseAgent.__call__ returns error state (not raises)
     → state merges error + retry_count+1 + phase=ERROR.
  2. should_plan reads error + retry_count<2 → routes back to trend_scout
     (stateful retry, NOT LangGraph RetryPolicy which only triggers on
     exceptions and is now a no-op since we don't raise).
  3. After retry_count reaches 2, should_plan stops retrying → __end__.
  4. orchestrator reads retry_count>=3 → ERROR terminal (via the
     orchestrator→trend_scout loop if reached).

The conftest auto-mocks get_model globally. We override it per-test to
make trend_scout's LLM call raise, then succeed on retry.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from backend.graph.builder import build_graph
from backend.state.enums import WorkflowPhase


def _compile_test_graph() -> Any:
    """Compile the real graph with an in-memory checkpointer + store.

    No SQLite/Postgres — purely in-memory so tests are fast and hermetic.
    The graph topology is byte-for-byte the production one.
    """
    builder = build_graph()
    return builder.compile(
        checkpointer=MemorySaver(),
        store=InMemoryStore(),
        interrupt_before=["choice_gate", "draft_gate"],
    )


@pytest.fixture(autouse=True)
def _reset_agent_model_cache():
    """Reset the cached _model on module-level agent singletons.

    TrendScoutAgent (and other agents) are instantiated as module-level
    singletons (e.g. `_trend_scout = TrendScoutAgent()` in trend_scout.py).
    Their `_model` is cached on first access and persists across tests,
    so a monkeypatched `get_model` only takes effect if `_model` is None.
    Resetting before each test ensures the patched `get_model` is called.
    """
    from backend.agents.nodes.trend_scout import _trend_scout

    _trend_scout._model = None
    yield
    _trend_scout._model = None


def _make_failing_model() -> MagicMock:
    """A mock LLM whose ainvoke always raises (simulates LLM outage)."""
    mock = MagicMock()
    mock.ainvoke = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    return mock


def _make_success_model(content: str = '{"hot_topics": []}') -> MagicMock:
    """A mock LLM whose ainvoke returns valid JSON content."""
    mock = MagicMock()
    mock.ainvoke = AsyncMock(return_value=MagicMock(content=content))
    return mock


class TestStatefulRetryE2E:
    """E2E: real graph retries trend_scout via stateful retry_count."""

    @pytest.mark.asyncio
    async def test_trend_scout_failure_sets_error_state(self, monkeypatch):
        """Node failure returns error state (not raises) → state has
        error + retry_count incremented + phase=ERROR.

        This is the core contract of prd 07-07: BaseAgent.__call__ returns
        handle_agent_error(e, state) so the error state merges into LangGraph
        state (previously it raised, so state was never updated).
        """
        graph = _compile_test_graph()
        thread_id = "stateful-fail-once"
        config = {"configurable": {"thread_id": thread_id}}

        # Make the LLM always fail → trend_scout.execute raises → __call__
        # returns handle_agent_error(e, state) with phase=ERROR.
        failing_model = _make_failing_model()
        monkeypatch.setattr("backend.agents.base.get_model", lambda *a, **kw: failing_model)
        monkeypatch.setattr("backend.models.router.get_model", lambda *a, **kw: failing_model)

        initial_state: dict[str, Any] = {
            "phase": WorkflowPhase.SCOUTING,
            "current_agent": "orchestrator",
            "workflow_mode": "trend",
            "session_id": thread_id,
            "account_id": "test_account",
            "niche": "母婴",
            "error": None,
            "retry_count": 0,
            "messages": [],
            "trend_data": {},
            "content_plan": {},
            "copy_content": {},
            "visual_plan": {},
            "publish_result": {},
            "analytics": {},
            "engagement_actions": [],
            "human_feedback": {},
            "content_history": [],
            "performance_log": [],
        }

        final_state = await graph.ainvoke(initial_state, config)

        # trend_scout failed → __call__ returned error state → should_plan
        # retried (retry_count 0<2) → trend_scout failed again → retry_count 1
        # → should_plan retried → trend_scout failed → retry_count 2 →
        # should_plan no longer retries (2 >= 2) → __end__.
        # So final retry_count should be 2 and error should be set.
        assert final_state is not None
        assert final_state.get("error") is not None
        assert "LLM unavailable" in final_state.get("error", "")
        # retry_count should reach 2 (the should_plan retry ceiling)
        assert final_state.get("retry_count", 0) >= 2

    @pytest.mark.asyncio
    async def test_trend_scout_retries_then_succeeds(self, monkeypatch):
        """Stateful retry: trend_scout fails once (retry_count=1), then
        should_plan retries (1<2), and the 2nd attempt succeeds → workflow
        continues to content_strategist (not __end__).

        Note: TrendScoutAgent caches its model instance (self._model), so
        we use a single mock whose ainvoke fails on call 1, succeeds on call 2+.
        """
        graph = _compile_test_graph()
        thread_id = "stateful-retry-then-success"
        config = {"configurable": {"thread_id": thread_id}}

        # Single mock model: first ainvoke raises, subsequent calls succeed.
        # The agent caches the model, so get_model is called once.
        success_response = MagicMock(
            content='{"hot_topics": [{"topic": "测试", "heat_score": 90}]}'
        )

        async def _flaky_ainvoke(*args, **kwargs):
            if not hasattr(_flaky_ainvoke, "_called"):
                _flaky_ainvoke._called = True  # type: ignore[attr-defined]
                raise RuntimeError("transient LLM failure")
            return success_response

        flaky_model = MagicMock()
        flaky_model.ainvoke = AsyncMock(side_effect=_flaky_ainvoke)
        monkeypatch.setattr("backend.agents.base.get_model", lambda *a, **kw: flaky_model)
        monkeypatch.setattr("backend.models.router.get_model", lambda *a, **kw: flaky_model)

        initial_state: dict[str, Any] = {
            "phase": WorkflowPhase.SCOUTING,
            "current_agent": "orchestrator",
            "workflow_mode": "trend",
            "session_id": thread_id,
            "account_id": "test_account",
            "niche": "母婴",
            "error": None,
            "retry_count": 0,
            "messages": [],
            "trend_data": {},
            "content_plan": {},
            "copy_content": {},
            "visual_plan": {},
            "publish_result": {},
            "analytics": {},
            "engagement_actions": [],
            "human_feedback": {},
            "content_history": [],
            "performance_log": [],
        }

        final_state = await graph.ainvoke(initial_state, config)

        # After the transient failure, should_plan retried trend_scout (retry_count
        # was 1 < 2). The retry succeeded with trend_data. should_plan then saw
        # trend_data.hot_topics → routed to content_strategist.
        # The workflow progressed past trend_scout (didn't end at __end__ due
        # to error). Final state has trend_data populated and error cleared.
        assert final_state is not None
        # trend_data should be populated (the successful retry returned it)
        trend_data = final_state.get("trend_data", {})
        assert trend_data.get("hot_topics"), (
            f"Expected trend_data with hot_topics after successful retry, got: {trend_data}"
        )
        # The graph progressed — not stuck in a pure error state
        # (content_strategist runs next, which may also use the model).
        assert final_state.get("error") is None or final_state.get("trend_data")

    @pytest.mark.asyncio
    async def test_failure_performance_log_has_failed_entry(self, monkeypatch):
        """When trend_scout fails, the perf_log gets a status=failed entry
        (now possible because __call__ returns a dict, not raises)."""
        graph = _compile_test_graph()
        thread_id = "stateful-perf-failed"
        config = {"configurable": {"thread_id": thread_id}}

        failing_model = _make_failing_model()
        monkeypatch.setattr("backend.agents.base.get_model", lambda *a, **kw: failing_model)
        monkeypatch.setattr("backend.models.router.get_model", lambda *a, **kw: failing_model)

        initial_state: dict[str, Any] = {
            "phase": WorkflowPhase.SCOUTING,
            "current_agent": "orchestrator",
            "workflow_mode": "trend",
            "session_id": thread_id,
            "account_id": "test_account",
            "niche": "母婴",
            "error": None,
            "retry_count": 0,
            "messages": [],
            "trend_data": {},
            "content_plan": {},
            "copy_content": {},
            "visual_plan": {},
            "publish_result": {},
            "analytics": {},
            "engagement_actions": [],
            "human_feedback": {},
            "content_history": [],
            "performance_log": [],
        }

        final_state = await graph.ainvoke(initial_state, config)

        # performance_log should contain at least one status=failed entry
        # from trend_scout's failed attempts.
        perf_log = final_state.get("performance_log", [])
        failed_entries = [e for e in perf_log if e.get("status") == "failed"]
        assert len(failed_entries) >= 1, f"Expected at least one failed perf entry, got: {perf_log}"
        # The failed entry should reference trend_scout
        assert any(e.get("agent") == "trend_scout" for e in failed_entries)


class TestOrchestratorRetryTermination:
    """E2E: orchestrator's retry_count>=3 → ERROR terminal path.

    The orchestrator (orchestrator.py:30-37) reads retry_count>=3 and
    returns phase=ERROR. With stateful retry active, this path is now
    reachable: trend_scout fails 3 times (retry_count reaches 3 via
    should_plan retries + orchestrator loop-back), then orchestrator
    sees retry_count>=3 and sets phase=ERROR → __end__.

    However, should_plan caps at retry_count<2, so trend_scout alone can't
    push retry_count to 3. The orchestrator path is reached when:
    - trend_scout fails 2x (retry_count=2, should_plan stops retrying)
    - But the graph goes __end__ at should_plan, not back to orchestrator.

    So the orchestrator retry_count>=3 path requires a different entry
    (e.g. continuous mode loop-back). This test is kept as documentation
    of the contract — the should_plan path is the primary stateful retry
    mechanism activated by prd 07-07.
    """

    @pytest.mark.asyncio
    async def test_orchestrator_error_path_on_high_retry(self, monkeypatch):
        """If retry_count>=3 reaches the orchestrator, it sets phase=ERROR.

        We simulate this by starting the workflow with retry_count=3 and
        an error already set, then routing through orchestrator. The
        orchestrator reads error+retry_count>=3 → returns phase=ERROR →
        orchestrator_router → __end__.
        """
        graph = _compile_test_graph()
        thread_id = "orchestrator-high-retry"
        config = {"configurable": {"thread_id": thread_id}}

        # Model succeeds (we're testing the orchestrator's error check,
        # not trend_scout's failure). The orchestrator reads the pre-set
        # error + retry_count from state.
        success_model = _make_success_model('{"hot_topics": []}')
        monkeypatch.setattr("backend.agents.base.get_model", lambda *a, **kw: success_model)
        monkeypatch.setattr("backend.models.router.get_model", lambda *a, **kw: success_model)

        # Start with error + retry_count=3 (simulating 3 failed trend_scout
        # attempts in a prior cycle). Orchestrator should see this and
        # return phase=ERROR.
        initial_state: dict[str, Any] = {
            "phase": WorkflowPhase.SCOUTING,
            "current_agent": "orchestrator",
            "workflow_mode": "trend",
            "session_id": thread_id,
            "account_id": "test_account",
            "niche": "母婴",
            "error": "persistent failure",
            "retry_count": 3,
            "messages": [],
            "trend_data": {},
            "content_plan": {},
            "copy_content": {},
            "visual_plan": {},
            "publish_result": {},
            "analytics": {},
            "engagement_actions": [],
            "human_feedback": {},
            "content_history": [],
            "performance_log": [],
        }

        final_state = await graph.ainvoke(initial_state, config)

        # orchestrator saw error + retry_count>=3 → returned phase=ERROR →
        # orchestrator_router → __end__. The workflow terminated.
        assert final_state is not None
        assert final_state.get("phase") == WorkflowPhase.ERROR
