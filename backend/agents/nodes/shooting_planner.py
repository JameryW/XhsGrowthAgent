"""Shooting planner node — LangGraph node wrapping ShootingPlannerAgent."""

from __future__ import annotations

from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.nodes._base import _check_cancelled
from backend.agents.shooting_planner import ShootingPlannerAgent
from backend.state.schema import XHSGrowthState

_agent = ShootingPlannerAgent()


async def shooting_planner_node(state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
    """Generate shooting plan from parsed brief + viral references.

    Routes through BaseAgent.__call__ (not execute directly) so a failure
    returns the error state for stateful retry and gains the perf-log entry,
    matching every other node.
    """
    _check_cancelled(state)
    return await _agent(state, store=store)


__all__ = ["shooting_planner_node"]
