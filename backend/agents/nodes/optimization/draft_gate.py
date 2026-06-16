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
    selected_blogger = state.get("selected_blogger") or {}

    # If the user already submitted a draft (via submit_draft API), skip
    # interrupt regardless of entry path (blogger or non-blogger).
    # The API (optimization.py) writes draft_content with source != "ai_generated"
    # before resuming, so we can trust that as a user-submitted draft.
    if (
        draft_content
        and draft_content.get("text")
        and draft_content.get("source") != "ai_generated"
    ):
        logger.debug("User-submitted draft_content present, skipping interrupt")
        return NodeResult(
            {
                "phase": WorkflowPhase.CREATING,
            },
            "draft_gate",
        ).to_dict()

    # Build default draft from AI-generated copy for user to confirm/edit
    # Priority: draft_content > copy_content > shooting_plan > content_plan
    default_draft = {}
    if draft_content and draft_content.get("text"):
        # User previously submitted a draft — use it as the base for re-editing
        default_draft = {
            "title": draft_content.get("title") or "",
            "text": draft_content.get("text") or "",
            "hashtags": draft_content.get("hashtags") or [],
            "source": "ai_generated",
        }
    elif copy_content and copy_content.get("body_text"):
        default_draft = {
            "title": copy_content.get("selected_title") or "",
            "text": copy_content.get("body_text") or "",
            "hashtags": copy_content.get("hashtags") or [],
            "source": "ai_generated",
        }
    else:
        # Fallback: build from shooting_plan (blogger_gate path)
        # or from blogger_notes/content_plan when shooting_plan not yet available
        shooting_plan = state.get("shooting_plan") or {}
        has_shooting = shooting_plan.get("body_copy") or shooting_plan.get("title_candidates")
        if has_shooting:
            titles = shooting_plan.get("title_candidates") or []
            required = shooting_plan.get("required_hashtags") or []
            optional = shooting_plan.get("optional_hashtags") or []
            default_draft = {
                "title": titles[0] if titles else "",
                "text": shooting_plan.get("body_copy") or "",
                "hashtags": required + optional,
                "source": "ai_generated",
            }
        else:
            # No shooting_plan yet (blogger_gate runs before shooting_planner).
            # Build from content_plan + blogger_notes as best-effort defaults.
            content_plan = state.get("content_plan") or {}
            blogger_notes = state.get("blogger_notes") or []
            # Use first blogger note as style reference
            note = blogger_notes[0] if blogger_notes else {}
            default_draft = {
                "title": (content_plan.get("selected_topic") or note.get("title", "")),
                "text": note.get("body", ""),
                "hashtags": note.get("hashtags", []),
                "source": "ai_generated",
            }

    # Always interrupt — user must confirm or edit before proceeding
    logger.info("Interrupting at draft_gate for user confirmation")
    decision = interrupt({"gate": "draft", "default_draft": default_draft})

    # On resume, decision contains the draft data from submit_draft
    if decision and isinstance(decision, dict):
        logger.debug("Draft gate resumed with user decision: %s", decision.get("title", "no title"))

    return NodeResult(
        {
            "phase": WorkflowPhase.CREATING,
        },
        "draft_gate",
    ).to_dict()
