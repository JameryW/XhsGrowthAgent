"""Base classes for graph nodes."""

from typing import Any

from langgraph.store.base import BaseStore

from backend.core.error_handling import WorkflowCancelledError
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState


class NodeContext:
    """节点执行上下文"""

    def __init__(self, state: XHSGrowthState, store: BaseStore | None):
        self.state = state
        self.store = store


class NodeResult:
    """节点执行结果封装"""

    def __init__(self, updates: dict[str, Any], agent_name: str = ""):
        self.updates = updates
        self.agent_name = agent_name

    def to_dict(self) -> dict[str, Any]:
        """转换为状态更新字典"""
        result = self.updates.copy()
        if self.agent_name:
            result["current_agent"] = self.agent_name
        return result


def _check_cancelled(state: XHSGrowthState) -> None:
    """Check if workflow is cancelled/paused and raise if so."""
    phase = state.get("phase")
    if phase in (WorkflowPhase.CANCELLED, WorkflowPhase.PAUSED):
        raise WorkflowCancelledError(f"Workflow is {phase}")


def emit_error_event(state: XHSGrowthState, error: Exception) -> None:
    """Emit WORKFLOW_ERROR event."""
    from backend.realtime import EventBusService, EventType
    EventBusService.get_instance().emit(
        EventType.WORKFLOW_ERROR,
        thread_id=state.get("session_id"),
        payload={"error": str(error)},
    )