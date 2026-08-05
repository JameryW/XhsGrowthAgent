"""Ripple late-recheck node — bounded poll for background Ripple result.

Background mode only. Inserted after ``visual_designer`` so copywriter+
visual (~88s) run concurrently with the background Ripple (~352s). The
node polls ``store.aget(("ripple", thread_id), "result")`` for up to
``Settings().ripple.late_recheck_timeout`` seconds, then either writes the
prediction/pmf to state, interrupts for a suboptimal result, or fails open
(does not block publish).

``ripple_finalize`` runs immediately after the strategist and leaves
``ripple_pending=True`` when the store has no result yet; this node is the
late-arriving consumer that recovers it. Reuses ``_is_suboptimal`` /
``_MAX_RESELECT_COUNT`` from :mod:`ripple_finalize` so thresholds stay in
one place.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langgraph.store.base import BaseStore
from langgraph.types import interrupt

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.agents.nodes.ripple_finalize import _MAX_RESELECT_COUNT, _is_suboptimal
from backend.config.settings import Settings
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.graph.nodes")

_POLL_INTERVAL_SECONDS = 5.0


async def ripple_late_recheck_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Poll the store for a late-arriving background Ripple result.

    - ``ripple_pending=False`` (blocking mode or finalize already handled) → pass-through
    - bounded poll until result arrives or ``late_recheck_timeout`` elapses
    - success + acceptable → write prediction/pmf, clear pending, pass-through
    - success + suboptimal + reselect<2 → ``interrupt(gate="ripple")`` for user decision
    - success + suboptimal + reselect>=2 → accept (loop guard)
    - timeout/unreachable/pending reason, or poll cap exceeded → fail open
    """
    _check_cancelled(state)

    # Blocking mode or finalize already consumed the result → nothing to recheck.
    if not state.get("ripple_pending"):
        return NodeResult({}, "ripple_late_recheck").to_dict()

    thread_id = state.get("session_id")
    if not thread_id:
        return NodeResult({}, "ripple_late_recheck").to_dict()

    cap = Settings().ripple.late_recheck_timeout
    deadline = asyncio.get_event_loop().time() + cap
    item: Any = None

    while True:
        item = await store.aget(("ripple", thread_id), "result")
        if item is not None:
            break
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        await asyncio.sleep(min(_POLL_INTERVAL_SECONDS, remaining))

    if item is None:
        # Ripple still running past the cap — fail open, don't block publish.
        logger.info(f"Ripple late-recheck timed out for {thread_id}, failing open")
        return NodeResult(
            {"ripple_pending": False, "ripple_reason": "pending"},
            "ripple_late_recheck",
        ).to_dict()

    stored = item.value if isinstance(item.value, dict) else {}

    result: dict[str, Any] = {"ripple_pending": False}

    prediction = stored.get("ripple_prediction") or {}
    pmf = stored.get("ripple_pmf") or {}
    reason = stored.get("ripple_reason")

    if reason in ("timeout", "unreachable", "pending"):
        result["ripple_reason"] = reason
        return NodeResult(result, "ripple_late_recheck").to_dict()

    result["ripple_prediction"] = prediction
    result["ripple_pmf"] = pmf

    reselect_count = state.get("reselect_count", 0)

    if not _is_suboptimal(prediction, pmf):
        logger.info("Ripple late-recheck results acceptable, continuing")
        return NodeResult(result, "ripple_late_recheck").to_dict()

    if reselect_count >= _MAX_RESELECT_COUNT:
        logger.info(f"Reselect limit reached ({reselect_count}), accepting suboptimal")
        return NodeResult(result, "ripple_late_recheck").to_dict()

    logger.info(
        "Ripple late-recheck results suboptimal "
        f"(viral={prediction.get('viral_probability', 0):.2f}, "
        f"pmf={pmf.get('pmf_score', 0):.2f}), interrupting for user decision"
    )

    interrupt_payload = {
        "gate": "ripple",
        "ripple_summary": {
            "viral_probability": prediction.get("viral_probability", 0),
            "pmf_score": pmf.get("pmf_score", 0),
            "reselect_count": reselect_count,
            "max_reselect": _MAX_RESELECT_COUNT,
            "source": "late_recheck",
        },
    }

    decision = interrupt(interrupt_payload)
    action = "accept"
    if decision and isinstance(decision, dict):
        action = decision.get("action", "accept")

    result["ripple_decision"] = {"action": action, "source": "user"}
    if action in ("reangle", "retopic"):
        result["reselect_count"] = reselect_count + 1

    return NodeResult(result, "ripple_late_recheck").to_dict()
