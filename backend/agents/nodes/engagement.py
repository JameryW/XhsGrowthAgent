"""Engagement node implementation."""

from typing import Any
from langgraph.store.base import BaseStore

from backend.agents.nodes._base import NodeResult
from backend.agents.engagement import EngagementAgent
from backend.state.schema import XHSGrowthState


_engagement = EngagementAgent()


async def engagement_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute engagement agent."""
    result = await _engagement(state, store=store)
    return NodeResult(result, "engagement").to_dict()