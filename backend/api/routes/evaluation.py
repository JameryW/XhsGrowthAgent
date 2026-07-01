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
        raise ValidationError("content", "No copy_content/visual_plan to evaluate for this thread")

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


@router.get("/weights")
async def get_evaluator_weights(request: Request) -> ApiResponse[Any]:
    """查看当前生效的 grader 权重（默认 + DB 覆盖解析后）.

    可选 query: account_id（按账号隔离权重）。
    """
    from backend.db.evaluator_config import list_weights
    from backend.db.pool import is_pool_ready

    account_id = request.query_params.get("account_id")
    if not is_pool_ready():
        # ponytail: no DB → return defaults only
        from backend.db.evaluator_config import DEFAULT_WEIGHTS

        return success(
            data={
                "db_ready": False,
                "account_id": account_id,
                "weights": [
                    {"weight_key": k, "value": v, "is_default": True}
                    for k, v in DEFAULT_WEIGHTS.items()
                ],
            }
        )
    weights = await list_weights(account_id)
    return success(
        data={
            "db_ready": True,
            "account_id": account_id,
            "weights": weights,
        }
    )


@router.get("/epochs")
async def get_evaluator_epochs(request: Request) -> ApiResponse[Any]:
    """查看 prompt epoch 演化历史 + 当前 active epoch.

    返回 list_epochs（newest first）每项含 epoch_id/bias_severity/note/active/created_at。
    DB 不可用时返回空列表 + db_ready=False。
    """
    from backend.db.evaluator_config import list_epochs
    from backend.db.pool import is_pool_ready

    if not is_pool_ready():
        return success(data={"db_ready": False, "epochs": []})
    epochs = await list_epochs()
    return success(
        data={
            "db_ready": True,
            "epochs": [
                {
                    "epoch_id": e.epoch_id,
                    "bias_severity": e.bias_severity,
                    "note": e.note,
                    "active": e.active,
                    "created_at": e.created_at,
                }
                for e in epochs
            ],
        }
    )


@router.get("/samples")
async def get_evaluator_samples(request: Request) -> ApiResponse[Any]:
    """导出训练样本（jsonl 训练格式预览）."""
    from backend.db.evaluator_config import export_samples
    from backend.db.pool import is_pool_ready

    if not is_pool_ready():
        return success(data={"db_ready": False, "samples": []})
    account_id = request.query_params.get("account_id")
    limit = int(request.query_params.get("limit", "100"))
    samples = await export_samples(account_id, limit=limit)
    return success(data={"db_ready": True, "samples": samples, "count": len(samples)})


@router.get("/trend")
async def get_evaluator_trend(request: Request) -> ApiResponse[Any]:
    """评估历史趋势 — overall_score 时序 + 各维度均值聚合."""
    from backend.db.evaluator_config import WEIGHTED_DIMENSIONS, fetch_trend
    from backend.db.pool import is_pool_ready

    if not is_pool_ready():
        return success(data={"db_ready": False, "points": [], "dim_averages": {}})
    account_id = request.query_params.get("account_id")
    limit = int(request.query_params.get("limit", "100"))
    rows = await fetch_trend(account_id, limit=limit)

    # Build timeline points + accumulate per-dimension scores for averages.
    points: list[dict[str, Any]] = []
    dim_totals: dict[str, float] = {d: 0.0 for d in WEIGHTED_DIMENSIONS}
    dim_counts: dict[str, int] = {d: 0 for d in WEIGHTED_DIMENSIONS}
    for r in rows:
        dims = r.get("dimensions") or []
        if isinstance(dims, str):
            import json as _json

            try:
                dims = _json.loads(dims)
            except (ValueError, TypeError):
                dims = []
        dim_scores: dict[str, float] = {}
        for d in dims:
            if not isinstance(d, dict):
                continue
            name = d.get("dimension")
            if not name:
                continue
            try:
                sc = float(d.get("score"))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            dim_scores[str(name)] = sc
            if name in dim_totals:
                dim_totals[name] += sc
                dim_counts[name] += 1
        points.append(
            {
                "created_at": r.get("created_at") or "",
                "overall_score": float(r.get("overall_score") or 0.0),
                "decision": r.get("decision") or "",
                "dim_scores": dim_scores,
            }
        )
    dim_averages = {
        d: round(dim_totals[d] / dim_counts[d], 1) if dim_counts[d] else 0.0
        for d in WEIGHTED_DIMENSIONS
    }
    return success(data={"db_ready": True, "points": points, "dim_averages": dim_averages})
