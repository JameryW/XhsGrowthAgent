"""Content strategist node implementation."""

from typing import Any
from langgraph.store.base import BaseStore

from backend.agents.nodes._base import NodeResult
from backend.agents.content_strategist import ContentStrategistAgent
from backend.realtime import EventBusService, EventType
from backend.state.schema import XHSGrowthState


_content_strategist = ContentStrategistAgent()


async def content_strategist_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute content strategist agent and emit data updated event."""
    thread_id = state.get("session_id")
    event_bus = EventBusService.get_instance()

    event_bus.emit(
        EventType.WORKFLOW_AGENT_STARTED,
        thread_id=thread_id,
        payload={"agent": "content_strategist"},
    )

    result = await _content_strategist(state, store=store)

    event_bus.emit(
        EventType.WORKFLOW_AGENT_COMPLETED,
        thread_id=thread_id,
        payload={"agent": "content_strategist"},
    )

    # Emit data updated event for content_plan
    if result.get("content_plan"):
        event_bus.emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "content_plan", "data": result.get("content_plan")},
        )

    return NodeResult(result, "content_strategist").to_dict()