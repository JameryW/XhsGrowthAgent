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
            payload={
                "phase": "completed",
                "copy_content": state.get("copy_content"),
                "trend_data": state.get("trend_data"),
                "content_plan": state.get("content_plan"),
                "visual_plan": state.get("visual_plan"),
                "publish_result": state.get("publish_result"),
                "analytics": state.get("analytics"),
                "ripple_prediction": state.get("ripple_prediction"),
                "ripple_pmf": state.get("ripple_pmf"),
                "ripple_comparison": state.get("ripple_comparison"),
            },
        )

    return NodeResult(result, "engagement").to_dict()