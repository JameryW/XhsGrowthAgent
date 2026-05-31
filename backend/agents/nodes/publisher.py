"""Publisher node implementation."""

from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.agents.publisher import PublisherAgent
from backend.realtime import EventBusService, EventType
from backend.state.schema import XHSGrowthState

_publisher = PublisherAgent()


async def publisher_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute publisher agent and emit workflow completed event."""
    _check_cancelled(state)
    thread_id = state.get("session_id")
    event_bus = EventBusService.get_instance()

    event_bus.emit(
        EventType.WORKFLOW_AGENT_STARTED,
        thread_id=thread_id,
        payload={"agent": "publisher"},
    )

    result = await _publisher(state, store=store)

    event_bus.emit(
        EventType.WORKFLOW_AGENT_COMPLETED,
        thread_id=thread_id,
        payload={
            "agent": "publisher",
            "status": result.get("publish_result", {}).get("status", "unknown"),
        },
    )

    # Emit workflow completed event after publish
    if result.get("publish_result"):
        event_bus.emit(
            EventType.WORKFLOW_COMPLETED,
            thread_id=thread_id,
            payload={"publish_result": result.get("publish_result")},
        )

    return NodeResult(result, "publisher").to_dict()