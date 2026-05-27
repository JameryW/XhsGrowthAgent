"""Visual designer node implementation."""

from typing import Any
from langgraph.store.base import BaseStore

from backend.agents.nodes._base import NodeResult
from backend.agents.visual_designer import VisualDesignerAgent
from backend.realtime import EventBusService, EventType
from backend.state.schema import XHSGrowthState


_visual_designer = VisualDesignerAgent()


async def visual_designer_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute visual designer agent and emit data updated event."""
    result = await _visual_designer(state, store=store)

    # Emit data updated event for visual_plan
    thread_id = state.get("thread_id")
    if result.get("visual_plan"):
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "visual_plan", "data": result.get("visual_plan")},
        )

    return NodeResult(result, "visual_designer").to_dict()