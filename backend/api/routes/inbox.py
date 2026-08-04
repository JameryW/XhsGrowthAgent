"""Inbox API route — aggregate all at-gate threads for the active account.

A single endpoint that lists every workflow paused at a human-decision gate
(review / ripple / choice / draft / blogger), with a per-gate data snapshot.
The user reviews them in one place; submit still goes through the original
per-gate submit endpoints.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request

from backend.api.account_scope import resolve_required_account_id
from backend.api.deps import get_current_user
from backend.api.responses import ApiResponse, success
from backend.db.pool import is_pool_ready
from backend.db.workflows import list_workflows as db_list

logger = logging.getLogger("xhs_growth.api.inbox")

router = APIRouter()

# Gate node names that appear in state.next when paused via interrupt_before.
# ripple_gate / blogger_gate also pause via dynamic interrupt() (gate field in
# the interrupt payload), so detection covers both styles.
_GATE_NODES = ("review_gate", "ripple_gate", "choice_gate", "draft_gate", "blogger_gate")


def _detect_gate(state: Any) -> str | None:
    """Identify which gate a paused thread is sitting at.

    Returns one of: review, ripple, choice, draft, blogger — or None when the
    thread is not at a decision gate (running / completed / error / etc.).
    Handles both interrupt_before (gate name in state.next) and dynamic
    interrupt() (gate field in snapshot.interrupts payload).
    """
    next_nodes = tuple(state.next or ())
    gate_to_name = {
        "review_gate": "review",
        "ripple_gate": "ripple",
        "choice_gate": "choice",
        "draft_gate": "draft",
        "blogger_gate": "blogger",
    }
    for node, name in gate_to_name.items():
        if node in next_nodes:
            return name
    # Dynamic interrupt() — gate type carried in the interrupt payload
    for intr in state.interrupts or ():
        val = getattr(intr, "value", None)
        if isinstance(val, dict):
            gate = val.get("gate")
            if gate in gate_to_name.values():
                return gate
    return None


def _gate_snapshot(values: dict[str, Any], gate: str) -> dict[str, Any]:
    """Build a minimal data snapshot for the given gate type.

    Mirrors the extraction already done in review.py's get_pending_review /
    get_pending_ripple_decision — kept minimal so the inbox payload stays small.
    """
    if gate == "review":
        copy_content = values.get("copy_content") or {}
        visual_plan = values.get("visual_plan") or {}
        return {
            "title": copy_content.get("selected_title", ""),
            "body_text": copy_content.get("body_text", ""),
            "hashtags": copy_content.get("hashtags", []),
            "image_paths": visual_plan.get("image_paths", []),
            "content_versions": values.get("content_versions") or [],
        }
    if gate == "ripple":
        return {
            "ripple_prediction": values.get("ripple_prediction") or {},
            "ripple_pmf": values.get("ripple_pmf") or {},
            "ripple_reason": values.get("ripple_reason", ""),
            "reselect_count": values.get("reselect_count", 0),
        }
    if gate == "choice":
        return {
            "content_versions": values.get("content_versions") or [],
        }
    if gate == "draft":
        return {
            "copy_content": values.get("copy_content") or {},
        }
    if gate == "blogger":
        return {
            "blogger_candidates": values.get("blogger_candidates") or [],
            "selected_blogger": values.get("selected_blogger") or {},
            "blogger_notes": values.get("blogger_notes") or [],
        }
    return {}


@router.get("/inbox")
async def get_inbox(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """List all at-gate threads for the active owned account.

    Reads workflows from DB for the active account, then probes each via
    graph.aget_state to detect which (if any) gate it's paused at. Threads
    not at a gate are skipped. Empty list when there are none (never 500).
    """
    graph = request.app.state.graph

    try:
        account_id = await resolve_required_account_id(str(user["id"]), None)
    except Exception:
        logger.debug("resolve inbox account failed", exc_info=True)
        return success(data={"inbox": [], "account_id": None})

    # No account configured or DB unavailable → empty inbox, not an error.
    if not account_id or not is_pool_ready():
        return success(data={"inbox": [], "account_id": account_id})

    rows, _total = await db_list(account_id=account_id, limit=100, offset=0)

    # Fetch checkpoint states concurrently — each aget_state is a separate
    # checkpointer round trip; a serial loop made inbox latency scale with row
    # count. _safe_aget preserves the per-row try/except skip from the loop.
    async def _safe_aget(thread_id: str) -> Any | None:
        try:
            return await graph.aget_state({"configurable": {"thread_id": thread_id}})
        except Exception:
            logger.debug("aget_state failed for %s", thread_id, exc_info=True)
            return None

    states = await asyncio.gather(*(_safe_aget(row.thread_id) for row in rows))

    inbox: list[dict[str, Any]] = []
    for row, state in zip(rows, states, strict=True):
        thread_id = row.thread_id
        if state is None:
            continue

        # Skip threads with no live checkpoint (created but not started, or
        # already terminal in DB without a graph snapshot).
        if not state.values or state.values.get("session_id") is None:
            continue

        gate = _detect_gate(state)
        if gate is None:
            continue

        inbox.append(
            {
                "thread_id": thread_id,
                "gate": gate,
                "phase": state.values.get("phase", "unknown"),
                "created_at": row.created_at,
                "label": row.label,
                "snapshot": _gate_snapshot(state.values, gate),
            }
        )

    return success(data={"inbox": inbox, "account_id": account_id})
