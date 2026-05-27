"""Tests for core.error_handling module."""
import pytest
from xhs_growth.core.error_handling import AgentError, handle_agent_error
from xhs_growth.state.enums import WorkflowPhase
from xhs_growth.state.schema import XHSGrowthState


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
    result = handle_agent_error(original, state)
    assert result["phase"] == WorkflowPhase.ERROR
    assert result["error"] == "timeout"
    assert result["retry_count"] == 1


def test_handle_agent_error_increments_retry():
    """Verify handle_agent_error increments retry_count."""
    original = RuntimeError("runtime")
    state: XHSGrowthState = {"retry_count": 2}
    result = handle_agent_error(original, state)
    assert result["retry_count"] == 3