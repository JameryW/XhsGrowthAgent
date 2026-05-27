"""Analyst node implementation."""

from typing import Any
from langgraph.store.base import BaseStore

from xhs_growth.agents.nodes._base import NodeResult
from xhs_growth.agents.analyst import AnalystAgent
from xhs_growth.realtime import EventBusService, EventType
from xhs_growth.state.schema import XHSGrowthState


_analyst = AnalystAgent()


async def analyst_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute analyst agent and emit data updated event."""
    result = await _analyst(state, store=store)

    # Emit data updated event for analytics
    thread_id = state.get("thread_id")
    if result.get("analytics"):
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "analytics", "data": result.get("analytics")},
        )

    return NodeResult(result, "analyst").to_dict()