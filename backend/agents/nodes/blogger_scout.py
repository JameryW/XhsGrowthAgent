"""Blogger scout node — discovers top bloggers from niche keywords."""

from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.blogger_scout import BloggerScoutAgent
from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.realtime import EventBusService, EventType
from backend.state.schema import XHSGrowthState

_blogger_scout = BloggerScoutAgent()


async def blogger_scout_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute blogger scout agent and emit data updated event."""
    _check_cancelled(state)
    result = await _blogger_scout(state, store=store)

    thread_id = state.get("session_id")
    if result.get("blogger_candidates"):
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "blogger_candidates", "data": result.get("blogger_candidates")},
        )

    return NodeResult(result, "blogger_scout").to_dict()
