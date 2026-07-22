"""Evaluation API routes — RQGM agent-as-a-judge creation-quality evaluation.

The evaluator runs automatically as the `evaluator_gate` graph node (after
human review approves, before publish). These routes expose the result and
allow on-demand evaluation of a thread's current content without advancing
the workflow (used by omp / external callers).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from backend.agents.evaluator import MIN_EVALUATION_COVERAGE, EvaluatorAgent
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

HISTORICAL_ASSESSMENT_TYPE = "rqgm_content_review"
HISTORICAL_SUBJECT_TYPE = "imported_note"
_HISTORICAL_DIMENSION_WEIGHTS: dict[str, float] = {
    "copywriting": 0.18,
    "visual": 0.13,
    "compliance": 0.14,
    "reach": 0.13,
    "audience": 0.13,
    "ai_taste": 0.08,
    "image_quality": 0.07,
    "commercial_tone": 0.05,
    "altruism": 0.09,
}


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
    status = str(evaluation.get("status") or "ready").lower()
    if evaluation.get("degraded") or status in {"degraded", "failed", "running", "unavailable"}:
        # Degraded/failed rows are audit records, not successful evaluations;
        # never let their legacy 100/approved fallback enter KPI aggregates.
        return None, None
    score = evaluation.get("overall_score")
    decision = evaluation.get("decision")
    try:
        score_val: float | None = float(score) if score is not None else None
    except (TypeError, ValueError):
        score_val = None
    decision_val = str(decision) if decision is not None else None
    # A decision without a usable score is an incomplete/legacy record, not a
    # successful evaluation row.  Keep it out of counts, pass rates and trend
    # inputs even when an old checkpoint says ``approved``.
    if score_val is None:
        return None, None
    return score_val, decision_val


async def _score_thresholds(account_id: str | None = None) -> dict[str, float]:
    """Resolve the effective evaluator thresholds for API/UI consumers.

    Evaluator decisions can use per-account overrides. Returning the resolved
    thresholds with score payloads keeps the UI's colour tiers aligned with
    the decision that was actually produced. Database failures deliberately
    fall back to the evaluator defaults.
    """
    from backend.db.evaluator_config import (
        DEFAULT_PASS_THRESHOLD,
        DEFAULT_REJECT_THRESHOLD,
        load_weights,
    )

    defaults = {
        "pass": float(DEFAULT_PASS_THRESHOLD),
        "warn": float(DEFAULT_REJECT_THRESHOLD),
    }
    if not is_pool_ready():
        return defaults
    try:
        weights = await load_weights(account_id)
    except Exception:
        logger.exception("failed to resolve evaluator thresholds for account=%s", account_id)
        return defaults
    return {
        "pass": float(weights.pass_threshold),
        "warn": float(weights.reject_threshold),
    }


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
    无法精确对应过滤后页码，因此先分页读取完整 DB 来源，再对过滤结果切片。
    """
    account_id = (account_id or "").strip() or None
    if not is_pool_ready():
        return success(
            data={
                "workflows": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
                "account_id": account_id,
                "scope": "account_history" if account_id else "all_accounts",
            }
        )

    graph = request.app.state.graph

    # Evaluation presence is discovered from checkpoints after the DB query,
    # so a single ``limit + offset`` fetch can under-fill a page when many
    # workflows have no evaluation. Read DB pages until the filtered source is
    # exhausted (or the adapter stops making progress), then apply the
    # requested offset/limit to the enriched list.
    db_page_size = 100
    rows: list[Any] = []
    db_offset = 0
    db_total = 0
    while True:
        batch, db_total = await db_list(
            account_id=account_id,
            limit=db_page_size,
            offset=db_offset,
        )
        if not batch:
            break
        rows.extend(batch)
        db_offset += len(batch)
        if db_offset >= db_total or len(batch) < db_page_size:
            break

    enriched: list[dict[str, Any]] = []
    threshold_cache: dict[str, dict[str, float]] = {}
    for row in rows:
        # Defense in depth: even if an adapter/database view ignores its
        # account predicate, never serialize a foreign-account checkpoint.
        if account_id and (row.account_id or "").strip() != account_id.strip():
            continue
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
        account_key = (row.account_id or "").strip()
        if account_key not in threshold_cache:
            threshold_cache[account_key] = await _score_thresholds(account_key)
        thresholds = threshold_cache[account_key]
        evaluation = values.get("evaluation_result") or {}
        status_detail = str(evaluation.get("status") or "ready")

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
                "assessment_type": "rqgm_content_review",
                "scope": "workflow_draft",
                "status_detail": status_detail,
                "degraded": bool(evaluation.get("degraded"))
                or status_detail in {"degraded", "failed"},
                "coverage": evaluation.get("coverage") or {},
                "evaluation_id": evaluation.get("evaluation_id"),
                "evaluator_fingerprint": evaluation.get("evaluator_fingerprint"),
                "pass_threshold": thresholds["pass"],
                "warn_threshold": thresholds["warn"],
                "evaluated_at": evaluation.get("evaluated_at") or row.updated_at,
                "data_as_of": evaluation.get("data_as_of") or row.updated_at,
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
            "account_id": account_id,
            "scope": "account_history" if account_id else "all_accounts",
            "assessment_type": "rqgm_content_review",
            "data_as_of": max(
                (str(item.get("data_as_of") or "") for item in enriched),
                default=None,
            ),
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
    thresholds = await _score_thresholds(str(values.get("account_id") or ""))
    return success(
        data={
            "thread_id": thread_id,
            "has_evaluation": bool(evaluation),
            "evaluation_result": evaluation,
            "thresholds": thresholds,
            "account_id": str(values.get("account_id") or "") or None,
            "subject_type": "workflow_draft",
            "subject_id": thread_id,
            "scope": "workflow_draft",
            "assessment_type": "rqgm_content_review",
            "status": str(evaluation.get("status") or "ready") if evaluation else "unavailable",
            "degraded": bool(evaluation.get("degraded")) if evaluation else False,
            "coverage": evaluation.get("coverage") or {},
            "data_as_of": evaluation.get("data_as_of") or values.get("updated_at") or None,
            "evaluated_at": evaluation.get("evaluated_at") or values.get("updated_at") or None,
            "evaluation_id": evaluation.get("evaluation_id"),
            "evaluator_fingerprint": evaluation.get("evaluator_fingerprint"),
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
    if "evaluation_result" not in result:
        evaluation = {
            "overall_score": None,
            "decision": None,
            "dimensions": [],
            "status": "degraded",
            "degraded": True,
            "coverage": {"weighted_ratio": 0.0, "available": [], "unavailable": []},
            "revision_hints": [],
            "bias_warning": "",
            "summary": f"评估器异常，评估未完成: {result.get('error') or 'evaluator failed'}",
        }
    thresholds = await _score_thresholds(str(values.get("account_id") or ""))

    # Persist evaluation_result to state (does not advance the graph)
    await graph.aupdate_state(
        config,
        {"evaluation_result": evaluation},
    )

    return success(
        data={
            "thread_id": thread_id,
            "status": str(evaluation.get("status") or "ready"),
            "evaluation_result": evaluation,
            "thresholds": thresholds,
            "account_id": str(values.get("account_id") or "") or None,
            "subject_type": "workflow_draft",
            "subject_id": thread_id,
            "scope": "workflow_draft",
            "assessment_type": "rqgm_content_review",
            "degraded": bool(evaluation.get("degraded")),
            "coverage": evaluation.get("coverage") or {},
            "data_as_of": evaluation.get("data_as_of") or values.get("updated_at") or None,
            "evaluated_at": evaluation.get("evaluated_at") or values.get("updated_at") or None,
        }
    )


class NoteEvaluationRequest(BaseModel):
    """Thread-less RQGM evaluation target: an imported historical note."""

    account_id: str = Field(description="账号 ID")
    note_id: str = Field(description="笔记 ID")
    force: bool = Field(default=False, description="强制创建新的评估版本")


def _build_note_eval_state(
    note: NoteStats,
    niche: str,
    *,
    niche_source: str = "",
    niche_context_available: bool | None = None,
) -> XHSGrowthState:
    """Synthesize a minimal XHSGrowthState for EvaluatorAgent.execute from a note.

    Mirrors free.py `_build_eval_state`: only the content fields matter; the rest
    default. Historical notes lack generation-side metadata (cover_prompt / layout /
    content_plan topic/angle), so visual/image_quality are unavailable to the
    current text-only evaluator.  Missing niche context is represented explicitly
    instead of falling back to a synthetic default niche.
    `image_urls` carries the real cover URL (text-only until a multimodal model is
    routed to TaskType.EVALUATION — the field is already wired through the prompt).
    """
    cover_url = (note.cover_url or "").strip()
    normalized_niche = (niche or "").strip()
    resolved_niche_source = (niche_source or "").strip()
    has_niche = (
        bool(normalized_niche) if niche_context_available is None else niche_context_available
    )
    return cast(
        "XHSGrowthState",
        {
            "account_id": note.account_id,
            "niche": normalized_niche,
            "niche_source": resolved_niche_source,
            "niche_context_available": has_niche,
            "visual_input_available": False,
            "historical_note": True,
            "subject_type": HISTORICAL_SUBJECT_TYPE,
            "subject_id": note.note_id,
            "assessment_type": HISTORICAL_ASSESSMENT_TYPE,
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


async def _historical_niche_context(
    account_id: str,
    note: NoteStats,
) -> tuple[str, str, bool]:
    """Resolve the niche used by historical-note evaluation without defaults.

    An explicit account binding remains authoritative.  When an older account
    has no binding, reuse the existing deterministic niche resolver against the
    imported note and persist a successful inference when possible.  A genuine
    cold start is represented as an empty niche with ``cold_start`` source so
    audience/reach coverage can be marked unavailable rather than silently
    evaluating against the workflow's legacy ``母婴`` fallback.
    """
    try:
        account = await get_account(account_id)
    except Exception as exc:
        logger.warning("account context lookup failed for %s: %s", account_id, exc)
        account = None

    bound_niche = (getattr(account, "niche", "") if account else "") or ""
    bound_source = (getattr(account, "niche_source", "") if account else "") or ""
    if bound_niche.strip():
        return (
            bound_niche.strip(),
            bound_source.strip() or "account_bound",
            True,
        )

    try:
        from backend.services.niche_resolver import resolve_account_niche

        resolution = await resolve_account_niche(
            account_id,
            notes=[note.to_dict()],
            persist=True,
        )
        niche = str(resolution.niche or "").strip()
        source = str(resolution.source or "cold_start").strip() or "cold_start"
        return niche, source, bool(niche)
    except Exception as exc:
        logger.debug("historical niche inference failed for %s: %s", account_id, exc)
        return "", "cold_start", False


def _hash_payload(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _historical_source_hash(note: NoteStats) -> str:
    """Hash content-bearing fields only; metrics changes do not rerun RQGM."""
    return _hash_payload(
        {
            "title": note.title or "",
            "body_text": note.body_text or "",
            "tags": list(note.tags or []),
            "cover_url": note.cover_url or "",
            "content_type": note.content_type or "note",
        }
    )


def _historical_context_hash(
    note: NoteStats, *, niche: str, niche_source: str, niche_available: bool
) -> str:
    return _hash_payload(
        {
            "account_id": note.account_id,
            "niche": niche,
            "niche_source": niche_source,
            "niche_available": niche_available,
            # Context fields that affect historical coverage and prompt input.
            "visual_input_available": False,
        }
    )


def _coverage_for_dimensions(
    dimensions: list[dict[str, Any]], *, niche_available: bool
) -> dict[str, Any]:
    by_name = {str(item.get("dimension")): item for item in dimensions if isinstance(item, dict)}
    available: list[str] = []
    unavailable: list[str] = []
    weighted_ratio = 0.0
    for name, weight in _HISTORICAL_DIMENSION_WEIGHTS.items():
        item = by_name.get(name)
        usable = bool(item and item.get("available", True) and item.get("score") is not None)
        if name in {"visual", "image_quality"} or (
            name in {"audience", "reach"} and not niche_available
        ):
            usable = False
        if usable:
            available.append(name)
            weighted_ratio += weight
        else:
            unavailable.append(name)
    required_available = all(name in available for name in ("copywriting", "compliance"))
    return {
        "weighted_ratio": round(weighted_ratio, 4),
        "available": available,
        "unavailable": unavailable,
        "required": ["copywriting", "compliance"],
        "required_available": required_available,
    }


def _sanitize_historical_evaluation(
    evaluation: dict[str, Any],
    *,
    niche_available: bool,
    evaluator_fingerprint: str,
    pass_threshold: float = 70.0,
    reject_threshold: float = 50.0,
) -> dict[str, Any]:
    """Apply the historical safety contract at the API boundary.

    This second guard is intentional: old evaluator checkpoints/mocks may not
    carry ``available`` metadata.  It ensures timeout/degraded results and
    unsupported dimensions can never be consumed as a successful score.
    """
    result = dict(evaluation or {})
    raw_status = str(result.get("status") or "").lower()
    degraded = bool(result.get("degraded")) or raw_status in {"degraded", "failed"}
    raw_dimensions = result.get("dimensions")
    dimensions = (
        [item for item in raw_dimensions if isinstance(item, dict)]
        if isinstance(raw_dimensions, list)
        else []
    )

    # Any explicit degraded marker is always sanitized to null score/decision.
    # ``running``/``unavailable`` are also non-consumable states: a legacy
    # producer may attach a stale score beside them, but that score must never
    # become a successful historical result after the API boundary.
    if degraded or raw_status in {"running", "unavailable"}:
        result.update(
            {
                "status": raw_status or "degraded",
                "degraded": degraded,
                "overall_score": None,
                "decision": None,
                "evaluator_fingerprint": evaluator_fingerprint,
                "coverage": {
                    "weighted_ratio": 0.0,
                    "available": [],
                    "unavailable": list(_HISTORICAL_DIMENSION_WEIGHTS),
                    "required": ["copywriting", "compliance"],
                    "required_available": False,
                },
            }
        )
        return result

    if not dimensions:
        # An empty panel is an incomplete historical evaluation, even if an
        # older evaluator attached a legacy score/decision beside it.
        result["status"] = "partial"
        result["overall_score"] = None
        result["decision"] = None
        result["evaluator_fingerprint"] = evaluator_fingerprint
        result["coverage"] = {
            "weighted_ratio": 0.0,
            "available": [],
            "unavailable": list(_HISTORICAL_DIMENSION_WEIGHTS),
            "required": ["copywriting", "compliance"],
            "required_available": False,
        }
        return result

    by_name = {str(item.get("dimension")): item for item in dimensions}
    # Never treat historical visual dimensions as available: the current model
    # receives a URL as text and cannot inspect the actual image bytes.
    for name in ("visual", "image_quality"):
        item = by_name.get(name)
        if item is not None:
            item["available"] = False
            item["score"] = None
            item["rationale"] = item.get("rationale") or "当前评估器未读取真实图片"
    if not niche_available:
        for name in ("audience", "reach"):
            item = by_name.get(name)
            if item is not None:
                item["available"] = False
                item["score"] = None
                item["rationale"] = item.get("rationale") or "缺少账号赛道上下文"

    for name in _HISTORICAL_DIMENSION_WEIGHTS:
        if name not in by_name:
            dimensions.append(
                {
                    "dimension": name,
                    "score": None,
                    "available": False,
                    "rationale": "评估器未返回该维度，未补中性分",
                    "issues": [],
                    "is_blocking": False,
                }
            )
    result["dimensions"] = dimensions
    coverage = _coverage_for_dimensions(dimensions, niche_available=niche_available)
    result["coverage"] = coverage
    result["evaluator_fingerprint"] = evaluator_fingerprint
    has_required = bool(coverage["required_available"])
    weighted_ratio = float(coverage["weighted_ratio"] or 0.0)
    if not has_required or weighted_ratio < MIN_EVALUATION_COVERAGE:
        result["status"] = "partial"
        result["overall_score"] = None
        result["decision"] = None
        return result
    # Normalize over the dimensions that actually have evidence.  This keeps
    # the score comparable while making the denominator visible to consumers.
    weighted_total = sum(
        float(item["score"]) * _HISTORICAL_DIMENSION_WEIGHTS[str(item["dimension"])]
        for item in dimensions
        if str(item.get("dimension")) in _HISTORICAL_DIMENSION_WEIGHTS
        and item.get("available")
        and item.get("score") is not None
    )
    result["overall_score"] = round(weighted_total / weighted_ratio, 1)
    result["status"] = "partial" if coverage["unavailable"] else "ready"
    if result["status"] != "ready":
        # A partial but sufficiently-covered score is useful; keep a decision
        # only when it can be derived from the score and compliance evidence.
        score = float(result["overall_score"])
        compliance = by_name.get("compliance") or {}
        if compliance.get("score") is not None and float(compliance["score"]) < reject_threshold:
            result["decision"] = "rejected"
        elif score >= pass_threshold:
            result["decision"] = "approved"
        else:
            result["decision"] = "needs_revision"
    return result


def _evaluation_run_data(run: Any, *, cache_hit: bool = False) -> dict[str, Any]:
    result = dict(run.result_json or {})
    result.setdefault("status", run.status)
    result.setdefault("coverage", run.coverage_json or {})
    result["evaluation_id"] = run.evaluation_id
    result["assessment_type"] = run.assessment_type
    source = {
        "content_hash": run.source_content_hash,
        "data_as_of": run.source_data_as_of,
        "context_hash": run.context_hash,
    }
    if isinstance(result.get("source"), dict):
        source.update(result["source"])
    payload = {
        "evaluation_id": run.evaluation_id,
        "account_id": run.account_id,
        "note_id": run.subject_id if run.subject_type == HISTORICAL_SUBJECT_TYPE else None,
        "subject_type": run.subject_type,
        "subject_id": run.subject_id,
        "assessment_type": run.assessment_type,
        "status": run.status,
        "evaluation_result": result,
        "coverage": run.coverage_json,
        "thresholds": run.thresholds_json,
        "source": source,
        "evaluator_fingerprint": run.evaluator_fingerprint,
        "evaluated_at": run.completed_at or run.created_at,
        "cache_hit": cache_hit,
        "error": run.error,
    }
    payload.update(
        {
            "overall_score": result.get("overall_score"),
            "decision": result.get("decision"),
            "degraded": bool(result.get("degraded")) or run.status in {"degraded", "failed"},
            "data_as_of": run.source_data_as_of or None,
            "stale": bool(run.stale_at),
            "stale_at": run.stale_at,
        }
    )
    return payload


@router.post("/note")
async def run_note_evaluation(
    ref: NoteEvaluationRequest,
    request: Request,
    force: bool | None = Query(None, description="强制创建新的评估版本（覆盖 body）"),
) -> ApiResponse[Any]:
    """对已导入历史笔记手动触发 RQGM 评估 (thread-less, 不写 checkpoint).

    读 NoteStats → 构造 eval_state (note 字段映射到 copy_content/visual_plan) →
    调 EvaluatorAgent.execute → 返回 evaluation_result。
    历史笔记无生成侧元数据，visual/image_quality 维度标记为不可用。
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

    niche, niche_source, niche_available = await _historical_niche_context(account_id, note)

    graph = getattr(request.app.state, "graph", None)
    store = getattr(graph, "store", None)
    eval_state = _build_note_eval_state(
        note,
        niche,
        niche_source=niche_source,
        niche_context_available=niche_available,
    )

    source_hash = _historical_source_hash(note)
    context_hash = _historical_context_hash(
        note,
        niche=niche.strip(),
        niche_source=niche_source,
        niche_available=niche_available,
    )
    # Resolve account-specific weights before the cache lookup so an override
    # changes the evaluator fingerprint and cannot reuse an incompatible run.
    try:
        await _evaluator._resolve_weights(account_id)
        evaluator_fingerprint = _evaluator.evaluator_fingerprint()
    except Exception as exc:
        logger.debug("evaluator fingerprint resolution failed: %s", exc)
        evaluator_fingerprint = "rqgm:unknown"
    thresholds = await _score_thresholds(account_id)

    from backend.db import quality_evaluations as quality_db

    force_requested = force if isinstance(force, bool) else ref.force
    if not force_requested:
        cached = await quality_db.get_cached(
            account_id=account_id,
            subject_type=HISTORICAL_SUBJECT_TYPE,
            subject_id=note_id,
            assessment_type=HISTORICAL_ASSESSMENT_TYPE,
            source_content_hash=source_hash,
            context_hash=context_hash,
            evaluator_fingerprint=evaluator_fingerprint,
        )
        if cached is not None:
            payload = _evaluation_run_data(cached, cache_hit=True)
            payload["thresholds"] = cached.thresholds_json or thresholds
            payload["persistence_status"] = "ready" if is_pool_ready() else "memory"
            payload["source"].update(
                {
                    "niche": niche or None,
                    "niche_source": niche_source or None,
                    "note_synced_at": note.synced_at or None,
                }
            )
            return success(data=payload)

    # A new content/context fingerprint supersedes prior runs.  Keep them for
    # audit, but mark them stale so the cache cannot silently serve an old
    # answer after title/body/tag/cover/niche changes.
    await quality_db.mark_subject_stale(
        account_id,
        HISTORICAL_SUBJECT_TYPE,
        note_id,
        reason="force_re_evaluation" if force_requested else "source_or_context_changed",
    )

    run = quality_db.new_run(
        account_id=account_id,
        subject_type=HISTORICAL_SUBJECT_TYPE,
        subject_id=note_id,
        assessment_type=HISTORICAL_ASSESSMENT_TYPE,
        source_content_hash=source_hash,
        source_data_as_of=note.synced_at or "",
        context_hash=context_hash,
        evaluator_fingerprint=evaluator_fingerprint,
    )
    run = await quality_db.create_run(run)
    # store may be None on compiled graphs without a store attached; EvaluatorAgent
    # tolerates None (skips memory recall), same as free.py:evaluate_draft.
    result = await _evaluator(eval_state, store=store)  # type: ignore[arg-type]
    evaluation: dict[str, Any]
    if "evaluation_result" not in result:
        error = str(result.get("error") or "evaluator failed")
        evaluation = {
            "overall_score": None,
            "decision": None,
            "dimensions": [],
            "status": "degraded",
            "degraded": True,
            "coverage": {
                "weighted_ratio": 0.0,
                "available": [],
                "unavailable": list(_HISTORICAL_DIMENSION_WEIGHTS),
                "required": ["copywriting", "compliance"],
                "required_available": False,
            },
            "revision_hints": [],
            "bias_warning": "",
            "summary": f"评估器异常，评估未完成: {error}",
            "evaluator_fingerprint": evaluator_fingerprint,
        }
    else:
        evaluation = _sanitize_historical_evaluation(
            result.get("evaluation_result") or {},
            niche_available=niche_available,
            evaluator_fingerprint=evaluator_fingerprint,
            pass_threshold=thresholds["pass"],
            reject_threshold=thresholds["warn"],
        )
    status = str(evaluation.get("status") or "partial")
    if status not in {"ready", "partial", "degraded", "failed", "running", "unavailable"}:
        status = "ready" if evaluation.get("overall_score") is not None else "partial"
    evaluation["status"] = status
    evaluation["assessment_type"] = HISTORICAL_ASSESSMENT_TYPE
    evaluation["scope"] = "single_note"
    evaluation["account_id"] = account_id
    evaluation["subject_type"] = HISTORICAL_SUBJECT_TYPE
    evaluation["subject_id"] = note_id
    coverage = evaluation.get("coverage") or {}
    evaluation["thresholds"] = thresholds
    evaluation["data_as_of"] = note.synced_at or None
    evaluation["evaluated_at"] = datetime.now(UTC).isoformat()
    evaluation["source"] = {
        "content_hash": source_hash,
        "data_as_of": note.synced_at or None,
        "context_hash": context_hash,
        "niche": niche or None,
        "niche_source": niche_source or None,
        "note_synced_at": note.synced_at or None,
    }

    run.status = status
    run.result_json = evaluation
    run.coverage_json = coverage if isinstance(coverage, dict) else {}
    run.thresholds_json = thresholds
    run.error = str(evaluation.get("summary") or "") if status in {"degraded", "failed"} else None
    run.completed_at = datetime.now(UTC).isoformat()
    run = await quality_db.update_run(run)

    logger.info(
        "note evaluated: account=%s note=%s overall=%s decision=%s status=%s eval_id=%s",
        account_id,
        note_id,
        evaluation.get("overall_score"),
        evaluation.get("decision"),
        status,
        run.evaluation_id,
    )
    payload = _evaluation_run_data(run)
    payload["persistence_status"] = "ready" if is_pool_ready() else "memory"
    payload["thresholds"] = thresholds
    payload["source"].update(
        {
            "niche": niche or None,
            "niche_source": niche_source or None,
            "note_synced_at": note.synced_at or None,
        }
    )
    return success(data=payload)


@router.get("/note/{account_id}/{note_id}/latest")
async def get_latest_note_evaluation(account_id: str, note_id: str) -> ApiResponse[Any]:
    """Restore the latest persisted historical-note RQGM run after refresh."""
    normalized_account_id = (account_id or "").strip()
    normalized_note_id = (note_id or "").strip()
    if not normalized_account_id:
        raise ValidationError("account_id", "account_id cannot be empty")
    if not normalized_note_id:
        raise ValidationError("note_id", "note_id cannot be empty")
    from backend.db import quality_evaluations as quality_db

    run = await quality_db.get_latest_for_subject(
        normalized_account_id,
        HISTORICAL_SUBJECT_TYPE,
        normalized_note_id,
        assessment_type=HISTORICAL_ASSESSMENT_TYPE,
    )
    if run is None:
        return success(
            data={
                "account_id": normalized_account_id,
                "note_id": normalized_note_id,
                "subject_type": HISTORICAL_SUBJECT_TYPE,
                "subject_id": normalized_note_id,
                "scope": "single_note",
                "assessment_type": HISTORICAL_ASSESSMENT_TYPE,
                "status": "unavailable" if not is_pool_ready() else "not_evaluated",
                "evaluation_result": None,
                "evaluation_id": None,
                "coverage": {
                    "weighted_ratio": 0.0,
                    "available": [],
                    "unavailable": list(_HISTORICAL_DIMENSION_WEIGHTS),
                },
                "thresholds": await _score_thresholds(normalized_account_id),
                "data_as_of": None,
                "evaluated_at": None,
                "persistence_status": "memory" if not is_pool_ready() else "ready",
            }
        )
    # A latest lookup is also the first read after an import/content update.
    # Compare the current durable note/context fingerprints so a stale RQGM
    # answer cannot be presented as current until the user explicitly reruns
    # it. Metrics-only changes intentionally do not affect this content hash.
    if run is not None and not run.stale_at:
        current_note = await get_note_stats(normalized_account_id, normalized_note_id)
        if current_note is not None:
            niche, niche_source, niche_available = await _historical_niche_context(
                normalized_account_id,
                current_note,
            )
            current_context_hash = _historical_context_hash(
                current_note,
                niche=niche.strip(),
                niche_source=niche_source,
                niche_available=niche_available,
            )
            if (
                run.source_content_hash != _historical_source_hash(current_note)
                or run.context_hash != current_context_hash
            ):
                await quality_db.mark_subject_stale(
                    normalized_account_id,
                    HISTORICAL_SUBJECT_TYPE,
                    normalized_note_id,
                    reason="source_or_context_changed",
                )
                run.stale_at = datetime.now(UTC).isoformat()
    payload = _evaluation_run_data(run)
    payload["persistence_status"] = "ready" if is_pool_ready() else "memory"
    return success(data=payload)


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

    account_id = (request.query_params.get("account_id") or "").strip() or None
    thresholds = await _score_thresholds(account_id)
    if not is_pool_ready():
        return success(
            data={
                "db_ready": False,
                "points": [],
                "dim_averages": {},
                "account_id": account_id,
                "scope": "account_history" if account_id else "all_accounts",
                "assessment_type": "rqgm_content_review",
                "pass_threshold": thresholds["pass"],
                "warn_threshold": thresholds["warn"],
                "data_as_of": None,
            }
        )
    limit = int(request.query_params.get("limit", "100"))
    rows = await fetch_trend(account_id, limit=limit)

    # Build timeline points + accumulate per-dimension scores for averages.
    points: list[dict[str, Any]] = []
    dim_totals: dict[str, float] = {d: 0.0 for d in WEIGHTED_DIMENSIONS}
    dim_counts: dict[str, int] = {d: 0 for d in WEIGHTED_DIMENSIONS}
    for r in rows:
        if (
            account_id
            and r.get("account_id") is not None
            and str(r.get("account_id") or "").strip() != account_id
        ):
            continue
        row_status = str(r.get("status") or "ready").lower()
        if bool(r.get("degraded")) or row_status in {"degraded", "failed", "running"}:
            continue
        if r.get("overall_score") is None:
            continue
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
                "status": row_status,
                "degraded": bool(r.get("degraded")),
                "account_id": r.get("account_id"),
                "assessment_type": "rqgm_content_review",
                "evaluated_at": r.get("created_at") or "",
            }
        )
    dim_averages = {
        d: round(dim_totals[d] / dim_counts[d], 1) if dim_counts[d] else 0.0
        for d in WEIGHTED_DIMENSIONS
    }
    return success(
        data={
            "db_ready": True,
            "points": points,
            "dim_averages": dim_averages,
            "account_id": account_id,
            "scope": "account_history" if account_id else "all_accounts",
            "assessment_type": "rqgm_content_review",
            "pass_threshold": thresholds["pass"],
            "warn_threshold": thresholds["warn"],
            "data_as_of": max(
                (str(point.get("created_at") or "") for point in points),
                default=None,
            ),
        }
    )
