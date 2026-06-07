"""Ripple gate node — conditional interrupt when Ripple results are suboptimal."""

import logging
from typing import Any

from langgraph.store.base import BaseStore
from langgraph.types import interrupt

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.graph.nodes")

# Thresholds for triggering the gate interrupt
_VIRAL_PROB_THRESHOLD = 0.4
_PMF_SCORE_THRESHOLD = 0.5
_MAX_RESELECT_COUNT = 2


def _is_ripple_suboptimal(state: XHSGrowthState) -> bool:
    """Check if Ripple results are below acceptable thresholds."""
    prediction = state.get("ripple_prediction") or {}
    pmf = state.get("ripple_pmf") or {}

    # If Ripple was unavailable/timeout, don't gate — let it continue
    if state.get("ripple_reason") in ("timeout", "unreachable"):
        return False

    viral_prob = prediction.get("viral_probability", 1.0)
    pmf_score = pmf.get("pmf_score", 1.0)

    return viral_prob < _VIRAL_PROB_THRESHOLD or pmf_score < _PMF_SCORE_THRESHOLD


async def ripple_gate_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Conditional gate after Ripple analysis — interrupts only when results are suboptimal.

    Flow:
    1. If Ripple results are good (viral_prob >= 0.4 AND pmf >= 0.5), auto-accept → copywriter
    2. If Ripple results are suboptimal AND reselect_count < 2, interrupt for user decision
    3. If reselect_count >= 2, auto-accept (prevent infinite loops)

    Decision format (from Command(resume=decision)):
      {"action": "accept"}     — continue to copywriter
      {"action": "reangle"}   — re-run content_strategist with same trend data
      {"action": "retopic"}   — go back to trend_scout for new trends
    """
    _check_cancelled(state)

    reselect_count = state.get("reselect_count", 0)

    # Auto-accept if results are good or reselect limit reached
    if not _is_ripple_suboptimal(state):
        logger.info("Ripple results are acceptable, auto-accepting")
        return NodeResult({
            "ripple_decision": {"action": "accept", "source": "auto"},
            "phase": WorkflowPhase.CREATING,
        }, "ripple_gate").to_dict()

    if reselect_count >= _MAX_RESELECT_COUNT:
        logger.info(
            f"Reselect limit reached ({reselect_count}), auto-accepting"
        )
        return NodeResult({
            "ripple_decision": {"action": "accept", "source": "auto_max_reselect"},
            "phase": WorkflowPhase.CREATING,
        }, "ripple_gate").to_dict()

    # Results are suboptimal and user hasn't exhausted reselects — interrupt
    prediction = state.get("ripple_prediction") or {}
    pmf = state.get("ripple_pmf") or {}

    logger.info(
        f"Ripple results suboptimal (viral={prediction.get('viral_probability', 0):.2f}, "
        f"pmf={pmf.get('pmf_score', 0):.2f}), interrupting for user decision"
    )

    interrupt_payload = {
        "gate": "ripple",
        "ripple_summary": {
            "viral_probability": prediction.get("viral_probability", 0),
            "pmf_score": pmf.get("pmf_score", 0),
            "reselect_count": reselect_count,
            "max_reselect": _MAX_RESELECT_COUNT,
        },
    }

    decision = interrupt(interrupt_payload)

    action = "accept"
    if decision and isinstance(decision, dict):
        action = decision.get("action", "accept")

    # Map action to next phase
    if action == "reangle":
        phase = WorkflowPhase.PLANNING
    elif action == "retopic":
        phase = WorkflowPhase.SCOUTING
    else:
        phase = WorkflowPhase.CREATING

    result = {
        "ripple_decision": {"action": action, "source": "user"},
        "phase": phase,
    }

    # Increment reselect count for reangle/retopic
    if action in ("reangle", "retopic"):
        result["reselect_count"] = reselect_count + 1

    return NodeResult(result, "ripple_gate").to_dict()
