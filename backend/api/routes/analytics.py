"""Analytics API routes — growth reports, creator-stats import, and creative advice."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field, field_validator

from backend.api.responses import ApiResponse, success
from backend.db.pool import is_pool_ready
from backend.db.workflows import list_workflows as db_list

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
    """Filter posts by time period.

    Posts without a parseable ``published_at`` are excluded (period-scoped
    analytics must not treat undated rows as always-in-range).
    """
    now = datetime.now(UTC)
    cutoff_hours = _period_cutoff_hours(period)
    filtered = []
    for p in posts:
        published = p.get("published_at")
        if published is None or published == "":
            continue
        try:
            pub = datetime.fromisoformat(str(published).replace(" ", "T"))
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=UTC)
            if (now - pub).total_seconds() / 3600 <= cutoff_hours:
                filtered.append(p)
        except (ValueError, AttributeError, TypeError):
            continue
    return filtered


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
        "id": publish.get("post_id", wf_state.get("session_id", "")),
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


@router.get("/report/{account_id}")
async def get_growth_report(
    account_id: str,
    period: str = "weekly",
    request: Request = None,  # type: ignore[assignment]
) -> ApiResponse[Any]:
    """获取增长报告 — workflows + imported creator-center notes."""
    assert request is not None
    account_id = (account_id or "").strip()
    graph = request.app.state.graph
    workflows = await _get_completed_workflows(graph, account_id)

    posts: list[dict[str, Any]] = []
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

    posts = await _merge_imported_posts(account_id, posts, limit=100)
    for t, c in _topics_from_imported(posts).items():
        topics[t] = topics.get(t, 0) + c
    filtered_posts = _filter_by_period(posts, period)
    return success(data=_build_growth_report(account_id, period, filtered_posts, topics))


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
                "title": d.get("title", ""),
                "likes": int(d.get("likes") or 0),
                "comments": int(d.get("comments") or 0),
                "collects": int(d.get("collects") or 0),
                "shares": int(d.get("shares") or 0),
                "views": int(d.get("views") or 0),
                "engagement_rate": _as_percent_engagement_rate(d.get("engagement_rate")),
                "published_at": d.get("published_at", ""),
                "dry_run": False,
                "source": d.get("source") or "creator_statistics",
            }
        )
    return posts


async def _merge_imported_posts(
    account_id: str,
    posts: list[dict[str, Any]],
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Append imported creator-center notes not already present (by post id)."""
    try:
        from backend.db import creator_stats as stats_db

        imported = await stats_db.list_note_stats(account_id, limit=limit, order_by="published")
    except Exception:
        return posts
    seen_ids = {p.get("id") for p in posts if p.get("id")}
    for ip in _imported_notes_as_posts(imported):
        if ip["id"] and ip["id"] in seen_ids:
            continue
        posts.append(ip)
        if ip["id"]:
            seen_ids.add(ip["id"])
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
) -> ApiResponse[Any]:
    """获取最近帖子表现 — workflow publish analytics + imported creator-center notes."""
    assert request is not None
    account_id = (account_id or "").strip()
    graph = request.app.state.graph
    workflows = await _get_completed_workflows(graph, account_id)

    posts: list[dict[str, Any]] = []
    for wf in workflows:
        state = wf.get("_state", {})
        post = _extract_post_data(state)
        if post:
            posts.append(post)

    posts = await _merge_imported_posts(account_id, posts, limit=max(limit, 50))
    posts = _filter_by_period(posts, period)
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
) -> ApiResponse[Any]:
    """Single-request analytics bundle — report + performance + costs.

    Avoids 3× the cold-start cost of _get_completed_workflows by computing
    all three payloads from one fetch. Includes imported creator-center notes
    (frontend Analytics uses this path exclusively).
    """
    assert request is not None
    account_id = (account_id or "").strip()
    graph = request.app.state.graph
    workflows = await _get_completed_workflows(graph, account_id)

    # ── Extract posts once ──
    posts: list[dict[str, Any]] = []
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

    # Merge imported creator-center stats (same as /performance)
    posts = await _merge_imported_posts(account_id, posts, limit=max(limit, 50))
    for t, c in _topics_from_imported(posts).items():
        topics[t] = topics.get(t, 0) + c

    filtered_posts = _filter_by_period(posts, period)
    report = _build_growth_report(account_id, period, filtered_posts, topics)

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

    return success(data={"report": report, "performance": performance, "costs": costs})


