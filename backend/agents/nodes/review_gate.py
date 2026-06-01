"""Review gate node implementation - human-in-the-loop checkpoint."""

import logging
from typing import Any

from langgraph.store.base import BaseStore
from langgraph.types import interrupt

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.graph.nodes")


async def review_gate_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Human-in-the-loop review gate - graph interrupts before this node."""
    _check_cancelled(state)
    copy = state.get("copy_content", {})
    visual = state.get("visual_plan", {})
    plan = state.get("content_plan", {})

    review_payload = {
        "gate": "review",
        "topic": plan.get("selected_topic", ""),
        "titles": copy.get("title_candidates", []),
        "body_preview": copy.get("body_text", "")[:200],
        "cover_prompt": visual.get("cover_prompt", ""),
        "hashtags": copy.get("hashtags", []),
    }

    # interrupt() pauses execution, sends payload to caller
    decision = interrupt(review_payload)

    # decision format: {"decision": "approved/needs_revision/rejected",
    #                    "comments": "...", "revisions": [...]}
    result = {
        "human_feedback": decision,
        "phase": WorkflowPhase.REVIEWING,
    }

    return NodeResult(result, "review_gate").to_dict()