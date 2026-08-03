"""Analytics API routes — growth reports, creator-stats import, and creative advice."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator

from backend.api.account_scope import require_owned_account, resolve_required_account_id
from backend.api.deps import get_current_user
from backend.api.errors import CreatorNoteNotFoundError, ValidationError
from backend.api.responses import ApiResponse, success
from backend.db.pool import is_pool_ready
from backend.db.workflows import list_workflows as db_list
from backend.services.quality_consistency import (
    QUALITY_CONSISTENCY_CONTRACT,
    quality_consistency_v2_enabled,
)
from backend.services.quality_consistency import (
    snapshot_id as build_snapshot_id,
)

router = APIRouter()


class CreatorStatsSyncRequest(BaseModel):
    """Trigger creator-center statistics import for a bound account browser."""

    account_id: str = Field(..., min_length=1, description="账号 ID")
    dry_run: bool = Field(
        default=False,
        description="旧版兼容字段，会被忽略；HTTP 导入始终使用绑定浏览器",
    )
    cookie: str = Field(
        default="",
        description="旧版兼容字段，会被忽略；真实同步必须使用账号绑定的浏览器登录态",
    )
    period: str = Field(default="30d", description="统计周期")
    analyze: bool = Field(default=True, description="导入后是否跑创作分析并沉淀风格")

    @field_validator("account_id", mode="before")
    @classmethod
    def _strip_account_id(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v).strip()


class CreatorStatsSyncAllRequest(BaseModel):
    """Trigger the atomic batch import for enabled accounts only."""

    period: str = Field(default="30d", description="统计周期")
    analyze: bool = Field(default=True, description="导入后是否跑创作分析并沉淀风格")


# Simple in-memory cache with TTL
_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 30  # seconds

# Bound on concurrent checkpointer reads in _get_completed_workflows.  The
# checkpointer pool is created with max_size=10 (backend/graph/builder.py), so
# 8 leaves headroom for the rest of the app while still parallelizing cold
# dashboard loads.
_STATE_FETCH_CONCURRENCY = 8


async def _creator_snapshot_metadata(account_id: str) -> dict[str, Any]:
    """Return shared imported-note snapshot metadata without triggering sync."""

    normalized = (account_id or "").strip()
    if not normalized:
        return {"data_as_of": None, "snapshot_id": None}

    bundle = await _creator_snapshot_bundle(normalized)
    return {
        key: bundle[key]
        for key in ("account_id", "data_as_of", "snapshot_id", "note_count")
        if key in bundle
    }


async def _creator_snapshot_bundle(account_id: str) -> dict[str, Any]:
    """Read imported facts and snapshot metadata from one storage boundary."""

    normalized = (account_id or "").strip()
    if not normalized:
        return {
            "account_id": "",
            "account": None,
            "notes": [],
            "data_as_of": None,
            "snapshot_id": None,
            "note_count": 0,
        }

    try:
        from backend.db import creator_stats as stats_db

        return await stats_db.get_creator_stats_snapshot_bundle(normalized)
    except Exception:
        # The imported tables are optional in local/legacy deployments.  Do
        # not invent a timestamp when they are unavailable.
        return {
            "account_id": normalized,
            "account": None,
            "notes": [],
            "data_as_of": None,
            "snapshot_id": None,
            "note_count": 0,
        }


def _workflow_data_as_of(workflows: list[dict[str, Any]]) -> str | None:
    """Use the latest workflow update as a fallback when no imported snapshot exists."""

    values: list[str] = []
    for workflow in workflows:
        state = workflow.get("_state") or {}
        values.extend(
            str(value)
            for value in (
                workflow.get("updated_at"),
                state.get("updated_at"),
            )
            if str(value or "").strip()
        )
    return max(values) if values else None


def _complete_snapshot_metadata(
    account_id: str, metadata: dict[str, Any], workflows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Ensure every analytics response has a meaningful as-of when possible."""

    if metadata.get("data_as_of"):
        return metadata
    fallback = _workflow_data_as_of(workflows)
    if not fallback:
        return metadata
    return {
        "data_as_of": fallback,
        "snapshot_id": build_snapshot_id(account_id, fallback),
    }


def _get_cached(key: str) -> Any | None:
    if key in _cache:
        ts, val = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return val
        del _cache[key]
    return None


def _set_cached(key: str, value: Any) -> None:
    _cache[key] = (time.time(), value)


async def _get_completed_workflows(
    graph: Any, account_id: str | None = None
) -> list[dict[str, Any]]:
    """Read full state for completed workflows, with caching.

    Checkpoint reads run concurrently (bounded by ``_STATE_FETCH_CONCURRENCY``):
    each ``aget_state`` is a separate checkpointer round trip, so fetching them
    serially made every cold dashboard/report request cost N sequential reads.
    """
    cache_key = f"completed_{account_id or 'all'}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cast(list[dict[str, Any]], cached)

    rows: list[Any] = []
    if is_pool_ready():
        # Include completed and analyzing workflows (both have publish_result)
        for status_filter in ("completed", "analyzing"):
            offset = 0
            while True:
                batch, total = await db_list(
                    account_id=account_id,
                    status=status_filter,
                    limit=100,
                    offset=offset,
                )
                if not batch:
                    break
                rows.extend(batch)
                offset += len(batch)
                if offset >= total or len(batch) < 100:
                    break

    semaphore = asyncio.Semaphore(_STATE_FETCH_CONCURRENCY)

    async def _read_workflow_state(row: Any) -> dict[str, Any] | None:
        if account_id and row.account_id != account_id:
            return None
        async with semaphore:
            try:
                config = {"configurable": {"thread_id": row.thread_id}}
                state = await graph.aget_state(config)
            except Exception:
                return None
        if not state.values:
            return None
        return {**row.to_dict(), "_state": state.values}

    # gather preserves input order, so results stay in created_at DESC order.
    fetched = await asyncio.gather(*(_read_workflow_state(row) for row in rows))
    results = [item for item in fetched if item is not None]

    _set_cached(cache_key, results)
    return results


def _period_cutoff_hours(period: str) -> int:
    """Convert period string to cutoff hours."""
    if period == "daily":
        return 24
    elif period == "weekly":
        return 7 * 24
    else:
        return 30 * 24


def _period_window(period: str) -> timedelta:
    """Return the duration used by the current and previous analytics windows."""
    return timedelta(hours=_period_cutoff_hours(period))


def _parse_published_at(value: Any) -> datetime | None:
    """Parse a post timestamp into an aware UTC datetime."""
    if value is None or value == "":
        return None
    try:
        published = datetime.fromisoformat(str(value).replace(" ", "T"))
    except (ValueError, AttributeError, TypeError):
        return None
    if published.tzinfo is None:
        published = published.replace(tzinfo=UTC)
    return published.astimezone(UTC)


