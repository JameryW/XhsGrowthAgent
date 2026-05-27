"""Content strategist node implementation."""

from typing import Any
from langgraph.store.base import BaseStore

from xhs_growth.agents.nodes._base import NodeResult
from xhs_growth.agents.content_strategist import ContentStrategistAgent
from xhs_growth.realtime import EventBusService, EventType
from xhs_growth.state.schema import XHSGrowthState


_content_strategist = ContentStrategistAgent()


async def content_strategist_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute content strategist agent and emit data updated event."""
    result = await _content_strategist(state, store=store)

    # Emit data updated event for content_plan
    thread_id = state.get("thread_id")
    if result.get("content_plan"):
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "content_plan", "data": result.get("content_plan")},
        )

    return NodeResult(result, "content_strategist").to_dict()