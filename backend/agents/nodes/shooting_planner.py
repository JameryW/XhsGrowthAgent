"""Shooting planner node — LangGraph node wrapping ShootingPlannerAgent."""

from __future__ import annotations

from langgraph.store.base import BaseStore

from backend.agents.nodes._base import _check_cancelled
from backend.agents.shooting_planner import ShootingPlannerAgent
from backend.state.schema import XHSGrowthState

_agent = ShootingPlannerAgent()


async def shooting_planner_node(
    state: XHSGrowthState, store: BaseStore
) -> dict:
    """Generate shooting plan from parsed brief + viral references."""
    _check_cancelled(state)
    result = await _agent.execute(state, store)
    result["current_agent"] = "shooting_planner"
    return result


__all__ = ["shooting_planner_node"]