def _split_period_posts(
    posts: list[dict[str, Any]], period: str, *, now: datetime | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split posts into complete current and previous windows.

    The split is deliberately performed before response pagination.  This
    keeps period-over-period aggregates correct even when the visible post
    table is limited to the newest 20 rows.
    """
    end = (now or datetime.now(UTC)).astimezone(UTC)
    window = _period_window(period)
    current_start = end - window
    previous_start = current_start - window
    current: list[dict[str, Any]] = []
    previous: list[dict[str, Any]] = []
    for post in posts:
        published = _parse_published_at(post.get("published_at"))
        if published is None:
            continue
        if current_start <= published <= end:
            current.append(post)
        elif previous_start <= published < current_start:
            previous.append(post)
    return current, previous


def _filter_by_period(posts: list[dict[str, Any]], period: str) -> list[dict[str, Any]]:
    """Filter posts by time period.

    Posts without a parseable ``published_at`` are excluded (period-scoped
    analytics must not treat undated rows as always-in-range).
    """
    current, _previous = _split_period_posts(posts, period)
    return current


def _period_metrics(posts: list[dict[str, Any]]) -> dict[str, float | int]:
    """Aggregate a complete period without applying the visible table limit.

    Fallback path when Creator Center daily series are unavailable: sum the
    lifetime metrics of notes *published* in the window. This is not the same
    as Creator Center period totals (view events in-window across all notes).
    """
    likes = sum(int(p.get("likes") or 0) for p in posts)
    comments = sum(int(p.get("comments") or 0) for p in posts)
    collects = sum(int(p.get("collects") or 0) for p in posts)
    shares = sum(int(p.get("shares") or 0) for p in posts)
    engagement = likes + comments + collects
    # Rates are expected as percent-like numbers here (see
    # ``_imported_notes_as_posts``); keep enough precision for later fraction
    # serialization instead of rounding the mean to one decimal early.
    rates = [float(p.get("engagement_rate") or 0.0) for p in posts]
    return {
        "posts": len(posts),
        "views": sum(int(p.get("views") or 0) for p in posts),
        "likes": likes,
        "comments": comments,
        "collects": collects,
        "shares": shares,
        "engagement": engagement,
        "avg_engagement_rate": round(sum(rates) / len(rates), 4) if rates else 0.0,
    }


def _parse_series_point_time(value: Any) -> datetime | None:
    """Parse Creator Center daily-series point timestamps (unix ms/s or ISO)."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        ts = float(value)
        # Creator Center uses millisecond epoch; seconds are < 1e12.
        if ts > 1e12:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    return _parse_published_at(value)


def _sum_detail_series(
    series: Any,
    *,
    start: datetime,
    end: datetime,
    end_exclusive: bool = False,
) -> int:
    """Sum ``count`` for series points whose date falls in [start, end] (or [start, end))."""
    if not isinstance(series, list):
        return 0
    total = 0
    for point in series:
        if not isinstance(point, dict):
            continue
        point_time = _parse_series_point_time(point.get("date") or point.get("day"))
        if point_time is None:
            continue
        if point_time < start:
            continue
        if end_exclusive:
            if point_time >= end:
                continue
        elif point_time > end:
            continue
        try:
            total += max(0, int(point.get("count") or 0))
        except (TypeError, ValueError):
            continue
    return total


def _period_metrics_from_detail(
    detail_metrics: dict[str, Any],
    period: str,
    *,
    posts_in_window: int,
    now: datetime | None = None,
    previous: bool = False,
) -> dict[str, Any] | None:
    """Build period metrics from Creator Center daily series when present.

    Account overview ``views`` / ``detail_metrics.view_list`` count *view events
    in the selected window across all notes* — the same semantics as the
    Creator Center dashboard. Summing lifetime note metrics for notes published
    in the window systematically understates that number (e.g. 149 vs 3822).
    """
    if not isinstance(detail_metrics, dict) or not detail_metrics:
        return None
    view_list = detail_metrics.get("view_list")
    if not isinstance(view_list, list) or not view_list:
        return None

    end = (now or datetime.now(UTC)).astimezone(UTC)
    window = _period_window(period)
    current_start = end - window
    previous_start = current_start - window
    if previous:
        start, stop, end_exclusive = previous_start, current_start, True
    else:
        start, stop, end_exclusive = current_start, end, False

    views = _sum_detail_series(view_list, start=start, end=stop, end_exclusive=end_exclusive)
    likes = _sum_detail_series(
        detail_metrics.get("like_list"), start=start, end=stop, end_exclusive=end_exclusive
    )
    comments = _sum_detail_series(
        detail_metrics.get("comment_list"), start=start, end=stop, end_exclusive=end_exclusive
    )
    collects = _sum_detail_series(
        detail_metrics.get("collect_list"), start=start, end=stop, end_exclusive=end_exclusive
    )
    shares = _sum_detail_series(
        detail_metrics.get("share_list"), start=start, end=stop, end_exclusive=end_exclusive
    )
    engagement = likes + comments + collects
    # Percent-like rate so ``_serialize_analytics_rate_units`` can normalize.
    avg_rate = round((engagement / views) * 100.0, 4) if views > 0 else 0.0
    return {
        "posts": posts_in_window,
        "views": views,
        "likes": likes,
        "comments": comments,
        "collects": collects,
        "shares": shares,
        "engagement": engagement,
        "avg_engagement_rate": avg_rate,
        "metric_source": "creator_center_series",
    }


def _build_period_summary(
    posts: list[dict[str, Any]],
    period: str,
    *,
    now: datetime | None = None,
    detail_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the server-owned current/previous aggregate contract.

    Prefer Creator Center daily series (``detail_metrics.*_list``) for
    views/likes/comments/collects/shares so cards match the official
    dashboard. Fall back to summing note rows when series are missing.
    ``posts`` still drives how many notes were *published* in each window.
    """
    current, previous = _split_period_posts(posts, period, now=now)
    current_metrics = _period_metrics_from_detail(
        detail_metrics or {},
        period,
        posts_in_window=len(current),
        now=now,
        previous=False,
    )
    previous_metrics = _period_metrics_from_detail(
        detail_metrics or {},
        period,
        posts_in_window=len(previous),
        now=now,
        previous=True,
    )
    if current_metrics is None:
        current_metrics = _period_metrics(current)
    if previous_metrics is None:
        previous_metrics = _period_metrics(previous)
    return {
        "period": period,
        "current": current_metrics,
        "previous": previous_metrics,
    }


def _as_percent_engagement_rate(value: Any) -> float:
    """Normalize engagement rate to a 0–100 percent-like number for UI/report.

    Workflow analytics may store fractions (0.05) or percents (5.0). Imported
    creator-center notes use 0–1 fractions. Mixing them without conversion
    corrupts dashboard averages.
    """
    try:
        er = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if er < 0:
        return 0.0
    if er <= 1.0:
        return round(er * 100.0, 2)
    return round(er, 2)


def _as_fraction_engagement_rate(value: Any) -> float:
    """Normalize an internal percent/fraction rate to the public fraction unit."""

    try:
        rate = float(value or 0.0)
    except (TypeError, ValueError):
        rate = 0.0
    if rate < 0:
        return 0.0
    if rate > 1.0:
        rate /= 100.0
    return round(min(rate, 1.0), 6)


def _serialize_analytics_rate_units(
    *,
    posts: list[dict[str, Any]] | None = None,
    report: dict[str, Any] | None = None,
    period_summary: dict[str, Any] | None = None,
) -> None:
    """Convert analytics response rates at the API boundary to fractions."""

    for post in posts or []:
        post["engagement_rate"] = _as_fraction_engagement_rate(post.get("engagement_rate"))
    if report is not None:
        metrics = report.get("metrics")
        if isinstance(metrics, dict) and "avg_engagement_rate" in metrics:
            metrics["avg_engagement_rate"] = _as_fraction_engagement_rate(
                metrics.get("avg_engagement_rate")
            )
        report["engagement_rate_unit"] = "fraction"
    if period_summary is not None:
        for key in ("current", "previous"):
            metrics = period_summary.get(key)
            if isinstance(metrics, dict) and "avg_engagement_rate" in metrics:
                metrics["avg_engagement_rate"] = _as_fraction_engagement_rate(
                    metrics.get("avg_engagement_rate")
                )
        period_summary["engagement_rate_unit"] = "fraction"


def _normalize_platform_post_id(value: Any) -> str:
    """Normalize a platform post identifier without accepting synthetic IDs."""
    raw = str(value or "").strip()
    if not raw or raw.startswith("mock_") or raw.startswith("workflow:"):
        return ""
    if "://" in raw:
        parsed = urlparse(raw)
        path_id = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if path_id:
            raw = path_id
    return raw


def _extract_post_data(
    wf_state: dict[str, Any], account_id: str | None = None
) -> dict[str, Any] | None:
    """Extract post performance data from a completed workflow state."""
    publish = wf_state.get("publish_result") or {}
    analytics = wf_state.get("analytics") or {}
    copy = wf_state.get("copy_content") or {}
    plan = wf_state.get("content_plan") or {}

    # Skip failed publishes (but include dry_run/mock)
    status = publish.get("status", "")
    if status == "failed":
        return None

    title = copy.get("selected_title") or plan.get("selected_topic") or publish.get("title", "")

    if not title and not analytics:
        return None

    is_dry_run = status == "mock_published"
    workflow_thread_id = str(
        publish.get("workflow_thread_id")
        or wf_state.get("session_id")
        or wf_state.get("thread_id")
        or ""
    ).strip()
    platform_post_id = _normalize_platform_post_id(
        publish.get("platform_post_id") or publish.get("post_id")
    )
    # Synthetic/session ids are display keys only; only an explicit platform
    # id may link an imported Creator Center note.
    display_id = platform_post_id or (
        f"workflow:{workflow_thread_id}" if workflow_thread_id else ""
    )

    # Prefer explicit engagement_rate; otherwise derive from counts/views
    raw_er = analytics.get("engagement_rate")
    if raw_er is None or raw_er == "":
        views = int(analytics.get("views") or 0)
        if views > 0:
            eng = (
                int(analytics.get("likes") or 0)
                + int(analytics.get("comments") or 0)
                + int(analytics.get("collects") or 0)
                + int(analytics.get("shares") or 0)
            )
            raw_er = eng / views
        else:
            raw_er = 0.0

    return {
        "id": display_id,
        "account_id": account_id or wf_state.get("account_id", ""),
        "workflow_thread_id": workflow_thread_id,
        "platform_post_id": platform_post_id,
        "link_status": "unmatched",
        "source": "workflow",
        "subject_type": "workflow_draft",
        "subject_id": workflow_thread_id,
        "scope": "workflow_draft",
        "assessment_type": "historical_performance",
        "status": "ready",
        "title": title,
        "likes": analytics.get("likes", 0),
        "comments": analytics.get("comments", 0),
        "collects": analytics.get("collects", 0),
        "shares": analytics.get("shares", 0),
        "views": analytics.get("views", 0),
        "engagement_rate": _as_percent_engagement_rate(raw_er),
        "published_at": publish.get("published_at", wf_state.get("updated_at", "")),
        "dry_run": is_dry_run,
    }


def _build_growth_report(
    account_id: str,
    period: str,
    filtered_posts: list[dict[str, Any]],
    topics: dict[str, int],
) -> dict[str, Any]:
    """Shared report payload for /report and /dashboard."""
    total_engagement = sum(p["likes"] + p["comments"] + p["collects"] for p in filtered_posts)
    avg_rate = (
        sum(p["engagement_rate"] for p in filtered_posts) / len(filtered_posts)
        if filtered_posts
        else 0.0
    )
    best = max(filtered_posts, key=lambda p: p["likes"] + p["comments"], default=None)
    trend_topics = sorted(topics, key=lambda k: topics[k], reverse=True)[:5]

    insights: list[dict[str, str]] = []
    if avg_rate > 4.0:
        insights.append({"type": "trend", "message": "互动率表现优秀，继续保持当前内容策略"})
    elif filtered_posts:
        insights.append({"type": "opportunity", "message": "互动率有提升空间，建议优化标题和封面"})
    if trend_topics:
        insights.append({"type": "trend", "message": f"热门话题：{'、'.join(trend_topics[:3])}"})
    if not filtered_posts:
        insights.append(
            {
                "type": "info",
                "message": "暂无表现数据：请完成工作流发布或同步创作者中心统计",
            }
        )
    elif any(p.get("source") in ("creator_statistics", "fixture") for p in filtered_posts):
        insights.append(
            {
                "type": "trend",
                "message": "已纳入创作者中心导入笔记表现，可用于风格沉淀与选题建议",
            }
        )

    return {
        "account_id": account_id,
        "period": period,
        "metrics": {
            "total_posts": len(filtered_posts),
            "total_engagement": total_engagement,
            "avg_engagement_rate": round(avg_rate, 1),
            "best_post_title": best["title"] if best else "",
            "trend_topics": trend_topics,
        },
        "insights": insights,
        "generated_at": datetime.now().isoformat(),
    }


def _link_stats(posts: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize explicit workflow/import identity resolution safely."""

    workflow_rows = [post for post in posts if post.get("source") == "workflow"]
    linked = sum(1 for post in workflow_rows if post.get("link_status") == "linked")
    return {
        "workflow_count": len(workflow_rows),
        "linked_count": linked,
        "link_rate": round(linked / len(workflow_rows), 4) if workflow_rows else None,
    }


@router.get("/report/{account_id}")
async def get_growth_report(
    account_id: str,
    period: str = "weekly",
    request: Request = None,  # type: ignore[assignment]
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """获取增长报告 — workflows + imported creator-center notes."""
    assert request is not None
    account_id = (account_id or "").strip()
    await require_owned_account(str(user["id"]), account_id)
    graph = request.app.state.graph
    workflows = await _get_completed_workflows(graph, account_id)

    posts: list[dict[str, Any]] = []
    topics: dict[str, int] = {}
    for wf in workflows:
        state = wf.get("_state", {})
        post = _extract_post_data(state, account_id)
        if post:
            posts.append(post)
        plan = state.get("content_plan") or {}
        topic = plan.get("selected_topic")
        if topic:
            topics[topic] = topics.get(topic, 0) + 1

    snapshot_bundle = await _creator_snapshot_bundle(account_id)
    posts = await _merge_imported_posts(
        account_id,
        posts,
        limit=100,
        imported_notes=snapshot_bundle.get("notes", []),
    )
    for t, c in _topics_from_imported(posts).items():
        topics[t] = topics.get(t, 0) + c
    account_obj = snapshot_bundle.get("account")
    detail_metrics: dict[str, Any] = {}
    if account_obj is not None:
        raw_dm = getattr(account_obj, "detail_metrics", None)
        if isinstance(raw_dm, dict):
            detail_metrics = raw_dm
        elif isinstance(account_obj, dict) and isinstance(account_obj.get("detail_metrics"), dict):
            detail_metrics = account_obj["detail_metrics"]
    filtered_posts = _filter_by_period(posts, period)
    report = _build_growth_report(account_id, period, filtered_posts, topics)
    period_summary = _build_period_summary(posts, period, detail_metrics=detail_metrics or None)
    current_metrics = period_summary.get("current") or {}
    if current_metrics.get("metric_source") == "creator_center_series":
        metrics = report.setdefault("metrics", {})
        metrics["total_engagement"] = int(current_metrics.get("engagement") or 0)
        metrics["avg_engagement_rate"] = float(current_metrics.get("avg_engagement_rate") or 0.0)
        metrics["total_views"] = int(current_metrics.get("views") or 0)
    snapshot = _complete_snapshot_metadata(
        account_id,
        snapshot_bundle,
        workflows,
    )
    report.update(
        {
            "scope": "account_history",
            "subject_type": "imported_note",
            "assessment_type": "historical_performance",
            "status": "ready" if filtered_posts else "unavailable",
            "data_as_of": snapshot["data_as_of"],
            "snapshot_id": snapshot["snapshot_id"],
            "contract_version": QUALITY_CONSISTENCY_CONTRACT
            if quality_consistency_v2_enabled()
            else "legacy_compatible",
            "link_stats": _link_stats(posts),
        }
    )
    _serialize_analytics_rate_units(report=report)
    return success(data=report)


def _imported_notes_as_posts(notes: list[Any]) -> list[dict[str, Any]]:
    """Map persisted creator-center NoteStats into the performance table shape."""
    posts: list[dict[str, Any]] = []
    for n in notes:
        # Accept dataclass or plain dict
        if hasattr(n, "to_dict"):
            d = n.to_dict()
        elif isinstance(n, dict):
            d = n
        else:
            continue
        posts.append(
            {
                "id": d.get("note_id", ""),
                "platform_post_id": _normalize_platform_post_id(d.get("note_id", "")),
                "workflow_thread_id": "",
                "link_status": "unmatched",
                "account_id": d.get("account_id", ""),
                "title": d.get("title", ""),
                "likes": int(d.get("likes") or 0),
                "comments": int(d.get("comments") or 0),
                "collects": int(d.get("collects") or 0),
                "shares": int(d.get("shares") or 0),
                "views": int(d.get("views") or 0),
                "engagement_rate": _as_percent_engagement_rate(d.get("engagement_rate")),
                "published_at": d.get("published_at", ""),
                "synced_at": d.get("synced_at", ""),
                "dry_run": False,
                "source": d.get("source") or "creator_statistics",
                "subject_type": "imported_note",
                "subject_id": d.get("note_id", ""),
                "scope": "account_history",
                "assessment_type": "historical_performance",
                "status": "ready",
                "algorithm_version": "historical_quality.v1",
                "data_as_of": d.get("synced_at") or None,
                "note_synced_at": d.get("synced_at") or None,
            }
        )
    return posts


async def _merge_imported_posts(
    account_id: str,
    posts: list[dict[str, Any]],
    *,
    limit: int = 100,
    imported_notes: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Merge imported notes using explicit platform identity only.

    Missing/synthetic workflow ids never collapse an imported note.  A single
    matching workflow is marked ``linked``; duplicate workflow claims are
    surfaced as ``ambiguous`` and remain separate.
    """
    if imported_notes is None:
        try:
            from backend.db import creator_stats as stats_db

            # Reports and period aggregates need the complete durable
            # snapshot; ``limit`` remains only for compatibility with older
            # callers.  Route callers can inject a bundle-owned list so the
            # response snapshot cannot be read from a later import.
            imported = await stats_db.list_all_note_stats(account_id)
        except Exception:
            return posts
    else:
        imported = imported_notes

    by_platform_id: dict[str, list[dict[str, Any]]] = {}
    for post in posts:
        # Workflow rows must opt in with an explicit platform id.  Falling
        # back to ``id`` would turn the synthetic ``workflow:<thread>``
        # display key into a false Creator Center link.
        platform_id = _normalize_platform_post_id(post.get("platform_post_id"))
        if platform_id:
            by_platform_id.setdefault(platform_id, []).append(post)

    imported_posts = _imported_notes_as_posts(imported)
    imported_by_platform: dict[str, list[dict[str, Any]]] = {}
    unmatched_imported: list[dict[str, Any]] = []
    for ip in imported_posts:
        platform_id = _normalize_platform_post_id(ip.get("platform_post_id") or ip.get("id"))
        if platform_id:
            imported_by_platform.setdefault(platform_id, []).append(ip)
        else:
            unmatched_imported.append(ip)

    # Resolve each normalized platform identity as a group.  Grouping the
    # imported side as well as the workflow side prevents URL-vs-id variants
    # from silently dropping a second Creator Center claim.
    for platform_id, candidates in imported_by_platform.items():
        matches = by_platform_id.get(platform_id, [])
        if len(matches) == 1 and len(candidates) == 1:
            workflow = matches[0]
            imported_note = candidates[0]
            # Creator Center is the authoritative post-publication fact
            # source.  Keep workflow identity/title metadata, but replace the
            # live checkpoint's potentially stale metrics with the imported
            # snapshot so reports and the canonical history reader cannot
            # disagree for a linked note.
            for key in (
                "title",
                "likes",
                "comments",
                "collects",
                "shares",
                "views",
                "engagement_rate",
                "published_at",
            ):
                if imported_note.get(key) is not None:
                    workflow[key] = imported_note.get(key)
            workflow["link_status"] = "linked"
            workflow["linked_note_id"] = imported_note.get("id")
            workflow["note_synced_at"] = imported_note.get("synced_at")
            workflow.update(
                {
                    "subject_type": "imported_note",
                    "subject_id": imported_note.get("id"),
                    "scope": "account_history",
                    "assessment_type": "historical_performance",
                    "status": "ready",
                    "algorithm_version": "historical_quality.v1",
                    "data_as_of": imported_note.get("synced_at") or None,
                }
            )
            imported_note["link_status"] = "linked"
            imported_note["workflow_thread_id"] = workflow.get("workflow_thread_id", "")
            continue

        # Zero/one/many workflows combined with multiple imported claims are
        # all explicit ambiguity or unmatched states; never collapse rows.
        if len(matches) > 1 or len(candidates) > 1:
            for workflow in matches:
                workflow["link_status"] = "ambiguous"
            for imported_note in candidates:
                imported_note["link_status"] = "ambiguous"
                if len(matches) == 1:
                    imported_note["workflow_thread_id"] = matches[0].get("workflow_thread_id", "")
        posts.extend(candidates)

    posts.extend(unmatched_imported)
    return posts


def _topics_from_imported(posts: list[dict[str, Any]]) -> dict[str, int]:
    """Lightweight topic counts from imported post titles (fallback when no plan)."""
    topics: dict[str, int] = {}
    for p in posts:
        if p.get("source") not in ("creator_statistics", "fixture"):
            continue
        title = (p.get("title") or "").strip()
        if title:
            # Use full title as a soft topic key (UI only needs a short list)
            topics[title] = topics.get(title, 0) + 1
    return topics


@router.get("/performance/{account_id}")
async def get_performance(
    account_id: str,
    period: str = "weekly",
    limit: int = Query(20, ge=1, le=100),
    request: Request = None,  # type: ignore[assignment]
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """获取最近帖子表现 — workflow publish analytics + imported creator-center notes."""
    assert request is not None
    account_id = (account_id or "").strip()
    await require_owned_account(str(user["id"]), account_id)
    graph = request.app.state.graph
    workflows = await _get_completed_workflows(graph, account_id)

    posts: list[dict[str, Any]] = []
    for wf in workflows:
        state = wf.get("_state", {})
        post = _extract_post_data(state, account_id)
        if post:
            posts.append(post)

    snapshot_bundle = await _creator_snapshot_bundle(account_id)
    posts = await _merge_imported_posts(
        account_id,
        posts,
        limit=max(limit, 50),
        imported_notes=snapshot_bundle.get("notes", []),
    )
    posts = _filter_by_period(posts, period)
    posts.sort(key=lambda p: p.get("published_at", ""), reverse=True)
    link_stats = _link_stats(posts)
    total = len(posts)
    posts = posts[:limit]
    _serialize_analytics_rate_units(posts=posts)

    snapshot = _complete_snapshot_metadata(
        account_id,
        snapshot_bundle,
        workflows,
    )
    for post in posts:
        post["snapshot_id"] = snapshot["snapshot_id"]
    return success(
        data={
            "account_id": account_id,
            "period": period,
            "posts": posts,
            "total": total,
            "fetched_at": datetime.now().isoformat(),
            "scope": "account_history",
            "subject_type": "imported_note",
            "assessment_type": "historical_performance",
            "status": "ready" if posts else "unavailable",
            "data_as_of": snapshot["data_as_of"],
            "snapshot_id": snapshot["snapshot_id"],
            "contract_version": QUALITY_CONSISTENCY_CONTRACT
            if quality_consistency_v2_enabled()
            else "legacy_compatible",
            "engagement_rate_unit": "fraction",
            "link_stats": link_stats,
        }
    )


@router.get("/costs")
async def get_costs(
    period: str = "weekly",
    request: Request = None,  # type: ignore[assignment]
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """获取 LLM 调用成本 — aggregated from workflow performance logs."""
    assert request is not None
    graph = request.app.state.graph
    workflows = await _get_completed_workflows(graph)

    now = datetime.now(UTC)
    cutoff_hours = _period_cutoff_hours(period)
    cutoff_time = now.timestamp() - cutoff_hours * 3600

    by_model: dict[str, float] = {}
    total_cost = 0.0
    period_cost = 0.0
    today_cost = 0.0
    today = now.date()

    for wf in workflows:
        state = wf.get("_state", {})
        perf_log = state.get("performance_log") or []
        for entry in perf_log:
            # ponytail: skip node/human_wait entries (no cost_usd); llm/ripple
            # and back-compat entries (no kind) carry cost.
            if entry.get("kind") in ("node", "human_wait"):
                continue
            cost = entry.get("cost_usd", 0.0)
            model = entry.get("model", "unknown")
            total_cost += cost
            by_model[model] = by_model.get(model, 0.0) + cost

            # Check if entry is within period
            try:
                ts = entry.get("timestamp", "")
                if ts:
                    entry_dt = datetime.fromisoformat(ts)
                    if entry_dt.tzinfo is None:
                        entry_dt = entry_dt.replace(tzinfo=UTC)
                    entry_date = entry_dt.date()
                    if entry_date == today:
                        today_cost += cost
                    if entry_dt.timestamp() >= cutoff_time:
                        period_cost += cost
            except (ValueError, AttributeError):
                pass

    return success(
        data={
            "total_cost_usd": round(total_cost, 2),
            "period_cost_usd": round(period_cost, 2),
            "today_cost_usd": round(today_cost, 2),
            "period": period,
            "by_model": {k: round(v, 2) for k, v in by_model.items()},
            "circuit_open": False,
            "budget_remaining_usd": round(max(0, 10.0 - total_cost), 2),
            "updated_at": datetime.now().isoformat(),
        }
    )


@router.get("/dashboard/{account_id}")
async def get_dashboard(
    account_id: str,
    period: str = "weekly",
    limit: int = Query(20, ge=1, le=100),
    request: Request = None,  # type: ignore[assignment]
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Single-request analytics bundle — report + performance + costs.

    Avoids 3× the cold-start cost of _get_completed_workflows by computing
    all three payloads from one fetch. Includes imported creator-center notes
    (frontend Analytics uses this path exclusively).
    """
    assert request is not None
    account_id = (account_id or "").strip()
    await require_owned_account(str(user["id"]), account_id)
    graph = request.app.state.graph
    workflows = await _get_completed_workflows(graph, account_id)

    # ── Extract posts once ──
    posts: list[dict[str, Any]] = []
    topics: dict[str, int] = {}
    for wf in workflows:
        state = wf.get("_state", {})
        post = _extract_post_data(state, account_id)
        if post:
            posts.append(post)
        plan = state.get("content_plan") or {}
        topic = plan.get("selected_topic")
        if topic:
            topics[topic] = topics.get(topic, 0) + 1

    # Merge the full imported snapshot before computing period aggregates. The
    # visible table remains paginated below, but current/previous totals must
    # not depend on its ``limit``.
    snapshot_bundle = await _creator_snapshot_bundle(account_id)
    posts = await _merge_imported_posts(
        account_id,
        posts,
        limit=500,
        imported_notes=snapshot_bundle.get("notes", []),
    )
    for t, c in _topics_from_imported(posts).items():
        topics[t] = topics.get(t, 0) + c

    account_obj = snapshot_bundle.get("account")
    detail_metrics: dict[str, Any] = {}
    if account_obj is not None:
        raw_dm = getattr(account_obj, "detail_metrics", None)
        if isinstance(raw_dm, dict):
            detail_metrics = raw_dm
        elif isinstance(account_obj, dict) and isinstance(account_obj.get("detail_metrics"), dict):
            detail_metrics = account_obj["detail_metrics"]

    period_summary = _build_period_summary(posts, period, detail_metrics=detail_metrics or None)
    filtered_posts = _filter_by_period(posts, period)
    report = _build_growth_report(account_id, period, filtered_posts, topics)
    # Align report engagement totals with Creator Center series when available
    # so the first-screen cards and report block cannot disagree.
    current_metrics = period_summary.get("current") or {}
    if current_metrics.get("metric_source") == "creator_center_series":
        metrics = report.setdefault("metrics", {})
        metrics["total_engagement"] = int(current_metrics.get("engagement") or 0)
        metrics["avg_engagement_rate"] = float(current_metrics.get("avg_engagement_rate") or 0.0)
        metrics["total_views"] = int(current_metrics.get("views") or 0)

    # ── Performance ──
    sorted_posts = sorted(filtered_posts, key=lambda p: p.get("published_at", ""), reverse=True)[
        :limit
    ]
    performance = {
        "account_id": account_id,
        "period": period,
        "posts": sorted_posts,
        "total": len(filtered_posts),
        "fetched_at": datetime.now().isoformat(),
    }

    # ── Costs ──
    now = datetime.now(UTC)
    cutoff_hours = _period_cutoff_hours(period)
    cutoff_time = now.timestamp() - cutoff_hours * 3600
    by_model: dict[str, float] = {}
    total_cost = 0.0
    period_cost = 0.0
    today_cost = 0.0
    today = now.date()

    for wf in workflows:
        state = wf.get("_state", {})
        perf_log = state.get("performance_log") or []
        for entry in perf_log:
            # ponytail: skip node/human_wait entries (no cost_usd); llm/ripple
            # and back-compat entries (no kind) carry cost.
            if entry.get("kind") in ("node", "human_wait"):
                continue
            cost = entry.get("cost_usd", 0.0)
            model = entry.get("model", "unknown")
            total_cost += cost
            by_model[model] = by_model.get(model, 0.0) + cost
            try:
                ts = entry.get("timestamp", "")
                if ts:
                    entry_dt = datetime.fromisoformat(ts)
                    if entry_dt.tzinfo is None:
                        entry_dt = entry_dt.replace(tzinfo=UTC)
                    if entry_dt.date() == today:
                        today_cost += cost
                    if entry_dt.timestamp() >= cutoff_time:
                        period_cost += cost
            except (ValueError, AttributeError):
                pass

    costs = {
        "total_cost_usd": round(total_cost, 2),
        "period_cost_usd": round(period_cost, 2),
        "today_cost_usd": round(today_cost, 2),
        "period": period,
        "by_model": {k: round(v, 2) for k, v in by_model.items()},
        "circuit_open": False,
        "budget_remaining_usd": round(max(0, 10.0 - total_cost), 2),
        "updated_at": datetime.now().isoformat(),
    }

    snapshot = _complete_snapshot_metadata(
        account_id,
        snapshot_bundle,
        workflows,
    )
    contract_version = (
        QUALITY_CONSISTENCY_CONTRACT if quality_consistency_v2_enabled() else "legacy_compatible"
    )
    _serialize_analytics_rate_units(
        posts=sorted_posts,
        report=report,
        period_summary=period_summary,
    )
    for post in sorted_posts:
        post["snapshot_id"] = snapshot["snapshot_id"]
    report.update(
        {
            "scope": "account_history",
            "subject_type": "imported_note",
            "assessment_type": "historical_performance",
            "status": "ready" if filtered_posts else "unavailable",
            "data_as_of": snapshot["data_as_of"],
            "snapshot_id": snapshot["snapshot_id"],
            "contract_version": contract_version,
            "engagement_rate_unit": "fraction",
            "link_stats": _link_stats(posts),
        }
    )
    performance.update(
        {
            "data_as_of": snapshot["data_as_of"],
            "snapshot_id": snapshot["snapshot_id"],
            "scope": "account_history",
            "subject_type": "imported_note",
            "assessment_type": "historical_performance",
            "status": "ready" if filtered_posts else "unavailable",
            "contract_version": contract_version,
            "engagement_rate_unit": "fraction",
            "link_stats": _link_stats(posts),
        }
    )
    period_summary.update(
        {
            "data_as_of": snapshot["data_as_of"],
            "snapshot_id": snapshot["snapshot_id"],
        }
    )

    return success(
        data={
            "report": report,
            "performance": performance,
            "costs": costs,
            # Server-owned aggregate contract for period-over-period cards.
            "period_summary": period_summary,
            "account_id": account_id,
            "data_as_of": snapshot["data_as_of"],
            "snapshot_id": snapshot["snapshot_id"],
            "engagement_rate_unit": "fraction",
            "contract_version": contract_version,
        }
    )


# ── Creator-center stats import + creative suggestions ──────────────────────


@router.post("/creator-stats/sync")
async def sync_creator_stats(
    body: CreatorStatsSyncRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """从创作者中心统计页导入账户/笔记数据，并沉淀创作风格。

    产品路径只使用账号绑定且已登录的 CDP Chrome，写入真实 Creator Center
    响应。旧版 ``dry_run`` 与 ``cookie`` 字段仅为请求兼容性保留，二者
    都不会改变 HTTP 路由的浏览器唯一导入契约；fixture 仅可由内部
    service/CLI 测试路径使用。
    """
    from backend.db.accounts import get_account_cdp_endpoint
    from backend.services.creator_stats.pipeline import sync_account_stats
    from backend.services.creator_stats.types import SyncResult

    account_id = await resolve_required_account_id(str(user["id"]), body.account_id)
    body.account_id = account_id

    graph = getattr(request.app.state, "graph", None)
    store = getattr(graph, "store", None) if graph is not None else None

    # 产品同步必须连接账号自己的常驻、已登录 Chrome。不要根据旧版
    # dry_run/cookie 字段改变该路径，否则调用者可意外写入 fixture 数据。
    cdp_endpoint = ""
    try:
        cdp_endpoint = (await get_account_cdp_endpoint(body.account_id)).strip()
    except Exception:
        cdp_endpoint = ""

    if not cdp_endpoint:
        # Do not substitute fixture or a caller-provided cookie under a real
        # account id. Existing durable imports remain untouched on this path.
        from backend.services.creator_stats.types import ERROR_BROWSER_UNAVAILABLE

        result = SyncResult(
            account_id=body.account_id,
            source="creator_statistics",
            error="未检测到该账号可用的浏览器会话。请先启动并登录绑定账号的 Chrome 后重试。",
            error_code=ERROR_BROWSER_UNAVAILABLE,
        )
    else:
        result = await sync_account_stats(
            body.account_id,
            cookie="",
            dry_run=False,
            store=store,
            period=body.period,
            run_creative_analysis=body.analyze,
            cdp_endpoint=cdp_endpoint,
        )
    data = result.to_dict()
    # Primary observables for clients/tests (not merely HTTP 200).
    # Import can succeed while analysis fails — still "ok" for the import path.
    import_ok = bool(result.account_synced) and (
        result.error is None or str(result.error).startswith("import succeeded")
    )
    data["ok"] = import_ok and (
        result.error is None or str(result.error).startswith("import succeeded")
    )
    # Live auth/network failures leave account_synced False → ok False
    if result.error and not result.account_synced:
        data["ok"] = False
    data["analyzed"] = result.analysis is not None
    data["import_ok"] = bool(result.account_synced)
    data["error_code"] = result.error_code
    return success(data=data)


@router.post("/creator-stats/sync-all")
async def sync_all_creator_stats(
    body: CreatorStatsSyncAllRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """仅导入当前激活账号；切换激活账号后，之前的账号不再同步。"""
    from backend.services.creator_stats.pipeline import sync_all_active_accounts

    graph = getattr(request.app.state, "graph", None)
    store = getattr(graph, "store", None) if graph is not None else None
    # Manual sync may deep-enrich (prefer_light=False); scheduled jobs force light.
    data = await sync_all_active_accounts(
        store=store,
        period=body.period,
        run_creative_analysis=body.analyze,
        prefer_light=False,
        skip_freshness_check=True,
    )
    return success(data=data)


@router.get("/creator-stats/{account_id}")
async def get_creator_stats(
    account_id: str,
    limit: int = Query(50, ge=1, le=200),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """读取本地已导入的创作者中心账户/笔记统计。"""
    from backend.db import creator_stats as stats_db
    from backend.services.creator_stats.audience import summarize_audience

    account_id = (account_id or "").strip()
    await require_owned_account(str(user["id"]), account_id)
    snapshot = await _creator_snapshot_bundle(account_id)
    account = snapshot.get("account")
    all_notes = list(snapshot.get("notes", []))
    all_notes.sort(
        key=lambda note: (
            float(getattr(note, "engagement_rate", 0.0) or 0.0),
            int(getattr(note, "views", 0) or 0),
        ),
        reverse=True,
    )
    notes = all_notes[:limit]
    canonical_notes = [stats_db.canonicalize_note_stats(note) for note in notes]
    note_rows = []
    for note in canonical_notes:
        row = note.to_dict()
        row.update(
            {
                "subject_type": "imported_note",
                "subject_id": note.note_id,
                "scope": "account_history",
                "assessment_type": "historical_performance",
                "status": "ready",
                "algorithm_version": "historical_quality.v1",
                "data_as_of": note.synced_at or None,
                "note_synced_at": note.synced_at or None,
            }
        )
        note_rows.append(row)
    # total = full count (not page size); note_count on account is a fallback
    total = len(all_notes)
    if total == 0 and account is not None:
        total = int(getattr(account, "note_count", 0) or 0)
    data_as_of = snapshot["data_as_of"]
    for row in note_rows:
        row["snapshot_id"] = snapshot["snapshot_id"]
    return success(
        data={
            "account_id": account_id,
            "account": account.to_dict() if account else None,
            "notes": note_rows,
            "audience_analysis": summarize_audience(account, canonical_notes),
            "total": total,
            "limit": limit,
            "data_as_of": data_as_of,
            "snapshot_id": snapshot["snapshot_id"],
            "scope": "account_history",
            "subject_type": "imported_note",
            "assessment_type": "historical_performance",
            "algorithm_version": "historical_quality.v1",
            "status": "ready" if canonical_notes or account else "unavailable",
            "engagement_rate_unit": "fraction",
            "contract_version": QUALITY_CONSISTENCY_CONTRACT
            if quality_consistency_v2_enabled()
            else "legacy_compatible",
            "fetched_at": datetime.now(UTC).isoformat(),
        }
    )


@router.get("/creator-stats/{account_id}/notes")
async def get_creator_stats_notes(
    account_id: str,
    cursor: str | None = Query(None, description="历史笔记游标"),
    limit: int = Query(50, ge=1, le=500, description="每页数量"),
    sort: str = Query("published_at_desc", description="稳定排序：published_at_desc"),
    published_from: str | None = Query(None, description="发布时间起始（ISO-8601）"),
    published_to: str | None = Query(None, description="发布时间结束（ISO-8601）"),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Canonical historical-note fact reader shared by Analytics/Evaluation.

    The older ``GET /creator-stats/{account_id}`` remains a bounded overview
    preview.  This route owns the complete filtered ``total`` and cursor
    contract so callers do not need to coordinate different 100/200/500 caps.
    """
    from backend.db import creator_stats as stats_db

    normalized_account_id = (account_id or "").strip()
    if not normalized_account_id:
        raise ValidationError("account_id", "account_id cannot be empty")
    await require_owned_account(str(user["id"]), normalized_account_id)
    if sort != "published_at_desc":
        raise ValidationError("sort", "sort must be published_at_desc")
    try:
        page = await stats_db.list_note_stats_page(
            normalized_account_id,
            cursor=cursor,
            limit=limit,
            published_from=published_from,
            published_to=published_to,
        )
    except ValueError as exc:
        raise ValidationError("cursor", str(exc)) from exc
    payload = page.to_dict()
    if not quality_consistency_v2_enabled():
        payload["contract_version"] = "legacy_compatible"
        for item in payload.get("items", []):
            if isinstance(item, dict):
                item["contract_version"] = "legacy_compatible"
    return success(data=payload)


async def _get_imported_creator_note_with_snapshot(
    account_id: str, note_id: str
) -> tuple[str, Any, dict[str, Any]]:
    """Load a note and its account snapshot from the same read bundle."""

    normalized_account_id = (account_id or "").strip()
    normalized_note_id = (note_id or "").strip()
    if not normalized_account_id:
        raise ValidationError("account_id", "account_id cannot be empty")
    if not normalized_note_id:
        raise ValidationError("note_id", "note_id cannot be empty")
    from backend.db import creator_stats as stats_db

    snapshot = await _creator_snapshot_bundle(normalized_account_id)
    note = next(
        (
            item
            for item in snapshot.get("notes", [])
            if str(getattr(item, "note_id", "") or "").strip() == normalized_note_id
        ),
        None,
    )
    if note is None:
        raise CreatorNoteNotFoundError(normalized_account_id, normalized_note_id)
    return normalized_account_id, stats_db.canonicalize_note_stats(note), snapshot


@router.get("/creator-stats/{account_id}/notes/{note_id}")
async def get_creator_note_detail(
    account_id: str,
    note_id: str,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Read one imported Creator Center note without starting a sync."""
    await require_owned_account(str(user["id"]), account_id)
    normalized_account_id, note, snapshot_metadata = await _get_imported_creator_note_with_snapshot(
        account_id, note_id
    )
    return success(
        data={
            "account_id": normalized_account_id,
            "note": note.to_dict(),
            "scope": "single_note",
            "assessment_type": "historical_performance",
            "data_as_of": snapshot_metadata["data_as_of"] or note.synced_at or None,
            "note_synced_at": note.synced_at or None,
            "snapshot_id": snapshot_metadata["snapshot_id"],
            "contract_version": QUALITY_CONSISTENCY_CONTRACT
            if quality_consistency_v2_enabled()
            else "legacy_compatible",
            "fetched_at": datetime.now(UTC).isoformat(),
        }
    )


@router.get("/creator-stats/{account_id}/notes/{note_id}/quality")
async def get_creator_note_quality(
    account_id: str,
    note_id: str,
    locale: str = Query("zh-CN", max_length=16, description="报告文案语言：zh-CN | en"),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Evaluate one imported note with the historical quality analyzer."""
    from backend.services.creator_stats.quality import analyze_note_quality

    await require_owned_account(str(user["id"]), account_id)

    normalized_account_id, note, snapshot_metadata = await _get_imported_creator_note_with_snapshot(
        account_id, note_id
    )
    report = analyze_note_quality(note, normalized_account_id, locale=locale)
    report_data = report.to_dict()
    report_data.update(
        {
            "assessment_type": "historical_performance",
            "algorithm_version": "historical_quality.v1",
            "scope": "single_note",
            "status": "ready" if report.overall_score is not None else "unavailable",
            "data_as_of": snapshot_metadata["data_as_of"] or note.synced_at or None,
            "note_synced_at": note.synced_at or None,
            "snapshot_id": snapshot_metadata["snapshot_id"],
            "contract_version": QUALITY_CONSISTENCY_CONTRACT
            if quality_consistency_v2_enabled()
            else "legacy_compatible",
            "coverage": {
                "available": [item.key for item in report.dimensions if item.available],
                "unavailable": [item.key for item in report.dimensions if not item.available],
                "weighted_ratio": round(
                    sum(1 for item in report.dimensions if item.available) / len(report.dimensions),
                    4,
                )
                if report.dimensions
                else 0.0,
            },
        }
    )
    return success(
        data={
            "account_id": normalized_account_id,
            "note_id": note.note_id,
            "subject_type": "imported_note",
            "subject_id": note.note_id,
            "scope": "single_note",
            "assessment_type": "historical_performance",
            "status": report_data["status"],
            "data_as_of": snapshot_metadata["data_as_of"] or note.synced_at or None,
            "snapshot_id": snapshot_metadata["snapshot_id"],
            "contract_version": QUALITY_CONSISTENCY_CONTRACT
            if quality_consistency_v2_enabled()
            else "legacy_compatible",
            "quality": report_data,
            "analyzed_at": datetime.now(UTC).isoformat(),
        }
    )


@router.get("/creator-stats/{account_id}/quality")
async def get_creator_quality(
    account_id: str,
    locale: str = Query("zh-CN", max_length=16, description="报告文案语言：zh-CN | en"),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Return a read-only quality report over every imported note for an account."""
    from backend.services.creator_stats.quality import analyze_historical_quality

    normalized_account_id = await resolve_required_account_id(str(user["id"]), account_id)
    await require_owned_account(str(user["id"]), normalized_account_id)
    # Do not use list_note_stats here: that reader is intentionally capped for
    # interactive display.  Historical quality must analyze the same complete
    # durable note bundle that supplies its snapshot metadata; it must not
    # calculate from one import and label the response with a later one.
    snapshot = await _creator_snapshot_bundle(normalized_account_id)
    notes = snapshot.get("notes", [])
    report = analyze_historical_quality(notes, normalized_account_id, locale=locale)
    data_as_of = snapshot["data_as_of"]
    data = report.to_dict()
    data.update(
        {
            "assessment_type": "historical_performance",
            "algorithm_version": "historical_quality.v1",
            "scope": "account_history",
            "subject_type": "imported_note",
            "subject_id": normalized_account_id,
            "status": "ready" if report.overall_score is not None else "unavailable",
            "data_as_of": data_as_of,
            "snapshot_id": snapshot["snapshot_id"],
            "contract_version": QUALITY_CONSISTENCY_CONTRACT
            if quality_consistency_v2_enabled()
            else "legacy_compatible",
            "coverage": {
                "available": [item.key for item in report.dimensions if item.available],
                "unavailable": [item.key for item in report.dimensions if not item.available],
                "weighted_ratio": round(
                    sum(1 for item in report.dimensions if item.available) / len(report.dimensions),
                    4,
                )
                if report.dimensions
                else 0.0,
            },
        }
    )
    return success(data=data)


@router.get("/creator-stats/{account_id}/suggestions")
async def get_creator_suggestions(
    account_id: str,
    mode: str = Query(
        "trend",
        description="创作模式：trend | brief | free（大小写不敏感）",
    ),
    request: Request = None,  # type: ignore[assignment]
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """按创作模式返回账户级创作建议（共享召回面）。"""
    from backend.services.creator_stats.suggestions import (
        _normalize_mode,
        get_suggestions_for_mode,
    )

    assert request is not None
    account_id = (account_id or "").strip()
    await require_owned_account(str(user["id"]), account_id)
    graph = getattr(request.app.state, "graph", None)
    store = getattr(graph, "store", None) if graph is not None else None
    mode_norm = _normalize_mode(mode)
    suggestions = await get_suggestions_for_mode(account_id, mode_norm, store=store)
    return success(
        data={
            "account_id": account_id,
            "mode": mode_norm,
            "suggestions": [s.to_dict() for s in suggestions],
            "count": len(suggestions),
            "cold_start": all(s.category == "cold_start" for s in suggestions)
            if suggestions
            else True,
        }
    )


@router.get("/creator-stats/{account_id}/analysis")
async def get_creator_analysis(
    account_id: str,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """对已导入笔记即时跑创作分析（不强制重新拉取远端）。"""
    from backend.db import creator_stats as stats_db
    from backend.services.creator_stats.analyze import analyze_notes
    from backend.services.creator_stats.audience import summarize_audience
    from backend.services.creator_stats.suggestions import suggestions_from_analysis

    account_id = (account_id or "").strip()
    await require_owned_account(str(user["id"]), account_id)
    notes = await stats_db.list_note_stats(account_id, limit=100)
    account = await stats_db.get_account_stats(account_id)
    analysis = analyze_notes(notes, account_id)
    suggestions = suggestions_from_analysis(analysis, notes)
    return success(
        data={
            "analysis": analysis.to_dict(),
            "suggestions": {m: [s.to_dict() for s in items] for m, items in suggestions.items()},
            "audience_analysis": summarize_audience(account, notes),
        }
    )
