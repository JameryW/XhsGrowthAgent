"""Choice gate node implementation - user selects A/B/C version."""

import logging
from typing import Any

from langgraph.store.base import BaseStore
from langgraph.types import interrupt

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.graph.nodes")


async def choice_gate_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Version selection gate - user chooses A/B/C version.

    With interrupt_before, this node only runs on resume. interrupt(None)
    simply receives the resume value (the user's selection).

    When there is only 1 version, auto-select it (skip interrupt).
    Always writes selected_title into copy_content.
    """
    _check_cancelled(state)
    versions = state.get("content_versions", [])
    draft = state.get("draft_content", {})

    # Auto-select when only 1 version
    if len(versions) <= 1:
        selected = versions[0] if versions else None
        title = (selected or draft).get("title", "")
        return NodeResult({
            "copy_content": {
                **(state.get("copy_content") or {}),
                "selected_title": title,
            },
            "phase": WorkflowPhase.CREATING,
        }, "choice_gate").to_dict()

    # Multiple versions - receive user selection from Command(resume=choice)
    # choice format: {"version_id": "..."} or {"selected_version": "A/B/C", "version_id": "..."}
    decision = interrupt(None)

    selected_version_id = decision.get("version_id") if decision else None

    # Find selected version from version list
    selected_version = next(
        (v for v in versions if v.get("version_id") == selected_version_id),
        None,
    )

    # Fallback to first version if selection is invalid or missing
    if selected_version is None:
        logger.warning("Selected version not found or missing, falling back to first version")
        selected_version = versions[0]

    # Always write selected_title into copy_content
    result = {
        "selected_version": selected_version.get("version_id"),
        "copy_content": {
            "selected_title": selected_version.get("title", ""),
            "title_candidates": [selected_version.get("title", "")],
            "body_text": selected_version.get("body", ""),
            "hashtags": selected_version.get("hashtags", []),
            "tone": selected_version.get("tone", ""),
        },
        "visual_plan": {
            "cover_prompt": selected_version.get("style_suggestion", ""),
            "style": selected_version.get("visual_style", ""),
            "color_palette": selected_version.get("color_palette", {}),
        },
        "phase": WorkflowPhase.CREATING,
    }

    return NodeResult(result, "choice_gate").to_dict()
