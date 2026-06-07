"""Blogger gate node — interrupt for user to select a blogger."""

import logging
from typing import Any

from langgraph.store.base import BaseStore
from langgraph.types import interrupt

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.graph.nodes")


async def blogger_gate_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Blogger selection gate — pauses for user to select a blogger from candidates.

    With interrupt_before, this node only runs on resume. interrupt(None)
    receives the resume value (the user's blogger selection).

    If no candidates exist, skip interrupt and proceed.
    On resume, fetch the selected blogger's top notes.

    Selection format (from Command(resume=selection)):
      {"user_id": "...", "nickname": "..."}  — selected blogger
      {"skip": true}                         — user skipped selection
    """
    _check_cancelled(state)

    candidates = state.get("blogger_candidates", [])

    # No candidates — skip gate
    if not candidates:
        logger.info("No blogger candidates, skipping blogger_gate")
        return NodeResult(
            {
                "phase": WorkflowPhase.CREATING,
            },
            "blogger_gate",
        ).to_dict()

    # Receive user selection from Command(resume=selection)
    decision = interrupt(None)

    # User skipped selection
    if not decision or (isinstance(decision, dict) and decision.get("skip")):
        logger.info("User skipped blogger selection")
        return NodeResult(
            {
                "selected_blogger": {},
                "blogger_notes": [],
                "phase": WorkflowPhase.CREATING,
            },
            "blogger_gate",
        ).to_dict()

    # User selected a blogger — fetch their top notes
    selected_user_id = decision.get("user_id", "") if isinstance(decision, dict) else ""
    if not selected_user_id:
        logger.warning("No user_id in blogger selection, skipping note fetch")
        return NodeResult(
            {
                "selected_blogger": decision if isinstance(decision, dict) else {},
                "blogger_notes": [],
                "phase": WorkflowPhase.CREATING,
            },
            "blogger_gate",
        ).to_dict()

    note_limit = state.get("blogger_note_limit", 20)
    blogger_notes = await _fetch_blogger_notes(state, selected_user_id, note_limit)

    selected = decision if isinstance(decision, dict) else {"user_id": selected_user_id}
    logger.info(
        f"User selected blogger: {selected.get('nickname', selected_user_id)}, "
        f"fetched {len(blogger_notes)} notes"
    )

    return NodeResult(
        {
            "selected_blogger": selected,
            "blogger_notes": blogger_notes,
            "phase": WorkflowPhase.CREATING,
        },
        "blogger_gate",
    ).to_dict()


async def _fetch_blogger_notes(
    state: XHSGrowthState,
    user_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Fetch a blogger's top notes sorted by engagement."""
    try:
        from backend.services.xhs_client import XHSClient

        cookie = state.get("xhs_cookie", "")
        client = XHSClient(cookie=cookie) if cookie else None
        if not client or not client._http:
            logger.warning("No XHS client available for fetching blogger notes")
            return []

        raw_notes = await client.get_user_notes(user_id=user_id, limit=limit)
        await client.close()

        # Sort by engagement (likes + collects + comments) descending
        notes_with_engagement = []
        for note in raw_notes:
            likes = note.get("like_count", 0)
            collects = note.get("collect_count", 0)
            comments = note.get("comment_count", 0)
            total = likes + collects + comments
            notes_with_engagement.append((total, note))

        notes_with_engagement.sort(key=lambda x: x[0], reverse=True)

        # Take top N and format as BloggerNote
        result = []
        for total_eng, note in notes_with_engagement[:limit]:
            likes = note.get("like_count", 0)
            collects = note.get("collect_count", 0)
            comments = note.get("comment_count", 0)
            engagement_rate = round(total_eng / max(likes, 1), 2) if likes else 0.0

            result.append(
                {
                    "note_id": note.get("note_id", note.get("id", "")),
                    "title": note.get("display_title", note.get("title", "")),
                    "body": note.get("desc", note.get("body", "")),
                    "hashtags": note.get("tag_list", []),
                    "likes": likes,
                    "collects": collects,
                    "comments": comments,
                    "engagement_rate": engagement_rate,
                    "cover_url": (
                        note.get("cover", {}).get("url", "")
                        if isinstance(note.get("cover"), dict)
                        else ""
                    ),
                }
            )

        return result

    except Exception as e:
        logger.warning(f"Failed to fetch blogger notes: {e}")
        return []
