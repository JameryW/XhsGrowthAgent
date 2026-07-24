"""Public, redacted read APIs for Showcase and Workflow Replay.

The internal workflow endpoints return the full execution state because the
workspace needs it for operations.  Public pages use this router instead so
visibility, identifiers, payload size, and redaction remain server-side
contracts rather than frontend conventions.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Any, Literal, cast
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from backend.api.deps import get_current_user, get_optional_user
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
from backend.db.workflows import (
    update_workflow as db_update,
)

router = APIRouter()


class ShowcaseVisibilityUpdate(BaseModel):
    """Authenticated operator payload for approving or revoking a case."""

    visibility: Literal["private", "unlisted", "public"]
    public_title: str | None = Field(default=None, max_length=120)
    public_summary: str | None = Field(default=None, max_length=360)
    featured: bool = False
    featured_rank: int | None = Field(default=None, ge=0, le=1000)


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
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_COLOR_RE = re.compile(
    r"^(?:#[0-9a-f]{3,8}|(?:rgb|rgba|hsl|hsla)\([0-9a-z%.,\s()/+-]{1,64}\))$",
    re.IGNORECASE,
)
_SAFE_COLOR_NAMES = {
    "amber",
    "black",
    "blue",
    "cyan",
    "gray",
    "green",
    "indigo",
    "orange",
    "pink",
    "purple",
    "red",
    "rose",
    "slate",
    "teal",
    "violet",
    "white",
    "yellow",
}
_DEFAULT_PUBLIC_HOSTS = {"xiaohongshu.com", "www.xiaohongshu.com", "xhslink.com"}


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
    text = _EMAIL_RE.sub("[已脱敏邮箱]", text)
    text = _PHONE_RE.sub("[已脱敏电话]", text)
    text = _UUID_RE.sub("[已脱敏标识]", text)
    return text[:limit] + ("…" if len(text) > limit else "")


def _safe_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        return None
    configured_hosts = {
        host.strip().lower()
        for host in os.environ.get("XHS_PUBLIC_URL_HOSTS", "").split(",")
        if host.strip()
    }
    allowed_hosts = configured_hosts or _DEFAULT_PUBLIC_HOSTS
    hostname = parsed.hostname.lower()
    if not any(hostname == host or hostname.endswith(f".{host}") for host in allowed_hosts):
        return None
    return url[:500]


def _public_error_category(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    lowered = value.casefold()
    if any(token in lowered for token in ("auth", "token", "credential", "permission")):
        return "authorization"
    if any(token in lowered for token in ("timeout", "timed out", "deadline")):
        return "timeout"
    if any(token in lowered for token in ("rate", "limit", "quota")):
        return "rate_limited"
    if any(token in lowered for token in ("network", "connection", "unavailable")):
        return "service_unavailable"
    return "processing"


def _cache_headers(
    payload: dict[str, Any],
    request: Request | None,
    response: Response | None,
    *,
    last_modified: str | None = None,
) -> Response | None:
    """Apply short public caching and honor conditional GETs."""

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    etag = f'"{hashlib.sha256(encoded).hexdigest()[:24]}"'
    headers = {
        "ETag": etag,
        "Cache-Control": "public, max-age=30, stale-while-revalidate=60",
        "Vary": "Accept-Encoding",
    }
    if last_modified:
        try:
            parsed = datetime.fromisoformat(last_modified.replace("Z", "+00:00"))
            headers["Last-Modified"] = format_datetime(parsed.astimezone(UTC), usegmt=True)
        except ValueError:
            pass
    if response is not None:
        response.headers.update(headers)
    if request is not None and request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
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


def _safe_colors(value: Any, limit: int = 5) -> list[str]:
    """Keep palette values safe for the frontend's CSS color binding."""

    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        color = item.strip()
        if color.casefold() not in _SAFE_COLOR_NAMES and not _COLOR_RE.fullmatch(color):
            continue
        result.append(color)
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
    palette = _safe_colors(visual.get("color_palette"), 5)
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
    error_category = _public_error_category(source.get("error"))
    if error_category:
        result["error_category"] = error_category
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
    phase = _phase(checkpoint.get("phase"))
    return bool(
        _public_result(checkpoint)
        or checkpoint.get("decision")
        or phase in {"reviewing", "publishing", "analyzing", "completed"}
    )


