"""Evaluation API routes — RQGM agent-as-a-judge creation-quality evaluation.

The evaluator runs automatically as the `evaluator_gate` graph node (after
human review approves, before publish). These routes expose the result and
allow on-demand evaluation of a thread's current content without advancing
the workflow (used by omp / external callers).
"""

from __future__ import annotations

import logging
from typing import Any, cast

from fastapi import APIRouter, Request

from backend.agents.evaluator import EvaluatorAgent
from backend.api.errors import ValidationError, WorkflowNotFoundError
from backend.api.responses import ApiResponse, success
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.api.evaluation")

router = APIRouter()

_evaluator = EvaluatorAgent()


def _get_state_values(state: Any) -> dict[str, Any]:
    if not state or not state.values or state.values.get("session_id") is None:
        return {}
    return cast("dict[str, Any]", state.values)


@router.get("/result/{thread_id}")
async def get_evaluation_result(thread_id: str, request: Request) -> ApiResponse[Any]:
    """获取指定工作流的创作质量评估结果."""
    if not thread_id or not thread_id.strip():
        raise ValidationError("thread_id", "thread_id cannot be empty")

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)
    values = _get_state_values(state)
    if not values:
        raise WorkflowNotFoundError(thread_id)

    evaluation = values.get("evaluation_result") or {}
    return success(
        data={
            "thread_id": thread_id,
            "has_evaluation": bool(evaluation),
            "evaluation_result": evaluation,
        }
    )


@router.post("/run/{thread_id}")
async def run_evaluation(thread_id: str, request: Request) -> ApiResponse[Any]:
    """对指定工作流当前内容手动触发评估 (不推进工作流).

    读取当前 copy_content / visual_plan / content_plan，调用 EvaluatorAgent，
    将 evaluation_result 写回 state 并返回。用于 omp 主动评估。
    """
    if not thread_id or not thread_id.strip():
        raise ValidationError("thread_id", "thread_id cannot be empty")

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)
    values = _get_state_values(state)
    if not values:
        raise WorkflowNotFoundError(thread_id)

    if not values.get("copy_content") and not values.get("visual_plan"):
        raise ValidationError(
            "content", "No copy_content/visual_plan to evaluate for this thread"
        )

    # Run evaluator against current state snapshot.
    # store may be None on compiled graphs without a store attached; EvaluatorAgent
    # tolerates None (skips memory recall), so the ignore is safe here.
    eval_state = cast("XHSGrowthState", dict(values))
    store = getattr(graph, "store", None)
    result = await _evaluator(eval_state, store=store)  # type: ignore[arg-type]

    evaluation = result.get("evaluation_result") or {}

    # Persist evaluation_result to state (does not advance the graph)
    await graph.aupdate_state(
        config,
        {"evaluation_result": evaluation},
    )

    return success(
        data={
            "thread_id": thread_id,
            "status": "evaluated",
            "evaluation_result": evaluation,
        }
    )
