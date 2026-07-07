"""Tests for core.error_handling module."""

from backend.core.error_handling import AgentError, handle_agent_error
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState


def test_agent_error_creation():
    """Verify AgentError can be created with all fields."""
    original = ValueError("test error")
    error = AgentError("test_agent", "testing", original)
    assert error.agent_name == "test_agent"
    assert error.phase == "testing"
    assert error.original_error == original


def test_handle_agent_error_returns_state_update():
    """Verify handle_agent_error returns correct state update."""
    original = TimeoutError("timeout")
    state: XHSGrowthState = {"retry_count": 0}
    result = handle_agent_error(original, state, agent_name="trend_scout")
    assert result["phase"] == WorkflowPhase.ERROR
    assert result["error"] == "timeout"
    assert result["retry_count"] == 1
    assert result["current_agent"] == "trend_scout"


def test_handle_agent_error_increments_retry():
    """Verify handle_agent_error increments retry_count."""
    original = RuntimeError("runtime")
    state: XHSGrowthState = {"retry_count": 2}
    result = handle_agent_error(original, state, agent_name="copywriter")
    assert result["retry_count"] == 3
    assert result["current_agent"] == "copywriter"


def test_handle_agent_error_default_agent_name():
    """Verify handle_agent_error works without agent_name (backward compat)."""
    original = ValueError("oops")
    state: XHSGrowthState = {"retry_count": 0}
    result = handle_agent_error(original, state)
    assert result["phase"] == WorkflowPhase.ERROR
    assert result["error"] == "oops"
    assert result["retry_count"] == 1
    assert result["current_agent"] == ""
