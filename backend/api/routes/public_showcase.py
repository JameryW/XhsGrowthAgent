"""Public, redacted read APIs for Showcase and Workflow Replay.

The internal workflow endpoints return the full execution state because the
workspace needs it for operations.  Public pages use this router instead so
visibility, identifiers, payload size, and redaction remain server-side
contracts rather than frontend conventions.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Iterable
from typing import Any, cast

from fastapi import APIRouter, Depends, Query, Request

from backend.api.deps import get_optional_user
from backend.api.errors import WorkflowNotFoundError
from backend.api.responses import ApiResponse, success
from backend.db.pool import is_pool_ready
from backend.db.workflows import (
    WorkflowRow,
)
from backend.db.workflows import (
    get_workflow_by_public_id as db_get_by_public_id,
)
from backend.db.workflows import (
    list_workflows as db_list,
)

router = APIRouter()

_PUBLIC_VISIBILITIES = {"public", "unlisted"}
_PUBLIC_STATUS_VALUES = {"completed", "in_progress", "attention"}
_KNOWN_PHASES = {
    "scouting",
    "planning",
    "briefing",
    "creating",
    "reviewing",
    "publishing",
    "analyzing",
    "engaging",
    "completed",
}
_SYSTEM_AGENTS = {"", "orchestrator", "__start__", "__end__"}


def _allowlist() -> set[str]:
    raw = os.environ.get("XHS_SHOWCASE_PUBLIC_IDS", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def _visibility(row: WorkflowRow) -> str:
    """Resolve DB visibility plus an explicit rollout allowlist.

    The DB default is private.  The environment allowlist is intentionally
    additive so operators can publish a reviewed legacy row before a
    migration/admin screen is available.
    """

    configured = (
        row.showcase_visibility if row.showcase_visibility in _PUBLIC_VISIBILITIES else "private"
    )
    allowed = _allowlist()
    if row.thread_id in allowed or (row.public_id and row.public_id in allowed):
        return "public"
    return configured


def _public_id(row: WorkflowRow) -> str:
    if row.public_id:
        return row.public_id
    secret = os.environ.get("XHS_PUBLIC_ID_SECRET") or "xhs-growth-engine-public-id"
    digest = hmac.new(secret.encode(), row.thread_id.encode(), hashlib.sha256).hexdigest()[:20]
    return f"case_{digest}"


def _step_public_id(thread_id: str, checkpoint_id: str) -> str:
    secret = os.environ.get("XHS_PUBLIC_ID_SECRET") or "xhs-growth-engine-public-id"
    digest = hmac.new(
        secret.encode(), f"{thread_id}:{checkpoint_id}".encode(), hashlib.sha256
    ).hexdigest()[:20]
    return f"step_{digest}"


def _safe_text(value: Any, limit: int = 240) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip()
    if not text:
        return None
    return text[:limit] + ("…" if len(text) > limit else "")


def _safe_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    url = value.strip()
    if url.startswith(("https://", "http://")):
        return url[:500]
    return None


def _safe_list(value: Any, limit: int = 6) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = _safe_text(item, 80)
        if text:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _has_data(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        return any(_has_data(item) for item in value.values())
    if isinstance(value, list):
        return bool(value)
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _phase(value: Any) -> str:
    phase = value if isinstance(value, str) else "creating"
    if phase == "engaging":
        return "publishing"
    return phase if phase in _KNOWN_PHASES else "creating"


def _public_status(status: Any, phase: Any = None) -> str:
    raw = status if isinstance(status, str) else ""
    if raw == "completed" or phase == "completed":
        return "completed"
    if raw in {"error", "cancelled", "paused", "stale"}:
        return "attention"
    return "in_progress"


def _public_result(source: dict[str, Any]) -> dict[str, Any]:
    """Project internal state into the stable, public result DTO."""

    brief = source.get("brief_content") or {}
    trend = source.get("trend_data") or {}
    plan = source.get("content_plan") or {}
    copy = source.get("copy_content") or {}
    visual = source.get("visual_plan") or {}
    publish = source.get("publish_result") or {}
    analytics = source.get("analytics") or {}
    prediction = source.get("ripple_prediction") or {}
    pmf = source.get("ripple_pmf") or {}

    if not isinstance(brief, dict):
        brief = {}
    if not isinstance(trend, dict):
        trend = {}
    if not isinstance(plan, dict):
        plan = {}
    if not isinstance(copy, dict):
        copy = {}
    if not isinstance(visual, dict):
        visual = {}
    if not isinstance(publish, dict):
        publish = {}
    if not isinstance(analytics, dict):
        analytics = {}
    if not isinstance(prediction, dict):
        prediction = {}
    if not isinstance(pmf, dict):
        pmf = {}

    title = _safe_text(copy.get("selected_title"))
    hot_topics = trend.get("hot_topics") if isinstance(trend.get("hot_topics"), list) else []
    first_hot_topic = hot_topics[0] if hot_topics and isinstance(hot_topics[0], dict) else {}
    topic = (
        _safe_text(plan.get("selected_topic"))
        or _safe_text(brief.get("content_direction"))
        or _safe_text(first_hot_topic.get("topic"))
    )
    summary = _safe_text(copy.get("body_text"), 360)
    if not summary:
        summary = _safe_text(plan.get("content_angle")) or _safe_text(brief.get("product_name"))

    result: dict[str, Any] = {}
    if title:
        result["title"] = title
    if topic:
        result["topic"] = topic
    if summary:
        result["summary"] = summary

    hashtags = _safe_list(copy.get("hashtags"), 8) or _safe_list(brief.get("required_hashtags"), 8)
    if hashtags:
        result["hashtags"] = hashtags
    key_points = _safe_list(plan.get("key_points"), 5) or _safe_list(brief.get("selling_points"), 5)
    if key_points:
        result["key_points"] = key_points
    target_audience = _safe_text(plan.get("target_audience")) or _safe_text(
        brief.get("target_audience")
    )
    if target_audience:
        result["target_audience"] = target_audience

    visual_result: dict[str, Any] = {}
    layout = _safe_text(visual.get("layout_style"), 80)
    image_count = _number(visual.get("image_count"))
    palette = _safe_list(visual.get("color_palette"), 5)
    if layout:
        visual_result["layout"] = layout
    if image_count is not None:
        visual_result["image_count"] = image_count
    if palette:
        visual_result["palette"] = palette
    if visual_result:
        result["visual"] = visual_result

    publish_status = (
        publish.get("status")
        if publish.get("status") in {"published", "scheduled", "draft"}
        else None
    )
    published_at = _safe_text(publish.get("published_at") or publish.get("scheduled_at"), 80)
    post_url = _safe_url(publish.get("post_url"))
    if publish_status or published_at or post_url:
        result["publish"] = {
            key: value
            for key, value in {
                "status": publish_status,
                "published_at": published_at,
                "post_url": post_url,
            }.items()
            if value
        }

    metrics: dict[str, int | float] = {}
    for public_key, internal_key in (
        ("views", "views"),
        ("likes", "likes"),
        ("collects", "collects"),
        ("comments", "comments"),
        ("shares", "shares"),
        ("engagement_rate", "engagement_rate"),
    ):
        value = _number(analytics.get(internal_key))
        if value is not None:
            metrics[public_key] = value
    if metrics:
        result["metrics"] = metrics

    prediction_result: dict[str, int | float | str] = {}
    for public_key, internal_key in (
        ("estimated_reach", "estimated_reach"),
        ("estimated_engagement", "estimated_engagement"),
        ("viral_probability", "viral_probability"),
        ("confidence", "confidence"),
        ("pmf_score", "pmf_score"),
    ):
        value = _number(prediction.get(internal_key))
        if value is None:
            value = _number(pmf.get(internal_key))
        if value is not None:
            prediction_result[public_key] = value
    verdict = _safe_text(prediction.get("verdict") or pmf.get("verdict"), 80)
    if verdict:
        prediction_result["verdict"] = verdict
    if prediction_result:
        result["prediction"] = prediction_result
    return result


def _checkpoint_dict(checkpoint: Any) -> dict[str, Any]:
    if isinstance(checkpoint, dict):
        return checkpoint
    if hasattr(checkpoint, "model_dump"):
        return cast(dict[str, Any], checkpoint.model_dump())
    return {}


def _is_meaningful_checkpoint(checkpoint: dict[str, Any]) -> bool:
    if checkpoint.get("current_agent") in _SYSTEM_AGENTS:
        return False
    return bool(
        _public_result(checkpoint)
        or checkpoint.get("phase") in {"completed", "reviewing", "publishing", "analyzing"}
    )


def _public_step(thread_id: str, checkpoint: dict[str, Any]) -> dict[str, Any]:
    result = _public_result(checkpoint)
    phase = _phase(checkpoint.get("phase"))
    step = checkpoint.get("step") if isinstance(checkpoint.get("step"), int) else 0
    title = result.get("title") or result.get("topic")
    summary = result.get("summary") or (
        "该阶段已完成关键处理" if phase != "creating" else "正在整理创作结果"
    )
    return {
        "public_id": _step_public_id(thread_id, str(checkpoint.get("checkpoint_id") or step)),
        "step": step,
        "phase": phase,
        "title": title,
        "summary": summary,
        "created_at": checkpoint.get("created_at"),
        "has_result": bool(result),
        "result_kind": phase,
    }


def _key_checkpoints(checkpoints: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(checkpoints, key=lambda item: item.get("step", 0))
    selected: list[dict[str, Any]] = []
    seen_phases: set[str] = set()
    for checkpoint in ordered:
        if not _is_meaningful_checkpoint(checkpoint):
            continue
        phase = _phase(checkpoint.get("phase"))
        if phase in seen_phases:
            continue
        seen_phases.add(phase)
        selected.append(checkpoint)
    if not selected and ordered:
        selected.append(ordered[-1])
    return selected


async def _all_rows() -> list[WorkflowRow]:
    if not is_pool_ready():
        return []
    rows, _ = await db_list(limit=1000, offset=0)
    return rows


def _is_link_public(row: WorkflowRow) -> bool:
    return _visibility(row) in _PUBLIC_VISIBILITIES


async def _resolve_case(public_id: str) -> WorkflowRow:
    if not is_pool_ready():
        raise WorkflowNotFoundError(public_id)
    direct = await db_get_by_public_id(public_id)
    if direct and _is_link_public(direct) and _public_id(direct) == public_id:
        return direct
    for row in await _all_rows():
        if _is_link_public(row) and _public_id(row) == public_id:
            return row
    raise WorkflowNotFoundError(public_id)


async def _load_state(request: Request, thread_id: str) -> dict[str, Any] | None:
    from backend.api.routes.workflow import get_workflow_status

    try:
        response = await get_workflow_status(thread_id, request)
        data = getattr(response, "data", None)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


async def _load_checkpoints(request: Request, thread_id: str) -> list[dict[str, Any]]:
    from backend.api.routes.workflow import get_checkpoint_history

    try:
        response = await get_checkpoint_history(thread_id, request, limit=100)
        data = getattr(response, "data", None)
        checkpoints = data.get("checkpoints", []) if isinstance(data, dict) else []
        return [_checkpoint_dict(item) for item in checkpoints]
    except Exception:
        return []


def _case_payload(
    row: WorkflowRow,
    state: dict[str, Any] | None = None,
    *,
    featured: bool = False,
) -> dict[str, Any]:
    state = state or {}
    result = _public_result(state)
    status = _public_status(state.get("status", row.status), state.get("phase", row.phase))
    title = (
        result.get("title") or result.get("topic") or _safe_text(row.label, 120) or "内容创作案例"
    )
    summary = result.get("summary") or result.get("topic") or "从洞察到产出的完整创作过程"
    return {
        "public_id": _public_id(row),
        "title": title,
        "summary": summary,
        "status": status,
        "phase": _phase(state.get("phase", row.phase)),
        "workflow_mode": row.workflow_mode if row.workflow_mode in {"trend", "brief"} else "trend",
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "featured": featured,
        "replay_available": status != "attention" or bool(state),
        "result_preview": {
            key: result[key]
            for key in ("title", "topic", "hashtags", "visual", "metrics")
            if key in result
        },
    }


@router.get("/showcase/cases")
async def list_public_cases(
    limit: int = Query(24, ge=1, le=100),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None, max_length=80),
    mode: str | None = Query(None),
    status: str | None = Query(None),
    sort: str = Query("recent"),
) -> ApiResponse[Any]:
    """List explicitly public cases without exposing internal workflow IDs."""

    rows = [row for row in await _all_rows() if _visibility(row) == "public"]
    search = q.strip().casefold() if q else ""
    if mode in {"trend", "brief"}:
        rows = [row for row in rows if row.workflow_mode == mode]
    if status in _PUBLIC_STATUS_VALUES:
        rows = [row for row in rows if _public_status(row.status, row.phase) == status]
    if search:
        rows = [row for row in rows if search in (row.label or "").casefold()]
    if sort == "title":
        rows.sort(key=lambda row: (row.label or "内容创作案例").casefold())
    else:
        rows.sort(key=lambda row: row.updated_at or row.created_at, reverse=True)

    featured_row = next((row for row in rows if row.showcase_featured), None)
    if featured_row is None:
        featured_row = next(
            (row for row in rows if row.status == "completed"),
            rows[0] if rows else None,
        )
    page = rows[offset : offset + limit]
    cases = [_case_payload(row, featured=row is featured_row) for row in page]
    return success(
        data={
            "cases": cases,
            "total": len(rows),
            "limit": limit,
            "offset": offset,
            "featured_public_id": _public_id(featured_row) if featured_row else None,
        }
    )


@router.get("/showcase/cases/{public_id}")
async def get_public_case(public_id: str, request: Request) -> ApiResponse[Any]:
    row = await _resolve_case(public_id)
    state = await _load_state(request, row.thread_id)
    payload = _case_payload(row, state, featured=row.showcase_featured)
    payload["result"] = _public_result(state or {})
    return success(data=payload)


@router.get("/replays/{public_id}/manifest")
async def get_public_replay_manifest(
    public_id: str,
    request: Request,
    include_technical: bool = Query(False),
    user: dict[str, Any] | None = Depends(get_optional_user),
) -> ApiResponse[Any]:
    row = await _resolve_case(public_id)
    checkpoints = await _load_checkpoints(request, row.thread_id)
    allow_technical = bool(user) and include_technical
    visible = checkpoints if allow_technical else _key_checkpoints(checkpoints)
    steps = [_public_step(row.thread_id, checkpoint) for checkpoint in visible]
    return success(
        data={
            "public_id": public_id,
            "view": "all" if allow_technical else "key",
            "steps": steps,
            "has_more": False,
            "technical_steps_available": bool(
                user and len(checkpoints) > len(_key_checkpoints(checkpoints))
            ),
            "workflow": _case_payload(row),
        }
    )


async def _resolve_checkpoint(
    public_id: str,
    checkpoint_public_id: str,
    request: Request,
    user: dict[str, Any] | None,
    include_technical: bool,
) -> tuple[WorkflowRow, dict[str, Any]]:
    row = await _resolve_case(public_id)
    checkpoints = await _load_checkpoints(request, row.thread_id)
    key_ids = {
        _step_public_id(row.thread_id, str(cp.get("checkpoint_id") or cp.get("step", 0)))
        for cp in _key_checkpoints(checkpoints)
    }
    if not (user and include_technical):
        checkpoints = [
            checkpoint
            for checkpoint in _key_checkpoints(checkpoints)
            if _step_public_id(
                row.thread_id,
                str(checkpoint.get("checkpoint_id") or checkpoint.get("step", 0)),
            )
            in key_ids
        ]
    for checkpoint in checkpoints:
        candidate = _step_public_id(
            row.thread_id,
            str(checkpoint.get("checkpoint_id") or checkpoint.get("step", 0)),
        )
        if candidate == checkpoint_public_id:
            return row, checkpoint
    raise WorkflowNotFoundError(checkpoint_public_id)


@router.get("/replays/{public_id}/checkpoints/{checkpoint_public_id}")
async def get_public_checkpoint_detail(
    public_id: str,
    checkpoint_public_id: str,
    request: Request,
    include_technical: bool = Query(False),
    user: dict[str, Any] | None = Depends(get_optional_user),
) -> ApiResponse[Any]:
    row, checkpoint = await _resolve_checkpoint(
        public_id, checkpoint_public_id, request, user, include_technical
    )
    step = _public_step(row.thread_id, checkpoint)
    step["result"] = _public_result(checkpoint)
    if user and include_technical:
        # Advanced mode is still presenter-safe: it exposes a readable phase
        # and step number, never raw state, provider errors, or internal IDs.
        step["technical"] = {
            "phase": step["phase"],
            "step": step["step"],
            "has_next": bool(checkpoint.get("next_nodes")),
        }
    return success(data=step)


@router.get("/replays/{public_id}/final-summary")
async def get_public_final_summary(public_id: str, request: Request) -> ApiResponse[Any]:
    row = await _resolve_case(public_id)
    state = await _load_state(request, row.thread_id)
    final_source = state or {}
    if not _public_result(final_source):
        checkpoints = await _load_checkpoints(request, row.thread_id)
        if checkpoints:
            final_source = max(checkpoints, key=lambda item: item.get("step", 0))
    result = _public_result(final_source)
    return success(
        data={
            "public_id": public_id,
            "status": _public_status(
                (state or {}).get("status", row.status), (state or {}).get("phase", row.phase)
            ),
            "result": result,
            "stable": True,
        }
    )
