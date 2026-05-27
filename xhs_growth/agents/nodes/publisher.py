"""Publisher node implementation."""

from typing import Any
from langgraph.store.base import BaseStore

from xhs_growth.agents.nodes._base import NodeResult
from xhs_growth.agents.publisher import PublisherAgent
from xhs_growth.realtime import EventBusService, EventType
from xhs_growth.state.schema import XHSGrowthState


_publisher = PublisherAgent()


async def publisher_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute publisher agent and emit workflow completed event."""
    result = await _publisher(state, store=store)

    # Emit workflow completed event after publish
    thread_id = state.get("thread_id")
    if result.get("publish_result"):
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_COMPLETED,
            thread_id=thread_id,
            payload={"publish_result": result.get("publish_result")},
        )

    return NodeResult(result, "publisher").to_dict()