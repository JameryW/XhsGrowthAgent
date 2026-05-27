"""Choice gate node implementation - user selects A/B/C version."""

import logging
from typing import Any
from langgraph.store.base import BaseStore
from langgraph.types import interrupt

from xhs_growth.agents.nodes._base import NodeResult
from xhs_growth.realtime import EventBusService, EventType
from xhs_growth.state.schema import XHSGrowthState
from xhs_growth.state.enums import WorkflowPhase


logger = logging.getLogger("xhs_growth.graph.nodes")


async def choice_gate_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Version selection gate - user chooses A/B/C version."""
    versions = state.get("content_versions", [])
    draft = state.get("draft_content", {})
    analysis = state.get("optimization_analysis", {})

    # Emit choice pending event before interrupt
    thread_id = state.get("thread_id")
    EventBusService.get_instance().emit(
        EventType.WORKFLOW_DATA_UPDATED,
        thread_id=thread_id,
        payload={
            "data_type": "choice_pending",
            "data": {
                "versions": versions,
                "draft": draft,
                "analysis": analysis,
            },
        },
    )

    # Prepare choice payload for frontend
    choice_payload = {
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

    # decision is user selection result: {"selected_version": "A/B/C", "version_id": "..."}
    selected_version_id = decision.get("version_id")
    selected_version_type = decision.get("selected_version")

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
        # Selected version not found, keep original state
        logger.warning(f"Selected version not found: {selected_version_id}")
        result = {
            "phase": WorkflowPhase.CREATING,
        }

    return NodeResult(result, "choice_gate").to_dict()