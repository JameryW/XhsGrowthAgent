"""Revise content node implementation - resets content for revision."""

from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState


async def revise_content_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Revise content - inject feedback for copy rewrite.

    Preserves evaluation_result.revision_hints into human_feedback.revisions so
    the copywriter can act on the evaluator's panel verdict (RQGM co-evolution:
    evaluator feedback feeds back into the writer).

    Increments revision_count on each cycle; evaluator_outcome force-approves
    after Settings().workflow.max_revision_count to prevent infinite revision loops.
    """
    _check_cancelled(state)
    # Carry evaluator revision hints into human_feedback for the copywriter
    evaluation = state.get("evaluation_result") or {}
    revision_hints: list[str] = evaluation.get("revision_hints") or []
    existing_feedback = state.get("human_feedback") or {}
    human_feedback = dict(existing_feedback)
    if revision_hints:
        human_feedback["revisions"] = list(revision_hints)

    # Clear previous copy content to trigger rewrite
    result: dict[str, Any] = {
        "copy_content": {},  # Clear, triggers rewrite
        "visual_plan": {},  # Clear, triggers redesign
        "phase": WorkflowPhase.CREATING,
        # Increment revision counter — evaluator_outcome reads this to cap loops
        "revision_count": state.get("revision_count", 0) + 1,
    }
    if human_feedback:
        result["human_feedback"] = human_feedback

    return NodeResult(result, "revise_content").to_dict()
