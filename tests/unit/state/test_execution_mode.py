"""Tests for execution mode."""

from backend.state.enums import ExecutionMode


def test_execution_mode_single():
    assert ExecutionMode.SINGLE == "single"


def test_execution_mode_continuous():
    assert ExecutionMode.CONTINUOUS == "continuous"


def test_should_continue_single_mode_goes_to_engagement():
    """In single mode, analyzing phase routes to engagement."""
    from backend.graph.routers import should_continue
    from backend.state.enums import WorkflowPhase

    state = {"phase": WorkflowPhase.ANALYZING, "execution_mode": "single"}
    assert should_continue(state) == "engagement"


def test_should_continue_continuous_mode_loops_to_orchestrator():
    """In continuous mode, analyzing phase routes back to orchestrator."""
    from backend.graph.routers import should_continue
    from backend.state.enums import WorkflowPhase

    state = {"phase": WorkflowPhase.ANALYZING, "execution_mode": "continuous"}
    assert should_continue(state) == "orchestrator"
