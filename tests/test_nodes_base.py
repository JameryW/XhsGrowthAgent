"""Tests for nodes base classes."""
from backend.agents.nodes._base import NodeContext, NodeResult
from backend.state.schema import XHSGrowthState


def test_node_context_creation():
    """Verify NodeContext wraps state and store."""
    state: XHSGrowthState = {"phase": "testing"}
    ctx = NodeContext(state, None)
    assert ctx.state == state
    assert ctx.store is None


def test_node_result_to_dict():
    """Verify NodeResult converts to dict."""
    result = NodeResult({"phase": "completed", "error": None})
    output = result.to_dict()
    assert output["phase"] == "completed"
    assert output["error"] is None


def test_node_result_includes_current_agent():
    """Verify NodeResult includes current_agent."""
    result = NodeResult({"phase": "completed"}, agent_name="test_agent")
    output = result.to_dict()
    assert output["current_agent"] == "test_agent"