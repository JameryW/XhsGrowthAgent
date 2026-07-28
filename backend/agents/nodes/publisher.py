"""Publisher node implementation."""

from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.agents.publisher import PublisherAgent
from backend.realtime import EventBusService, EventType
from backend.state.schema import XHSGrowthState

_publisher = PublisherAgent()


async def publisher_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute publisher agent — does NOT emit WORKFLOW_COMPLETED here.

    The completed event is emitted by _runner._emit_status_transition when
    derive_status returns COMPLETED, which happens only after the graph has
    fully finished (including any manually resumed analyst step). Emitting it
    here would prematurely close SSE streams and skip downstream nodes.
    """
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

    return NodeResult(result, "publisher").to_dict()
