"""Engagement node implementation."""

from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.engagement import EngagementAgent
from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.realtime import EventBusService
from backend.realtime.events import EventType
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

_engagement = EngagementAgent()


async def engagement_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute engagement agent."""
    _check_cancelled(state)
    result = await _engagement(state, store=store)

    if result.get("phase") == WorkflowPhase.COMPLETED:
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_COMPLETED,
            thread_id=state.get("session_id"),
            payload={"phase": "completed"},
        )

    return NodeResult(result, "engagement").to_dict()