"""Draft gate node implementation - waits for user draft confirmation."""

import logging
from typing import Any

from langgraph.store.base import BaseStore
from langgraph.types import interrupt

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.graph.nodes")


async def draft_gate_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Draft confirmation gate — always pauses for user to confirm or edit.

    If the user already submitted draft_content (via resume/submit_draft),
    skip interrupt and proceed. Otherwise, interrupt so the user can review
    the AI-generated copy and edit before continuing.

    The AI-generated copy is passed in the interrupt value as `default_draft`,
    so the frontend can pre-populate the editor.
    """
    _check_cancelled(state)

    draft_content = state.get("draft_content")
    copy_content = state.get("copy_content") or {}

    # User already submitted a draft (via submit_draft endpoint) — proceed
    if (
        draft_content
        and draft_content.get("text")
        and draft_content.get("source") != "ai_generated"
    ):
        logger.debug("User-submitted draft_content present, skipping interrupt")
        return NodeResult({
            "phase": WorkflowPhase.CREATING,
        }, "draft_gate").to_dict()

    # Build default draft from AI-generated copy for user to confirm/edit
    default_draft = {}
    if copy_content and copy_content.get("body_text"):
        default_draft = {
            "title": copy_content.get("selected_title") or "",
            "text": copy_content.get("body_text") or "",
            "hashtags": copy_content.get("hashtags") or [],
            "source": "ai_generated",
        }

    # Always interrupt — user must confirm or edit before proceeding
    logger.info("Interrupting at draft_gate for user confirmation")
    decision = interrupt({"gate": "draft", "default_draft": default_draft})

    # On resume, decision contains the draft data from submit_draft
    if decision and isinstance(decision, dict):
        logger.debug("Draft gate resumed with user decision: %s", decision.get("title", "no title"))

    return NodeResult({
        "phase": WorkflowPhase.CREATING,
    }, "draft_gate").to_dict()
