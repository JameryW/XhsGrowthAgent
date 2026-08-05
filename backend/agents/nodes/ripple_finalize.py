"""Ripple finalize node — reads background Ripple results from store, conditionally interrupts.

Only meaningful in RIPPLE_BACKGROUND mode. In blocking mode the strategist
already wrote ripple_prediction to state and ripple_gate already ran, so this
node is a pass-through (no store result, no interrupt).

In background mode, if the store result has not arrived yet (Ripple still
running), this node keeps ``ripple_pending=True`` and passes through — the
late-arriving result is recovered by ``ripple_late_recheck`` after
visual_designer. If the result is present, this node writes it to state and
optionally interrupts (same logic as recheck, but runs before copywriter).
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.store.base import BaseStore
from langgraph.types import interrupt

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.graph.nodes")

_VIRAL_PROB_THRESHOLD = 0.4
_PMF_SCORE_THRESHOLD = 0.5
_MAX_RESELECT_COUNT = 2


def _is_suboptimal(prediction: dict[str, Any], pmf: dict[str, Any]) -> bool:
    viral_prob = prediction.get("viral_probability", 1.0)
    pmf_score = pmf.get("pmf_score", 1.0)
    return bool(viral_prob < _VIRAL_PROB_THRESHOLD or pmf_score < _PMF_SCORE_THRESHOLD)


async def ripple_finalize_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Read background Ripple result from store; interrupt if suboptimal.

    - If store has no result yet (still running) → keep ripple_pending=True and
      pass through (ripple_late_recheck recovers the late result after visual)
    - If result is acceptable → write ripple_prediction/ripple_pmf to state
    - If suboptimal AND reselect_count < 2 → interrupt for user decision
    - If suboptimal AND reselect_count >= 2 → accept (prevent loops)
    """
    _check_cancelled(state)

    thread_id = state.get("session_id")
    if not thread_id:
        return NodeResult({}, "ripple_finalize").to_dict()

    # Blocking mode: strategist already wrote ripple_prediction to state and
    # ripple_gate already handled the decision. Pass through.
    if not state.get("ripple_pending"):
        return NodeResult({}, "ripple_finalize").to_dict()

    item = await store.aget(("ripple", thread_id), "result")
    if item is None:
        # Still running — leave ripple_pending=True so the late-recheck node
        # (after visual_designer) polls the store for the late-arriving result.
        # Late data recovery is ripple_late_recheck's job, not this node's.
        logger.info(f"Ripple background result not yet available for {thread_id}")
        return NodeResult(
            {"ripple_pending": True, "ripple_reason": "pending"},
            "ripple_finalize",
        ).to_dict()

    stored = item.value if isinstance(item.value, dict) else {}

    result: dict[str, Any] = {"ripple_pending": False}

    prediction = stored.get("ripple_prediction") or {}
    pmf = stored.get("ripple_pmf") or {}
    reason = stored.get("ripple_reason")

    if reason in ("timeout", "unreachable", "pending"):
        result["ripple_reason"] = reason
        return NodeResult(result, "ripple_finalize").to_dict()

    # Ripple succeeded — write prediction/pmf to state
    result["ripple_prediction"] = prediction
    result["ripple_pmf"] = pmf

    reselect_count = state.get("reselect_count", 0)

    if not _is_suboptimal(prediction, pmf):
        logger.info("Ripple background results acceptable, continuing")
        return NodeResult(result, "ripple_finalize").to_dict()

    if reselect_count >= _MAX_RESELECT_COUNT:
        logger.info(f"Reselect limit reached ({reselect_count}), accepting suboptimal")
        return NodeResult(result, "ripple_finalize").to_dict()

    logger.info(
        "Ripple background results suboptimal "
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
            "source": "background_finalize",
        },
    }

    decision = interrupt(interrupt_payload)
    action = "accept"
    if decision and isinstance(decision, dict):
        action = decision.get("action", "accept")

    result["ripple_decision"] = {"action": action, "source": "user"}
    if action in ("reangle", "retopic"):
        result["reselect_count"] = reselect_count + 1

    return NodeResult(result, "ripple_finalize").to_dict()
