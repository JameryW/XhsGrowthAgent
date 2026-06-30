"""Revise content node implementation - resets content for revision."""

from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState


async def revise_content_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Revise content - inject human feedback for copy rewrite."""
    _check_cancelled(state)
    # Clear previous copy content to trigger rewrite
    result = {
        "copy_content": {},  # Clear, triggers rewrite
        "visual_plan": {},  # Clear, triggers redesign
        "phase": WorkflowPhase.CREATING,
    }

    return NodeResult(result, "revise_content").to_dict()
