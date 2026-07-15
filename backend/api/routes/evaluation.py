"""Evaluation API routes — RQGM agent-as-a-judge creation-quality evaluation.

The evaluator runs automatically as the `evaluator_gate` graph node (after
human review approves, before publish). These routes expose the result and
allow on-demand evaluation of a thread's current content without advancing
the workflow (used by omp / external callers).
"""

from __future__ import annotations

import logging
from typing import Any, cast

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from backend.agents.evaluator import EvaluatorAgent
from backend.api.errors import CreatorNoteNotFoundError, ValidationError, WorkflowNotFoundError
from backend.api.responses import ApiResponse, success
from backend.db.accounts import get_account
from backend.db.creator_stats import get_note_stats
from backend.db.pool import is_pool_ready
from backend.db.workflows import list_workflows as db_list
from backend.services.creator_stats.types import NoteStats
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.api.evaluation")

router = APIRouter()

_evaluator = EvaluatorAgent()


def _get_state_values(state: Any) -> dict[str, Any]:
    if not state or not state.values or state.values.get("session_id") is None:
        return {}
    return cast("dict[str, Any]", state.values)


def _extract_eval_summary(values: dict[str, Any]) -> tuple[float | None, str | None]:
    """Pull (overall_score, decision) from a checkpoint's evaluation_result.

    Returns (None, None) when there is no evaluation_result, so callers can
    skip the thread. decision is coerced to its string value (ContentStatus is
    a StrEnum, so str(...) yields "approved" / "needs_revision" / "rejected").
    """
    evaluation = values.get("evaluation_result")
    if not evaluation or not isinstance(evaluation, dict):
        return None, None
    score = evaluation.get("overall_score")
    decision = evaluation.get("decision")
    try:
        score_val: float | None = float(score) if score is not None else None
    except (TypeError, ValueError):
        score_val = None
    decision_val = str(decision) if decision is not None else None
    return score_val, decision_val


