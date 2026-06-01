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
    """Version selection gate - user chooses A/B/C version."""
    _check_cancelled(state)
    versions = state.get("content_versions", [])
    draft = state.get("draft_content", {})
    analysis = state.get("optimization_analysis", {})

    # Prepare choice payload for frontend
    choice_payload = {
        "gate": "choice",
        "versions": [
            {
                "version_id": v.get("version_id"),
                "version_type": v.get("version_type"),
                "title": v.get("title"),
                "body_preview": v.get("body", "")[:200],
                "hashtags": v.get("hashtags", []),
                "style_suggestion": v.get("style_suggestion", ""),
                "predicted_score": v.get("predicted_score", 0),
            }
            for v in versions
        ],
        "original_draft": {
            "title": draft.get("title", ""),
            "body_preview": draft.get("text", "")[:200],
        },
        "analysis_summary": {
            "gaps_count": len(analysis.get("gaps", [])),
            "suggestions_count": len(analysis.get("suggestions", [])),
            "viral_patterns": analysis.get("viral_patterns", []),
        },
    }

    # interrupt() pauses execution, waiting for user selection
    decision = interrupt(choice_payload)

    # decision format: {"selected_version": "A/B/C", "version_id": "..."}
    selected_version_id = decision.get("version_id")

    # Find selected version from version list
    selected_version = next(
        (v for v in versions if v.get("version_id") == selected_version_id),
        None
    )

    if selected_version:
        # Write selected version content to copy_content and visual_plan
        result = {
            "selected_version": selected_version_id,
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
    else:
        # Selected version not found, write original draft as fallback
        logger.warning(f"Selected version not found: {selected_version_id}")
        result = {
            "phase": WorkflowPhase.CREATING,
            "copy_content": {
                **(state.get("copy_content") or {}),
                "selected_title": draft.get("title", ""),
            },
        }

    return NodeResult(result, "choice_gate").to_dict()