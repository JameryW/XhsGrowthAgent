"""Engagement node implementation."""

from typing import Any
from langgraph.store.base import BaseStore

from xhs_growth.agents.nodes._base import NodeResult
from xhs_growth.agents.engagement import EngagementAgent
from xhs_growth.state.schema import XHSGrowthState


_engagement = EngagementAgent()


async def engagement_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute engagement agent."""
    result = await _engagement(state, store=store)
    return NodeResult(result, "engagement").to_dict()