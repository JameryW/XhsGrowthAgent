"""Unified error handling for XHS Growth Agent."""

from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState


class AgentError(Exception):
    """Agent execution error — should be caught by LangGraph retry."""

    def __init__(self, agent_name: str, cause: Exception, phase: str | None = None):
        # Backward compat: old code passed (agent_name, phase_str, original_error)
        # Detect old convention: if cause is a string, it's actually the phase
        if isinstance(cause, str) and phase is not None and isinstance(phase, Exception):
            # Old calling convention: (agent_name, phase, original_error)
            actual_phase = cause
            actual_cause = phase
            cause = actual_cause
            phase = actual_phase

        self.agent_name = agent_name
        self.cause = cause
        self.phase = phase
        # Backward compat alias
        self.original_error = cause
        super().__init__(f"Agent {agent_name} failed: {cause}")


class WorkflowCancelledError(Exception):
    """Workflow was cancelled — nodes should stop execution."""

    pass


def handle_agent_error(error: Exception, state: XHSGrowthState) -> dict:
    """统一错误处理，返回状态更新"""
    return {
        "phase": WorkflowPhase.ERROR,
        "error": str(error),
        "retry_count": state.get("retry_count", 0) + 1,
    }
