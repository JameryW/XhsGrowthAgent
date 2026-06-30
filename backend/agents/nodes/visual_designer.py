"""Visual designer node implementation."""

from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.agents.visual_designer import VisualDesignerAgent
from backend.realtime import EventBusService, EventType
from backend.state.schema import XHSGrowthState

_visual_designer = VisualDesignerAgent()


async def visual_designer_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute visual designer agent and emit data updated event."""
    _check_cancelled(state)
    result = await _visual_designer(state, store=store)

    # Emit data updated event for visual_plan
    thread_id = state.get("session_id")
    if result.get("visual_plan"):
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "visual_plan", "data": result.get("visual_plan")},
        )

    # 更新阶段为 reviewing（即将进入审核）
    result["phase"] = "reviewing"

    return NodeResult(result, "visual_designer").to_dict()
