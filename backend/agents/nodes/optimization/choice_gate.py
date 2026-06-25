"""Choice gate node implementation - user selects style or A/B/C version.

Two layers of selection:
1. Style selection (from copywriter multi-style variants): writes draft_content
   + style_selected=True so version_generator can generate A/B/C based on it.
2. Version selection (from version_generator A/B/C): writes final copy_content
   + visual_plan, clears style_selected.
"""

import logging
from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.graph.nodes")


async def choice_gate_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Version/style selection gate.

    With interrupt_before, this node only runs on resume. The user's selection
    (selected_version) is written to state by select_version via aupdate_state
    before ainvoke(None) advances the graph.

    Two layers:
    - Style selection (style_selected not yet True): writes draft_content for
      version_generator, sets style_selected=True, clears content_versions.
    - Version selection (style_selected=True): writes final copy_content +
      visual_plan, clears style_selected.
    """
    _check_cancelled(state)
    versions = state.get("content_versions", [])
    draft = state.get("draft_content", {})
    style_selected = state.get("style_selected", False)

    # Auto-select when only 1 version
    if len(versions) <= 1:
        selected = versions[0] if versions else None
        title = (selected or draft).get("title", "")
        result: dict[str, Any] = {
            "copy_content": {
                **(state.get("copy_content") or {}),
                "selected_title": title,
            },
            "phase": WorkflowPhase.CREATING,
        }
        # If this was style selection, also write draft_content
        if not style_selected and selected:
            result["draft_content"] = {
                "title": selected.get("title", ""),
                "text": selected.get("body", ""),
                "hashtags": selected.get("hashtags", []),
                "style_suggestion": selected.get("style_suggestion", ""),
            }
            result["style_selected"] = True
            result["content_versions"] = []
        return NodeResult(result, "choice_gate").to_dict()

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

    # Style selection (first layer): write draft_content for version_generator
    if not style_selected:
        result = {
            "selected_version": found_version.get("version_id"),
            "copy_content": {
                **(state.get("copy_content") or {}),
                "selected_title": found_version.get("title", ""),
                "title_candidates": [found_version.get("title", "")],
                "body_text": found_version.get("body", ""),
                "hashtags": found_version.get("hashtags", []),
                "tone": found_version.get("tone", ""),
            },
            "draft_content": {
                "title": found_version.get("title", ""),
                "text": found_version.get("body", ""),
                "hashtags": found_version.get("hashtags", []),
                "style_suggestion": found_version.get("style_suggestion", ""),
            },
            "style_selected": True,
            "content_versions": [],  # Clear so version_generator can write new ones
            "phase": WorkflowPhase.CREATING,
        }
    else:
        # Version selection (second layer): write final copy_content + visual_plan
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
            "style_selected": False,  # Reset for potential future use
            "phase": WorkflowPhase.CREATING,
        }

    return NodeResult(result, "choice_gate").to_dict()
