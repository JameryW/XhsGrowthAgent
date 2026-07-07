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

    result = await _evaluator(state, store=store)

    # Degrade on failure: BaseAgent.__call__ returns an error state (phase=ERROR,
    # error, retry_count) instead of raising (prd 07-07 stateful retry). The
    # evaluator is a non-blocking quality gate — a failure must not block
    # publishing. Detect the error state (no evaluation_result key) and
    # replace with a synthetic pass-through result.
    if "evaluation_result" not in result:
        error = result.get("error", "unknown evaluator failure")
        logger.warning("Evaluator failed, degrading to pass-through: %s", error)
        from backend.state.enums import ContentStatus

        result = {
            "evaluation_result": {
                "overall_score": 100.0,
                "dimensions": [],
                "decision": ContentStatus.APPROVED,
                "revision_hints": [],
                "bias_warning": "",
                "summary": f"评估器异常，降级放行: {error}",
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
