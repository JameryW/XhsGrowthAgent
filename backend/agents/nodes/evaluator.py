"""Evaluator node — RQGM agent-as-a-judge panel (pre-publish quality gate).

Runs after review_gate (human-approved) and before publisher. Auto-routes:
overall_score >= threshold and no blocking compliance failure → publisher,
else → revise_content (revision_hints carried in evaluation_result).

Does NOT use interrupt_before — the decision is the AI panel's own verdict,
not a human input (per RQGM judge semantics). Evaluation result is written
to state + emitted as a WORKFLOW_DATA_UPDATED event for visibility.

Failure semantics (P0-W5, task 09-11-p0-correctness-fixes): a degraded or
decision-less evaluation — and a compliance/policy rejection at the revision
cap — is fail-CLOSED: the router ends the run (__end__) and this node parks
the workflow in the existing paused phase for the human channel. It must
never silently pass through to the publisher. Quality-only revisions keep
the pre-existing revise/force-publish loop.
"""

import logging
from typing import Any, cast

from langgraph.store.base import BaseStore

from backend.agents.evaluator import EvaluatorAgent
from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.graph.routers import (
    PAUSE_REASON_EVALUATOR_FAIL_CLOSED,
    evaluator_requires_human,
)
from backend.realtime import EventBusService, EventType
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.graph.nodes")

_evaluator = EvaluatorAgent()


async def evaluator_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Run the creation-quality evaluator and emit its result.

    P0-W5 (fail-closed quality gate): a degraded / decision-less evaluation or
    a compliance/policy rejection must NOT silently reach the publisher. The
    evaluator_gate router ends the run for those cases (__end__); this node
    additionally parks the workflow in the existing PAUSED phase so
    derive_status surfaces the (frontend-handled) "paused" status and the human
    can continue via the existing resume/review channels.
    """
    _check_cancelled(state)

    result = await _evaluator(state, store=store)

    # Degrade on failure: BaseAgent.__call__ returns an error state (phase=ERROR,
    # error, retry_count) instead of raising (prd 07-07 stateful retry). Detect
    # the error state (no evaluation_result key) and replace with an explicit
    # degraded result.  A failure must remain non-blocking for the *creation*
    # flow, but must never look like a successful 100/approved evaluation in
    # analytics/KPI — and (P0-W5) must never auto-publish.
    if "evaluation_result" not in result:
        error = result.get("error", "unknown evaluator failure")
        logger.warning("Evaluator failed, degrading to an explicit fail-closed result: %s", error)
        result = {
            "evaluation_result": {
                "overall_score": None,
                "dimensions": [],
                "decision": None,
                "status": "degraded",
                "degraded": True,
                "coverage": {
                    "weighted_ratio": 0.0,
                    "available": [],
                    "unavailable": [],
                    "required": ["copywriting", "compliance"],
                    "required_available": False,
                },
                "revision_hints": [],
                "bias_warning": "",
                "summary": f"评估器异常，评估未完成: {error}",
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

    # P0-W5 human channel: mirror the router's fail-closed decision (shared
    # single source of truth) and mark the workflow paused WITH A REASON, so
    # POST /resume can tell this pause apart from a user pause and demand an
    # explicit human decision instead of restarting the whole pipeline. The
    # router reads the merged state, so node and router stay consistent by
    # construction — the marker uses the very same predicate value.
    merged = {**state, **result}
    if evaluator_requires_human(cast("XHSGrowthState", merged)):
        result["phase"] = WorkflowPhase.PAUSED
        result["pause_reason"] = PAUSE_REASON_EVALUATOR_FAIL_CLOSED
        logger.warning(
            "Evaluator gate fail-closed (degraded/compliance) — parking workflow %s "
            "as paused for human review instead of publishing",
            thread_id,
        )
    else:
        # A gate that passed (or took the quality revise loop) must not keep a
        # stale pause marker around — /resume would keep demanding a decision.
        result["pause_reason"] = None

    return NodeResult(result, "evaluator").to_dict()


async def _collect_sample(
    state: XHSGrowthState, thread_id: str | None, evaluation: dict[str, Any]
) -> None:
    """Persist one evaluator-judgment sample (label_source='evaluator')."""
    if not thread_id:
        return
    status = str(evaluation.get("status") or "ready").lower()
    score = evaluation.get("overall_score")
    # Training samples also feed the legacy trend endpoint.  Persisting a
    # degraded/scoreless result as ``0`` would turn an evaluator outage into a
    # real low score and contaminate pass-rate/trend aggregates.
    if status in {"degraded", "failed", "running", "unavailable"} or score is None:
        logger.debug(
            "skip evaluator sample for non-consumable result: thread=%s status=%s",
            thread_id,
            status,
        )
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
                overall_score=float(score),
                decision=str(evaluation.get("decision") or ""),
                label_source="evaluator",
                content_snapshot=_build_content_snapshot(state),
            )
        )
    except Exception as e:
        logger.debug("evaluator sample collection failed (non-blocking): %s", e)


# Body text cap — keeps sample rows bounded (~1-3KB) for finetune data volume.
_BODY_TRUNCATE = 2000
# Cap image prompts stored — full galleries aren't needed to judge visual plan.
_MAX_IMAGE_PROMPTS = 6


def _build_content_snapshot(state: XHSGrowthState) -> dict[str, Any]:
    """Compact snapshot of the evaluated content for finetune training input.

    ponytail: truncation + caps — finetune needs enough to learn content→score,
    not a full archive. Falls back to empty strings when fields are absent.
    """
    copy_content = state.get("copy_content") or {}
    visual_plan = state.get("visual_plan") or {}
    body = str(copy_content.get("body_text") or "")
    image_prompts = list(visual_plan.get("image_prompts") or [])[:_MAX_IMAGE_PROMPTS]
    return {
        "title": str(copy_content.get("selected_title") or ""),
        "body": body[:_BODY_TRUNCATE],
        "hashtags": list(copy_content.get("hashtags") or []),
        "cta": str(copy_content.get("cta") or ""),
        "tone": str(copy_content.get("tone") or ""),
        "cover_prompt": str(visual_plan.get("cover_prompt") or ""),
        "image_prompts": image_prompts,
        "image_count": int(visual_plan.get("image_count") or 0),
        "layout_style": str(visual_plan.get("layout_style") or ""),
    }
