"""Viral matcher node implementation - searches and matches viral posts."""

from typing import Any
from langgraph.store.base import BaseStore

from backend.agents.nodes._base import NodeResult
from backend.agents.viral_matcher import ViralMatcherAgent
from backend.realtime import EventBusService, EventType
from backend.state.schema import XHSGrowthState


_viral_matcher = ViralMatcherAgent()


async def viral_matcher_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute viral matcher agent and emit data updated event."""
    result = await _viral_matcher(state, store=store)

    # Emit data updated event for viral_posts
    thread_id = state.get("session_id")
    if result.get("viral_posts"):
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "viral_posts", "data": result.get("viral_posts")},
        )

    return NodeResult(result, "viral_matcher").to_dict()