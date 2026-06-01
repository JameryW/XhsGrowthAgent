"""Draft gate node implementation - waits for user draft submission."""

import logging
from typing import Any

from langgraph.store.base import BaseStore
from langgraph.types import interrupt

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.graph.nodes")


async def draft_gate_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Draft submission gate - waits for user draft via submit_draft endpoint.

    This node checks if draft_content exists in state:
    - If draft_content exists: proceed to viral_matcher (optimization flow)
    - If no draft_content: interrupt and wait for user submission

    The interrupt is resumed via Command(resume=draft_data) from submit_draft endpoint.
    """
    _check_cancelled(state)

    draft_content = state.get("draft_content")
    copy_content = state.get("copy_content") or {}

    # If draft already exists, skip interrupt and proceed
    if draft_content and draft_content.get("text"):
        logger.debug("Draft content already present, skipping draft_gate interrupt")
        return NodeResult({
            "phase": WorkflowPhase.CREATING,
        }, "draft_gate").to_dict()

    # Generated copy is a valid default draft. The user can still edit it from
    # the UI, but the workflow should not require retyping AI-generated copy.
    if copy_content.get("body_text"):
        logger.debug("Using generated copy_content as default draft")
        return NodeResult({
            "phase": WorkflowPhase.CREATING,
            "draft_content": {
                "title": copy_content.get("selected_title") or "",
                "text": copy_content.get("body_text") or "",
                "hashtags": copy_content.get("hashtags") or [],
            },
        }, "draft_gate").to_dict()

    # No draft - interrupt and wait for user submission
    # interrupt(None) pauses the graph until resumed via Command(resume=draft_data)
    # The resume value is the draft data submitted via /api/optimization/draft endpoint
    logger.info("No draft content found, interrupting at draft_gate")
    decision = interrupt({"gate": "draft"})

    # On resume, decision contains the draft data from submit_draft
    # The submit_draft endpoint writes draft_content to state before resuming,
    # so we just need to signal that we're proceeding
    if decision:
        logger.debug("Draft gate resumed with decision: %s", decision.get("title", "no title"))

    return NodeResult({
        "phase": WorkflowPhase.CREATING,
    }, "draft_gate").to_dict()
