"""Copywriter node implementation."""

from typing import Any
from langgraph.store.base import BaseStore

from backend.agents.nodes._base import NodeResult
from backend.agents.copywriter import CopywriterAgent
from backend.realtime import EventBusService, EventType
from backend.state.schema import XHSGrowthState


_copywriter = CopywriterAgent()


async def copywriter_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute copywriter agent and emit data updated event."""
    thread_id = state.get("session_id")
    event_bus = EventBusService.get_instance()

    event_bus.emit(
        EventType.WORKFLOW_AGENT_STARTED,
        thread_id=thread_id,
        payload={"agent": "copywriter"},
    )

    result = await _copywriter(state, store=store)

    event_bus.emit(
        EventType.WORKFLOW_AGENT_COMPLETED,
        thread_id=thread_id,
        payload={"agent": "copywriter"},
    )

    # Emit data updated event for copy_content
    if result.get("copy_content"):
        event_bus.emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "copy_content", "data": result.get("copy_content")},
        )

    return NodeResult(result, "copywriter").to_dict()