@router.get("/list")
async def list_evaluated_workflows(
    request: Request,
    account_id: str | None = Query(None, description="筛选账号 ID"),
    limit: int = Query(20, ge=1, le=100, description="返回数量限制（过滤后）"),
    offset: int = Query(0, ge=0, description="分页偏移（过滤后）"),
) -> ApiResponse[Any]:
    """列出有评估结果的工作流 — 含标题 + 评估摘要.

    专用端点，不污染通用 /api/workflow/list（后者从 DB workflows 表查，无标题/无评估）。
    流程：DB 取基础列表 → 逐条读 checkpoint → 过滤掉无 evaluation_result 的 →
    装载 selected_title / overall_score / decision → 切片分页。

    分页注意：has_evaluation 过滤在 checkpoint 读取后进行，DB 端的 limit/offset
    无法精确对应过滤后页码。为此从 DB 多取 (limit+offset) 条作为缓冲，
    再对过滤后结果做 limit/offset 切片。绝大多数账号工作流总量小，缓冲足够。
    """
    if not is_pool_ready():
        return success(data={"workflows": [], "total": 0, "limit": limit, "offset": offset})

    graph = request.app.state.graph

    # Over-fetch from DB to compensate for post-filter shrinkage.
    # limit+offset is the worst case (every DB row has an evaluation).
    db_limit = limit + offset
    rows, _db_total = await db_list(
        account_id=account_id,
        limit=db_limit,
        offset=0,
    )

    enriched: list[dict[str, Any]] = []
    for row in rows:
        config = {"configurable": {"thread_id": row.thread_id}}
        try:
            state = await graph.aget_state(config)
        except Exception:
            logger.exception("aget_state failed for %s during evaluation list", row.thread_id)
            continue
        values = _get_state_values(state)
        if not values:
            continue

        overall_score, decision = _extract_eval_summary(values)
        if overall_score is None and decision is None:
            # No evaluation_result → skip this workflow.
            continue

        copy_content = values.get("copy_content") or {}
        if not isinstance(copy_content, dict):
            copy_content = {}
        selected_title = copy_content.get("selected_title") or ""

        enriched.append(
            {
                "thread_id": row.thread_id,
                "account_id": row.account_id,
                "status": row.status,
                "phase": row.phase,
                "label": row.label,
                "workflow_mode": row.workflow_mode,
                "updated_at": row.updated_at,
                "created_at": row.created_at,
                "selected_title": selected_title,
                "overall_score": overall_score,
                "decision": decision,
            }
        )

    total = len(enriched)
    page = enriched[offset : offset + limit]
    return success(
        data={
            "workflows": page,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    )


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


class NoteEvaluationRequest(BaseModel):
    """Thread-less RQGM evaluation target: an imported historical note."""

    account_id: str = Field(description="账号 ID")
    note_id: str = Field(description="笔记 ID")


def _build_note_eval_state(note: NoteStats, niche: str) -> XHSGrowthState:
    """Synthesize a minimal XHSGrowthState for EvaluatorAgent.execute from a note.

    Mirrors free.py `_build_eval_state`: only the content fields matter; the rest
    default. Historical notes lack generation-side metadata (cover_prompt / layout /
    content_plan topic/angle), so visual / image_quality / reach are reference scores.
    `image_urls` carries the real cover URL (text-only until a multimodal model is
    routed to TaskType.EVALUATION — the field is already wired through the prompt).
    """
    cover_url = (note.cover_url or "").strip()
    return cast(
        "XHSGrowthState",
        {
            "account_id": note.account_id,
            "niche": niche or "母婴",
            "copy_content": {
                "selected_title": note.title or "",
                "body_text": note.body_text or "",
                "hashtags": list(note.tags or []),
                "cta": "",
                "tone": "",
            },
            "content_plan": {
                "selected_topic": "",
                "content_angle": "",
                "target_audience": "",
                "content_type": note.content_type or "note",
            },
            "visual_plan": {
                "cover_prompt": "",
                "image_count": 1 if cover_url else 0,
                "image_prompts": [],
                "image_urls": [cover_url] if cover_url else [],
                "layout_style": "",
                "color_palette": [],
            },
        },
    )


@router.post("/note")
async def run_note_evaluation(ref: NoteEvaluationRequest, request: Request) -> ApiResponse[Any]:
    """对已导入历史笔记手动触发 RQGM 评估 (thread-less, 不写 checkpoint).

    读 NoteStats → 构造 eval_state (note 字段映射到 copy_content/visual_plan) →
    调 EvaluatorAgent.execute → 返回 evaluation_result。
    历史笔记无生成侧元数据，visual/image_quality 维度为参考分。
    """
    account_id = (ref.account_id or "").strip()
    note_id = (ref.note_id or "").strip()
    if not account_id:
        raise ValidationError("account_id", "account_id cannot be empty")
    if not note_id:
        raise ValidationError("note_id", "note_id cannot be empty")

    note = await get_note_stats(account_id, note_id)
    if note is None:
        raise CreatorNoteNotFoundError(account_id, note_id)

    account = await get_account(account_id)
    niche = account.niche if account else ""

    graph = getattr(request.app.state, "graph", None)
    store = getattr(graph, "store", None)
    eval_state = _build_note_eval_state(note, niche)
    # store may be None on compiled graphs without a store attached; EvaluatorAgent
    # tolerates None (skips memory recall), same as free.py:evaluate_draft.
    result = await _evaluator(eval_state, store=store)  # type: ignore[arg-type]
    evaluation = result.get("evaluation_result") or {}

    logger.info(
        "note evaluated: account=%s note=%s overall=%s decision=%s",
        account_id,
        note_id,
        evaluation.get("overall_score"),
        evaluation.get("decision"),
    )
    return success(
        data={
            "account_id": account_id,
            "note_id": note_id,
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
