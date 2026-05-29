"""Analytics API routes — growth reports and performance data from real workflows."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request

from backend.api.responses import success
from backend.api.routes.workflow import _workflow_registry

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
    graph, account_id: str | None = None
) -> list[dict[str, Any]]:
    """Read full state for completed workflows, with caching."""
    cache_key = f"completed_{account_id or 'all'}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    results = []
    for wf in _workflow_registry.values():
        if wf.get("status") != "completed":
            continue
        if account_id and wf.get("account_id") != account_id:
            continue
        try:
            config = {"configurable": {"thread_id": wf["thread_id"]}}
            state = await graph.aget_state(config)
            if state.values:
                results.append({**wf, "_state": state.values})
        except Exception:
            continue

    _set_cached(cache_key, results)
    return results


def _extract_post_data(wf_state: dict) -> dict | None:
    """Extract post performance data from a completed workflow state."""
    publish = wf_state.get("publish_result") or {}
    analytics = wf_state.get("analytics") or {}
    copy = wf_state.get("copy_content") or {}
    plan = wf_state.get("content_plan") or {}

    title = (
        copy.get("selected_title")
        or plan.get("selected_topic")
        or publish.get("title", "")
    )

    if not title and not analytics:
        return None

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
    }


@router.get("/report/{account_id}")
async def get_growth_report(
    account_id: str, period: str = "weekly", request: Request = None
):
    """获取增长报告 — from real completed workflows."""
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
    now = datetime.now(timezone.utc)
    if period == "daily":
        cutoff_hours = 24
    elif period == "weekly":
        cutoff_hours = 7 * 24
    else:
        cutoff_hours = 30 * 24

    filtered_posts = []
    for p in posts:
        try:
            pub = datetime.fromisoformat(p["published_at"].replace(" ", "T"))
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            if (now - pub).total_seconds() / 3600 <= cutoff_hours:
                filtered_posts.append(p)
        except (ValueError, AttributeError):
            filtered_posts.append(p)

    total_engagement = sum(
        p["likes"] + p["comments"] + p["collects"] for p in filtered_posts
    )
    avg_rate = (
        sum(p["engagement_rate"] for p in filtered_posts) / len(filtered_posts)
        if filtered_posts
        else 0.0
    )
    best = max(filtered_posts, key=lambda p: p["likes"] + p["comments"], default=None)
    trend_topics = sorted(topics, key=topics.get, reverse=True)[:5]

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

    return success(data={
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
    })


@router.get("/performance/{account_id}")
async def get_performance(
    account_id: str, limit: int = 20, request: Request = None
):
    """获取最近帖子表现数据 — from real completed workflows."""
    graph = request.app.state.graph
    workflows = await _get_completed_workflows(graph, account_id)

    posts = []
    for wf in workflows:
        state = wf.get("_state", {})
        post = _extract_post_data(state)
        if post:
            posts.append(post)

    # Sort by published_at descending
    posts.sort(key=lambda p: p.get("published_at", ""), reverse=True)
    posts = posts[:limit]

    return success(data={
        "account_id": account_id,
        "posts": posts,
        "total": len(posts),
        "fetched_at": datetime.now().isoformat(),
    })


@router.get("/costs")
async def get_costs(request: Request):
    """获取 LLM 调用成本 — aggregated from workflow performance logs."""
    graph = request.app.state.graph
    workflows = await _get_completed_workflows(graph)

    by_model: dict[str, float] = {}
    total_cost = 0.0
    today_cost = 0.0
    today = datetime.now(timezone.utc).date()

    for wf in workflows:
        state = wf.get("_state", {})
        perf_log = state.get("performance_log") or []
        for entry in perf_log:
            cost = entry.get("cost_usd", 0.0)
            model = entry.get("model", "unknown")
            total_cost += cost
            by_model[model] = by_model.get(model, 0.0) + cost

            # Check if entry is from today
            try:
                ts = entry.get("timestamp", "")
                if ts:
                    entry_date = datetime.fromisoformat(ts).date()
                    if entry_date == today:
                        today_cost += cost
            except (ValueError, AttributeError):
                pass

    return success(data={
        "total_cost_usd": round(total_cost, 2),
        "today_cost_usd": round(today_cost, 2),
        "by_model": {k: round(v, 2) for k, v in by_model.items()},
        "circuit_open": False,
        "budget_remaining_usd": round(max(0, 10.0 - total_cost), 2),
        "updated_at": datetime.now().isoformat(),
    })