def _is_decision_checkpoint(checkpoint: dict[str, Any]) -> bool:
    return bool(
        checkpoint.get("decision")
        or _phase(checkpoint.get("phase")) in {"reviewing", "publishing", "completed"}
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
        "has_business_data": bool(result),
        "is_decision": _is_decision_checkpoint(checkpoint),
        "error_category": _public_error_category(checkpoint.get("error")),
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


async def _resolve_any_case(public_id: str) -> WorkflowRow:
    """Resolve a case for the authenticated visibility-management endpoint."""

    if not is_pool_ready():
        raise WorkflowNotFoundError(public_id)
    direct = await db_get_by_public_id(public_id)
    if direct and _public_id(direct) == public_id:
        return direct
    for row in await _all_rows():
        if _public_id(row) == public_id:
            return row
    raise WorkflowNotFoundError(public_id)


async def _load_state(request: Request, thread_id: str) -> dict[str, Any] | None:
    from backend.api.deps import service_identity
    from backend.api.routes.workflow import get_workflow_status

    try:
        # Internal anonymous read: present the trusted service identity so the
        # authenticated status route accepts this direct (non-HTTP) call.
        response = await get_workflow_status(thread_id, request, service_identity())
        data = getattr(response, "data", None)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


async def _load_checkpoints(request: Request, thread_id: str) -> list[dict[str, Any]]:
    import logging

    from backend.api.routes.workflow import get_checkpoint_history

    try:
        # before=None must be passed explicitly: get_checkpoint_history is a
        # FastAPI route, and calling it directly leaves `before` at its raw
        # Query(None) default — a truthy FieldInfo — which builds a broken
        # cursor config, raises inside aget_state_history, and (via the except
        # below) silently empties the replay manifest.
        response = await get_checkpoint_history(thread_id, request, limit=100, before=None)
        data = getattr(response, "data", None)
        checkpoints = data.get("checkpoints", []) if isinstance(data, dict) else []
        return [_checkpoint_dict(item) for item in checkpoints]
    except Exception:
        logging.getLogger(__name__).warning("Failed to load checkpoints for replay", exc_info=True)
        return []


_SUMMARY_PROMPT = {
    "system": (
        "你是小红书内容增长平台的案例编辑。根据给定的笔记信息，为公开案例展示页"
        "撰写一句中文摘要（40-80 字），概括选题角度与内容亮点；语气客观克制，"
        '不使用 emoji，不得编造输入中不存在的数据。只输出 JSON：{"summary": "..."}'
    ),
    "user_template": (
        "标题：{title}\n选题：{topic}\n目标受众：{audience}\n内容要点：{key_points}\n"
        "正文：{body}\n真实数据：{metrics}"
    ),
}

# Bound on concurrent LLM/state reads during lazy list backfill.
_SUMMARY_BACKFILL_CONCURRENCY = 4


def _summary_metrics_text(metrics: dict[str, Any]) -> str:
    parts = []
    for key, label in (
        ("views", "阅读"),
        ("likes", "点赞"),
        ("collects", "收藏"),
        ("comments", "评论"),
    ):
        value = metrics.get(key)
        if isinstance(value, (int, float)):
            parts.append(f"{label} {int(value)}")
    return "、".join(parts) if parts else "（暂无）"


async def _generate_case_summary(state: dict[str, Any] | None, row: WorkflowRow) -> str | None:
    """Generate a public case summary: LLM-polished, deterministic fallback.

    Returns ``None`` when there is no meaningful source content at all, so
    callers can keep the generic placeholder instead of persisting noise.
    LLM output passes the same ``_safe_text`` redaction as operator input.
    """

    result = _public_result(state or {})
    fallback = result.get("summary") or result.get("topic")
    if not fallback:
        # No state-derived content (e.g. missing checkpoint): an LLM summary
        # written from the label alone would be invention, so keep the generic
        # placeholder instead of persisting noise.
        return None
    title = (
        _safe_text(row.public_title, 120) or result.get("title") or _safe_text(row.label, 120) or ""
    )

    def _fallback(_data: dict[str, Any]) -> dict[str, Any]:
        return {"summary": fallback}

    inputs = {
        "title": title or "（无）",
        "topic": result.get("topic") or "（无）",
        "audience": result.get("target_audience") or "（无）",
        "key_points": "、".join(result.get("key_points") or []) or "（无）",
        "body": result.get("summary") or "（无）",
        "metrics": _summary_metrics_text(result.get("metrics") or {}),
    }
    try:
        from backend.config.models import TaskType
        from backend.services.llm_enrichment import get_llm_service

        generated = await get_llm_service().enrich_with_llm(
            task_type=TaskType.WRITING,
            prompt_template=_SUMMARY_PROMPT,
            input_data=inputs,
            fallback_fn=_fallback,
        )
    except Exception:
        generated = _fallback(inputs)
    if isinstance(generated, dict):
        text = _safe_text(generated.get("summary"), 360)
        if text:
            return text
    return _safe_text(fallback, 360)


async def _backfill_missing_summaries(request: Request, rows: list[WorkflowRow]) -> None:
    """Generate and persist summaries for listed public rows that lack one.

    The list reader never loads workflow state for card rendering, so rows
    approved before summary generation existed would show the generic
    placeholder forever.  Generation is bounded and write-through: the first
    listing pays it once, later reads stay on the persisted column.  The
    backfill never touches ``updated_at`` so it cannot reorder recent-first
    listings.
    """

    pending = [row for row in rows if not _safe_text(row.public_summary, 360)]
    if not pending:
        return
    semaphore = asyncio.Semaphore(_SUMMARY_BACKFILL_CONCURRENCY)

    async def _backfill(row: WorkflowRow) -> None:
        async with semaphore:
            try:
                state = await _load_state(request, row.thread_id)
                summary = await _generate_case_summary(state, row)
                if not summary:
                    return
                updated = await db_update(
                    row.thread_id, public_summary=summary, touch_updated_at=False
                )
                if updated is not None:
                    row.public_summary = updated.public_summary
            except Exception:
                import logging

                logging.getLogger(__name__).warning(
                    "showcase summary backfill failed for a case", exc_info=True
                )

    await asyncio.gather(*(_backfill(row) for row in pending))


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
        _safe_text(row.public_title, 120)
        or result.get("title")
        or result.get("topic")
        or _safe_text(row.label, 120)
        or "内容创作案例"
    )
    summary = (
        _safe_text(row.public_summary, 360)
        or result.get("summary")
        or result.get("topic")
        or "从洞察到产出的完整创作过程"
    )
    payload: dict[str, Any] = {
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
    if state:
        payload["has_final_summary"] = bool(result)
        payload["has_publish_result"] = bool(result.get("publish"))
    if row.featured_rank is not None:
        payload["featured_rank"] = row.featured_rank
    return payload


@router.get("/showcase/cases", response_model=None)
async def list_public_cases(
    request: Request,
    response: Response,
    limit: int = Query(24, ge=1, le=100),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None, max_length=80),
    mode: str | None = Query(None),
    status: str | None = Query(None),
    sort: str = Query("recent"),
) -> ApiResponse[Any] | Response:
    """List explicitly public cases without exposing internal workflow IDs."""

    rows = [row for row in await _all_rows() if _visibility(row) == "public"]
    search = q.strip().casefold() if q else ""
    if mode in {"trend", "brief"}:
        rows = [row for row in rows if row.workflow_mode == mode]
    if status in _PUBLIC_STATUS_VALUES:
        rows = [row for row in rows if _public_status(row.status, row.phase) == status]
    if search:
        rows = [
            row
            for row in rows
            if search
            in " ".join(
                value.casefold()
                for value in (row.public_title, row.public_summary, row.label)
                if value
            )
        ]
    if sort == "title":
        rows.sort(
            key=lambda row: (
                row.public_title or row.public_summary or row.label or "内容创作案例"
            ).casefold()
        )
    else:
        rows.sort(key=lambda row: row.updated_at or row.created_at, reverse=True)

    featured_row = next(
        (
            row
            for row in sorted(
                (item for item in rows if item.showcase_featured or item.featured_rank is not None),
                key=lambda item: item.featured_rank if item.featured_rank is not None else 10**9,
            )
        ),
        None,
    )
    if featured_row is None:
        featured_row = next(
            (row for row in rows if row.status == "completed"),
            rows[0] if rows else None,
        )
    page = rows[offset : offset + limit]
    # Write-through backfill for rows approved before summaries were generated.
    await _backfill_missing_summaries(request, page)
    cases = [_case_payload(row, featured=row is featured_row) for row in page]
    data = {
        "cases": cases,
        "total": len(rows),
        "limit": limit,
        "offset": offset,
        "featured_public_id": _public_id(featured_row) if featured_row else None,
    }
    not_modified = _cache_headers(
        data,
        request,
        response,
        last_modified=max((row.updated_at for row in rows), default=None),
    )
    return not_modified or success(data=data)