# ── Creator-center stats import + creative suggestions ──────────────────────


@router.post("/creator-stats/sync")
async def sync_creator_stats(
    body: CreatorStatsSyncRequest,
    request: Request,
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
        result = SyncResult(
            account_id=body.account_id,
            source="creator_statistics",
            error="未检测到该账号可用的浏览器会话。请先启动并登录绑定账号的 Chrome 后重试。",
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
    return success(data=data)


@router.post("/creator-stats/sync-all")
async def sync_all_creator_stats(
    body: CreatorStatsSyncAllRequest,
    request: Request,
) -> ApiResponse[Any]:
    """导入所有激活账号；停用账号不会启动浏览器或写入数据。"""
    from backend.services.creator_stats.pipeline import sync_all_active_accounts

    graph = getattr(request.app.state, "graph", None)
    store = getattr(graph, "store", None) if graph is not None else None
    data = await sync_all_active_accounts(
        store=store,
        period=body.period,
        run_creative_analysis=body.analyze,
    )
    return success(data=data)


@router.get("/creator-stats/{account_id}")
async def get_creator_stats(
    account_id: str,
    limit: int = Query(50, ge=1, le=200),
) -> ApiResponse[Any]:
    """读取本地已导入的创作者中心账户/笔记统计。"""
    from backend.db import creator_stats as stats_db
    from backend.services.creator_stats.audience import summarize_audience

    account_id = (account_id or "").strip()
    account = await stats_db.get_account_stats(account_id)
    notes = await stats_db.list_note_stats(account_id, limit=limit)
    # total = full count (not page size); note_count on account is a fallback
    total = await stats_db.count_note_stats(account_id)
    if total == 0 and account is not None:
        total = int(getattr(account, "note_count", 0) or 0)
    return success(
        data={
            "account_id": account_id,
            "account": account.to_dict() if account else None,
            "notes": [n.to_dict() for n in notes],
            "audience_analysis": summarize_audience(account, notes),
            "total": total,
            "limit": limit,
            "fetched_at": datetime.now(UTC).isoformat(),
        }
    )


@router.get("/creator-stats/{account_id}/quality")
async def get_creator_quality(
    account_id: str,
    locale: str = Query("zh-CN", max_length=16, description="报告文案语言：zh-CN | en"),
) -> ApiResponse[Any]:
    """Return a read-only quality report over every imported note for an account."""
    from backend.db import creator_stats as stats_db
    from backend.services.creator_stats.quality import analyze_historical_quality

    normalized_account_id = (account_id or "").strip()
    # Do not use list_note_stats here: that reader is intentionally capped for
    # interactive display.  Historical quality must state and analyze the full
    # durable note history without triggering a browser re-sync or DB writes.
    notes = await stats_db.list_all_note_stats(normalized_account_id)
    report = analyze_historical_quality(notes, normalized_account_id, locale=locale)
    return success(data=report.to_dict())


@router.get("/creator-stats/{account_id}/suggestions")
async def get_creator_suggestions(
    account_id: str,
    mode: str = Query(
        "trend",
        description="创作模式：trend | brief | free（大小写不敏感）",
    ),
    request: Request = None,  # type: ignore[assignment]
) -> ApiResponse[Any]:
    """按创作模式返回账户级创作建议（共享召回面）。"""
    from backend.services.creator_stats.suggestions import (
        _normalize_mode,
        get_suggestions_for_mode,
    )

    assert request is not None
    account_id = (account_id or "").strip()
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
async def get_creator_analysis(account_id: str) -> ApiResponse[Any]:
    """对已导入笔记即时跑创作分析（不强制重新拉取远端）。"""
    from backend.db import creator_stats as stats_db
    from backend.services.creator_stats.analyze import analyze_notes
    from backend.services.creator_stats.audience import summarize_audience
    from backend.services.creator_stats.suggestions import suggestions_from_analysis

    account_id = (account_id or "").strip()
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
