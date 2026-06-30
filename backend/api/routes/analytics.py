"""Analytics API routes — growth reports and performance data from real workflows."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter, Query, Request

from backend.api.responses import ApiResponse, success
from backend.db.pool import is_pool_ready
from backend.db.workflows import list_workflows as db_list

router = APIRouter()

# Simple in-memory cache with TTL
_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 30  # seconds


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
    """Read full state for completed workflows, with caching."""
    cache_key = f"completed_{account_id or 'all'}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cast(list[dict[str, Any]], cached)

    results: list[dict[str, Any]] = []
    if is_pool_ready():
        # Include completed and analyzing workflows (both have publish_result)
        for status_filter in ("completed", "analyzing"):
            rows, _ = await db_list(status=status_filter, limit=100)
            for row in rows:
                if account_id and row.account_id != account_id:
                    continue
                try:
                    config = {"configurable": {"thread_id": row.thread_id}}
                    state = await graph.aget_state(config)
                    if state.values:
                        results.append({**row.to_dict(), "_state": state.values})
                except Exception:
                    continue

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


def _filter_by_period(posts: list[dict[str, Any]], period: str) -> list[dict[str, Any]]:
    """Filter posts by time period."""
    now = datetime.now(UTC)
    cutoff_hours = _period_cutoff_hours(period)
    filtered = []
    for p in posts:
        try:
            pub = datetime.fromisoformat(p["published_at"].replace(" ", "T"))
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=UTC)
            if (now - pub).total_seconds() / 3600 <= cutoff_hours:
                filtered.append(p)
        except (ValueError, AttributeError):
            filtered.append(p)
    return filtered


def _extract_post_data(wf_state: dict[str, Any]) -> dict[str, Any] | None:
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

    return {
        "id": publish.get("post_id", wf_state.get("session_id", "")),
        "title": title,
        "likes": analytics.get("likes", 0),
        "comments": analytics.get("comments", 0),
        "collects": analytics.get("collects", 0),
        "shares": analytics.get("shares", 0),
        "views": analytics.get("views", 0),
        "engagement_rate": round(analytics.get("engagement_rate", 0.0), 2),
        "published_at": publish.get("published_at", wf_state.get("updated_at", "")),
        "dry_run": is_dry_run,
    }


@router.get("/report/{account_id}")
async def get_growth_report(
    account_id: str, period: str = "weekly", request: Request = None  # type: ignore[assignment]
) -> ApiResponse[Any]:
    """获取增长报告 — from real completed workflows."""
    assert request is not None
    graph = request.app.state.graph
    workflows = await _get_completed_workflows(graph, account_id)

    posts = []
    topics: dict[str, int] = {}
    for wf in workflows:
        state = wf.get("_state", {})
        post = _extract_post_data(state)
        if post:
            posts.append(post)
        plan = state.get("content_plan") or {}
        topic = plan.get("selected_topic")
        if topic:
            topics[topic] = topics.get(topic, 0) + 1

    # Filter by period
    filtered_posts = _filter_by_period(posts, period)

    total_engagement = sum(p["likes"] + p["comments"] + p["collects"] for p in filtered_posts)
    avg_rate = (
        sum(p["engagement_rate"] for p in filtered_posts) / len(filtered_posts)
        if filtered_posts
        else 0.0
    )
    best = max(filtered_posts, key=lambda p: p["likes"] + p["comments"], default=None)
    trend_topics = sorted(topics, key=lambda k: topics[k], reverse=True)[:5]

    # Generate insights from real data
    insights = []
    if avg_rate > 4.0:
        insights.append({"type": "trend", "message": "互动率表现优秀，继续保持当前内容策略"})
    elif filtered_posts:
        insights.append({"type": "opportunity", "message": "互动率有提升空间，建议优化标题和封面"})

    if trend_topics:
        insights.append({"type": "trend", "message": f"热门话题：{'、'.join(trend_topics[:3])}"})

    if not filtered_posts:
        insights.append({"type": "info", "message": "暂无已完成的工作流数据，请先完成一次内容发布"})

    return success(
        data={
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
    )


@router.get("/performance/{account_id}")
async def get_performance(
    account_id: str,
    period: str = "weekly",
    limit: int = Query(20, ge=1, le=100),
    request: Request = None,  # type: ignore[assignment]
) -> ApiResponse[Any]:
    """获取最近帖子表现数据 — from real completed workflows."""
    assert request is not None
    graph = request.app.state.graph
    workflows = await _get_completed_workflows(graph, account_id)

    posts = []
    for wf in workflows:
        state = wf.get("_state", {})
        post = _extract_post_data(state)
        if post:
            posts.append(post)

    # Filter by period
    posts = _filter_by_period(posts, period)

    # Sort by published_at descending
    posts.sort(key=lambda p: p.get("published_at", ""), reverse=True)
    posts = posts[:limit]

    return success(
        data={
            "account_id": account_id,
            "period": period,
            "posts": posts,
            "total": len(posts),
            "fetched_at": datetime.now().isoformat(),
        }
    )


@router.get("/costs")
async def get_costs(period: str = "weekly", request: Request = None) -> ApiResponse[Any]:  # type: ignore[assignment]
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
) -> ApiResponse[Any]:
    """Single-request analytics bundle — report + performance + costs.

    Avoids 3× the cold-start cost of _get_completed_workflows by computing
    all three payloads from one fetch.
    """
    assert request is not None
    graph = request.app.state.graph
    workflows = await _get_completed_workflows(graph, account_id)

    # ── Extract posts once ──
    posts = []
    topics: dict[str, int] = {}
    for wf in workflows:
        state = wf.get("_state", {})
        post = _extract_post_data(state)
        if post:
            posts.append(post)
        plan = state.get("content_plan") or {}
        topic = plan.get("selected_topic")
        if topic:
            topics[topic] = topics.get(topic, 0) + 1

    filtered_posts = _filter_by_period(posts, period)

    # ── Growth report ──
    total_engagement = sum(p["likes"] + p["comments"] + p["collects"] for p in filtered_posts)
    avg_rate = (
        (sum(p["engagement_rate"] for p in filtered_posts) / len(filtered_posts))
        if filtered_posts
        else 0.0
    )
    best = max(filtered_posts, key=lambda p: p["likes"] + p["comments"], default=None)
    trend_topics = sorted(topics, key=lambda k: topics[k], reverse=True)[:5]

    insights = []
    if avg_rate > 4.0:
        insights.append({"type": "trend", "message": "互动率表现优秀，继续保持当前内容策略"})
    elif filtered_posts:
        insights.append({"type": "opportunity", "message": "互动率有提升空间，建议优化标题和封面"})
    if trend_topics:
        insights.append({"type": "trend", "message": f"热门话题：{'、'.join(trend_topics[:3])}"})
    if not filtered_posts:
        insights.append({"type": "info", "message": "暂无已完成的工作流数据，请先完成一次内容发布"})

    report = {
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

    # ── Performance ──
    sorted_posts = sorted(filtered_posts, key=lambda p: p.get("published_at", ""), reverse=True)[
        :limit
    ]
    performance = {
        "account_id": account_id,
        "period": period,
        "posts": sorted_posts,
        "total": len(sorted_posts),
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

    return success(data={"report": report, "performance": performance, "costs": costs})
