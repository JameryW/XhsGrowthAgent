"""Copywriter node implementation."""

from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.copywriter import CopywriterAgent
from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.realtime import EventBusService, EventType
from backend.state.schema import XHSGrowthState

_copywriter = CopywriterAgent()


async def copywriter_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute copywriter agent and emit data updated event."""
    _check_cancelled(state)
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

    # Emit data updated event for content_versions (multi-style variants)
    if result.get("content_versions"):
        event_bus.emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "content_versions", "data": result.get("content_versions")},
        )

    return NodeResult(result, "copywriter").to_dict()