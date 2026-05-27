"""Unified error handling for XHS Growth Agent."""

from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState


class AgentError(Exception):
    """Agent执行错误"""

    def __init__(self, agent_name: str, phase: str, original_error: Exception):
        self.agent_name = agent_name
        self.phase = phase
        self.original_error = original_error
        super().__init__(f"{agent_name} failed in {phase}: {original_error}")


def handle_agent_error(error: Exception, state: XHSGrowthState) -> dict:
    """统一错误处理，返回状态更新"""
    return {
        "phase": WorkflowPhase.ERROR,
        "error": str(error),
        "retry_count": state.get("retry_count", 0) + 1,
    }