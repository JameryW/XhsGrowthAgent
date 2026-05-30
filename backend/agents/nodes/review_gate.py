"""Review gate node implementation - human-in-the-loop checkpoint."""

import logging
from typing import Any
from langgraph.store.base import BaseStore
from langgraph.types import interrupt

from backend.agents.nodes._base import NodeResult
from backend.realtime import EventBusService, EventType
from backend.state.schema import XHSGrowthState
from backend.state.enums import WorkflowPhase, ContentStatus


logger = logging.getLogger("xhs_growth.graph.nodes")


async def review_gate_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Human-in-the-loop review gate - graph interrupts before this node."""
    copy = state.get("copy_content", {})
    visual = state.get("visual_plan", {})
    plan = state.get("content_plan", {})

    # Emit review pending event before interrupt
    thread_id = state.get("session_id")
    EventBusService.get_instance().emit(
        EventType.REVIEW_PENDING,
        thread_id=thread_id,
        payload={
            "content_plan": plan,
            "copy_content": copy,
            "visual_plan": visual,
        },
    )

    review_payload = {
        "topic": plan.get("selected_topic", ""),
        "titles": copy.get("title_candidates", []),
        "body_preview": copy.get("body_text", "")[:200],
        "cover_prompt": visual.get("cover_prompt", ""),
        "hashtags": copy.get("hashtags", []),
    }

    # interrupt() pauses execution, sends payload to caller
    decision = interrupt(review_payload)

    # decision is human review result: {"decision": "approved/needs_revision/rejected", "comments": "...", "revisions": [...]}
    # Handle both enum and string values for compatibility
    decision_value = decision.get("decision")
    result = {
        "human_feedback": decision,
        "phase": WorkflowPhase.REVIEWING,
    }

    return NodeResult(result, "review_gate").to_dict()