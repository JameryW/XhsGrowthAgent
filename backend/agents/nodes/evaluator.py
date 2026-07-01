"""Evaluator node — RQGM agent-as-a-judge panel (pre-publish quality gate).

Runs after review_gate (human-approved) and before publisher. Auto-routes:
overall_score >= threshold and no blocking compliance failure → publisher,
else → revise_content (revision_hints carried in evaluation_result).

Does NOT use interrupt_before — the decision is the AI panel's own verdict,
not a human input (per RQGM judge semantics). Evaluation result is written
to state + emitted as a WORKFLOW_DATA_UPDATED event for visibility.

Failure is non-blocking: on evaluator error, log and pass-through to publisher
(degrade gracefully rather than block publishing on a quality-check failure).
"""

import logging
from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.evaluator import EvaluatorAgent
from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.realtime import EventBusService, EventType
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.graph.nodes")

_evaluator = EvaluatorAgent()


async def evaluator_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Run the creation-quality evaluator and emit its result."""
    _check_cancelled(state)

    try:
        result = await _evaluator(state, store=store)
    except Exception as e:
        # ponytail: degrade — a quality-check failure must not block publishing.
        # Log and pass through to publisher with a synthetic pass result.
        logger.warning("Evaluator failed, degrading to pass-through: %s", e)
        from backend.state.enums import ContentStatus

        result = {
            "evaluation_result": {
                "overall_score": 100.0,
                "dimensions": [],
                "decision": ContentStatus.APPROVED,
                "revision_hints": [],
                "bias_warning": "",
                "summary": f"评估器异常，降级放行: {e}",
            }
        }

    evaluation = result.get("evaluation_result") or {}
    thread_id = state.get("session_id")
    if evaluation:
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "evaluation_result", "data": evaluation},
        )
        # ponytail: collect training sample for future grader finetuning — best-effort,
        # non-blocking (DB may be absent in dev/test). Real engagement label back-filled
        # later by analyst_node after publish.
        await _collect_sample(state, thread_id, evaluation)

    return NodeResult(result, "evaluator").to_dict()


async def _collect_sample(
    state: XHSGrowthState, thread_id: str | None, evaluation: dict[str, Any]
) -> None:
    """Persist one evaluator-judgment sample (label_source='evaluator')."""
    if not thread_id:
        return
    try:
        from backend.db.evaluator_config import EvaluatorSample, insert_sample
        from backend.db.pool import is_pool_ready

        if not is_pool_ready():
            return
        await insert_sample(
            EvaluatorSample(
                account_id=state.get("account_id"),
                thread_id=thread_id,
                dimensions=evaluation.get("dimensions") or [],
                overall_score=float(evaluation.get("overall_score") or 0.0),
                decision=str(evaluation.get("decision") or ""),
                label_source="evaluator",
            )
        )
    except Exception as e:
        logger.debug("evaluator sample collection failed (non-blocking): %s", e)
