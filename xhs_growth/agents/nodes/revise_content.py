"""Revise content node implementation - resets content for revision."""

from typing import Any
from langgraph.store.base import BaseStore

from xhs_growth.agents.nodes._base import NodeResult
from xhs_growth.state.schema import XHSGrowthState
from xhs_growth.state.enums import WorkflowPhase


async def revise_content_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Revise content - inject human feedback for copy rewrite."""
    feedback = state.get("human_feedback", {})
    revisions = feedback.get("revisions", [])

    # Clear previous copy content to trigger rewrite
    result = {
        "copy_content": {},  # Clear, triggers rewrite
        "visual_plan": {},   # Clear, triggers redesign
        "phase": WorkflowPhase.CREATING,
    }

    return NodeResult(result, "revise_content").to_dict()