@router.put("/admin/showcase/cases/{public_id}")
async def update_showcase_visibility(
    public_id: str,
    payload: ShowcaseVisibilityUpdate,
    request: Request,
    current: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Approve, edit, or revoke a public case from the authenticated console."""

    row = await _resolve_any_case(public_id)
    is_public = payload.visibility in _PUBLIC_VISIBILITIES
    approved_at = datetime.now(UTC).isoformat() if is_public else None
    approved_by = (current.get("username") or current.get("id")) if is_public else None
    featured = bool(payload.featured and payload.visibility == "public")
    public_summary = _safe_text(payload.public_summary, 360)
    summary_auto_generated = False
    if is_public and not public_summary:
        # Operator left the summary blank: generate one from the workflow
        # content (LLM-polished with a deterministic excerpt fallback) so the
        # public card never shows the generic placeholder.
        state = await _load_state(request, row.thread_id)
        public_summary = await _generate_case_summary(state, row)
        summary_auto_generated = public_summary is not None
    updated = await db_update(
        row.thread_id,
        showcase_visibility=payload.visibility,
        public_id=_public_id(row),
        showcase_featured=featured,
        featured_rank=payload.featured_rank if featured else None,
        public_title=_safe_text(payload.public_title, 120),
        public_summary=public_summary,
        approved_at=approved_at,
        approved_by=approved_by,
        redaction_version="v1",
    )
    if updated is None:
        raise WorkflowNotFoundError(public_id)
    return success(
        data={
            "public_id": _public_id(updated),
            "visibility": payload.visibility,
            "approved_at": approved_at,
            "approved_by": approved_by,
            "summary_auto_generated": summary_auto_generated,
            "case": _case_payload(updated, featured=featured),
        }
    )


@router.delete("/admin/showcase/cases/{public_id}")
async def revoke_showcase_visibility(
    public_id: str,
    current: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Revoke public visibility without exposing the internal workflow ID."""

    row = await _resolve_any_case(public_id)
    updated = await db_update(
        row.thread_id,
        showcase_visibility="private",
        public_id=_public_id(row),
        showcase_featured=False,
        featured_rank=None,
        approved_at=None,
        approved_by=None,
        updated_at=datetime.now(UTC).isoformat(),
    )
    if updated is None:
        raise WorkflowNotFoundError(public_id)
    return success(
        data={
            "public_id": _public_id(updated),
            "visibility": "private",
            "revoked_by": current.get("username") or current.get("id"),
        }
    )


@router.get("/showcase/cases/{public_id}", response_model=None)
async def get_public_case(
    public_id: str,
    request: Request,
    response: Response,
) -> ApiResponse[Any] | Response:
    row = await _resolve_case(public_id)
    state = await _load_state(request, row.thread_id)
    payload = _case_payload(row, state, featured=row.showcase_featured)
    payload["result"] = _public_result(state or {})
    not_modified = _cache_headers(payload, request, response, last_modified=row.updated_at)
    return not_modified or success(data=payload)


@router.get("/replays/{public_id}/manifest", response_model=None)
async def get_public_replay_manifest(
    public_id: str,
    request: Request,
    response: Response,
    include_technical: bool = Query(False),
    user: dict[str, Any] | None = Depends(get_optional_user),
    limit: int = 20,
    offset: int = 0,
) -> ApiResponse[Any] | Response:
    row = await _resolve_case(public_id)
    limit = max(1, min(int(limit), 20))
    offset = max(0, int(offset))
    checkpoints = await _load_checkpoints(request, row.thread_id)
    allow_technical = bool(user) and include_technical
    key_checkpoints = _key_checkpoints(checkpoints)
    visible = checkpoints if allow_technical else key_checkpoints
    page = visible[offset : offset + limit]
    data = {
        "public_id": public_id,
        "view": "all" if allow_technical else "key",
        "steps": [_public_step(row.thread_id, checkpoint) for checkpoint in page],
        "offset": offset,
        "limit": limit,
        "total_steps": len(visible),
        "key_step_count": len(key_checkpoints),
        "technical_step_count": len(checkpoints),
        "has_more": offset + limit < len(visible),
        "technical_steps_available": bool(user and len(checkpoints) > len(key_checkpoints)),
        "workflow": _case_payload(row),
    }
    not_modified = _cache_headers(data, request, response, last_modified=row.updated_at)
    return not_modified or success(data=data)


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


@router.get("/replays/{public_id}/checkpoints/{checkpoint_public_id}", response_model=None)
async def get_public_checkpoint_detail(
    public_id: str,
    checkpoint_public_id: str,
    request: Request,
    response: Response,
    include_technical: bool = Query(False),
    user: dict[str, Any] | None = Depends(get_optional_user),
) -> ApiResponse[Any] | Response:
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
    not_modified = _cache_headers(step, request, response, last_modified=step.get("created_at"))
    return not_modified or success(data=step)


@router.get("/replays/{public_id}/final-summary", response_model=None)
async def get_public_final_summary(
    public_id: str,
    request: Request,
    response: Response,
) -> ApiResponse[Any] | Response:
    row = await _resolve_case(public_id)
    state = await _load_state(request, row.thread_id)
    final_source = state or {}
    if not _public_result(final_source):
        checkpoints = await _load_checkpoints(request, row.thread_id)
        if checkpoints:
            final_source = max(checkpoints, key=lambda item: item.get("step", 0))
    result = _public_result(final_source)
    data = {
        "public_id": public_id,
        "status": _public_status(
            (state or {}).get("status", row.status), (state or {}).get("phase", row.phase)
        ),
        "result": result,
        "stable": True,
    }
    not_modified = _cache_headers(data, request, response, last_modified=row.updated_at)
    return not_modified or success(data=data)
