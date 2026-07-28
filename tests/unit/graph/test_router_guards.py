"""Tests for router terminal state guards."""

from backend.graph.routers import (
    orchestrator_router,
    review_outcome,
    should_continue,
    should_plan,
)
from backend.state.enums import WorkflowPhase


def test_should_continue_returns_end_on_cancelled():
    state = {"phase": WorkflowPhase.CANCELLED}
    assert should_continue(state) == "__end__"


def test_should_continue_returns_end_on_paused():
    state = {"phase": WorkflowPhase.PAUSED}
    assert should_continue(state) == "__end__"


def test_should_continue_returns_end_on_error_phase():
    """Only phase=ERROR is terminal, not just an error string with an active phase."""
    state = {"phase": WorkflowPhase.ERROR}
    assert should_continue(state) == "__end__"


def test_should_continue_ends_after_analysis_even_with_error_field():
    """An active analysis phase still terminates after analysis."""
    state = {"phase": WorkflowPhase.ANALYZING, "error": "Something failed"}
    assert should_continue(state) == "__end__"


def test_should_plan_returns_end_on_cancelled():
    state = {"phase": WorkflowPhase.CANCELLED, "trend_data": None, "error": "x"}
    assert should_plan(state) == "__end__"


def test_orchestrator_router_returns_end_on_cancelled():
    state = {"phase": WorkflowPhase.CANCELLED}
    assert orchestrator_router(state) == "__end__"


def test_review_outcome_returns_end_on_cancelled():
    state = {
        "phase": WorkflowPhase.CANCELLED,
        "human_feedback": {"decision": "approved"},
    }
    assert review_outcome(state) == "__end__"
