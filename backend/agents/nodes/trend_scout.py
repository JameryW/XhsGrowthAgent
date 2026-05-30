"""Trend scout node implementation."""

from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.nodes._base import NodeResult
from backend.agents.trend_scout import TrendScoutAgent
from backend.realtime import EventBusService, EventType
from backend.state.schema import XHSGrowthState

_trend_scout = TrendScoutAgent()


async def trend_scout_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute trend scout agent and emit data updated event."""
    thread_id = state.get("session_id")
    event_bus = EventBusService.get_instance()

    event_bus.emit(
        EventType.WORKFLOW_AGENT_STARTED,
        thread_id=thread_id,
        payload={"agent": "trend_scout"},
    )

    result = await _trend_scout(state, store=store)

    event_bus.emit(
        EventType.WORKFLOW_AGENT_COMPLETED,
        thread_id=thread_id,
        payload={"agent": "trend_scout"},
    )

    # Emit data updated event for trend_data
    if result.get("trend_data"):
        event_bus.emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "trend_data", "data": result.get("trend_data")},
        )

    return NodeResult(result, "trend_scout").to_dict()