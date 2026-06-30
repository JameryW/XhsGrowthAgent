"""Analyst node implementation."""

from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.analyst import AnalystAgent
from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.realtime import EventBusService, EventType
from backend.state.schema import XHSGrowthState

_analyst = AnalystAgent()


async def analyst_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute analyst agent and emit data updated event."""
    _check_cancelled(state)
    thread_id = state.get("session_id")
    event_bus = EventBusService.get_instance()

    event_bus.emit(
        EventType.WORKFLOW_AGENT_STARTED,
        thread_id=thread_id,
        payload={"agent": "analyst"},
    )

    result = await _analyst(state, store=store)

    event_bus.emit(
        EventType.WORKFLOW_AGENT_COMPLETED,
        thread_id=thread_id,
        payload={"agent": "analyst"},
    )

    # Emit data updated event for analytics
    if result.get("analytics"):
        event_bus.emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "analytics", "data": result.get("analytics")},
        )

    # Emit Ripple comparison event for real-time UI updates
    if result.get("ripple_comparison"):
        event_bus.emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "ripple_comparison", "data": result.get("ripple_comparison")},
        )

    return NodeResult(result, "analyst").to_dict()
