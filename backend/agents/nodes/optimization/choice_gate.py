"""Choice gate node implementation - user selects A/B/C version."""

import logging
from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.graph.nodes")


async def choice_gate_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Version selection gate — user chooses A/B/C version.

    With interrupt_before, this node only runs on resume. The user's selection
    (selected_version) is written to state by select_version via aupdate_state
    before ainvoke(None) advances the graph.

    When there is only 1 version, auto-select it (no user input needed).
    Always writes selected_title into copy_content.
    """
    _check_cancelled(state)
    versions = state.get("content_versions", [])
    draft = state.get("draft_content", {})

    # Auto-select when only 1 version
    if len(versions) <= 1:
        selected = versions[0] if versions else None
        title = (selected or draft).get("title", "")
        return NodeResult(
            {
                "copy_content": {
                    **(state.get("copy_content") or {}),
                    "selected_title": title,
                },
                "phase": WorkflowPhase.CREATING,
            },
            "choice_gate",
        ).to_dict()

    # Multiple versions - read user selection from state
    # (written by select_version API via aupdate_state)
    selected_version_id = state.get("selected_version")

    # Find selected version from version list
    found_version = next(
        (v for v in versions if v.get("version_id") == selected_version_id),
        None,
    )

    # Fallback to first version if selection is invalid or missing
    if found_version is None:
        logger.warning("Selected version not found or missing, falling back to first version")
        found_version = versions[0]

    # Always write selected_title into copy_content
    result = {
        "selected_version": found_version.get("version_id"),
        "copy_content": {
            "selected_title": found_version.get("title", ""),
            "title_candidates": [found_version.get("title", "")],
            "body_text": found_version.get("body", ""),
            "hashtags": found_version.get("hashtags", []),
            "tone": found_version.get("tone", ""),
        },
        "visual_plan": {
            "cover_prompt": found_version.get("style_suggestion", ""),
            "style": found_version.get("visual_style", ""),
            "color_palette": found_version.get("color_palette", {}),
        },
        "phase": WorkflowPhase.CREATING,
    }

    return NodeResult(result, "choice_gate").to_dict()
