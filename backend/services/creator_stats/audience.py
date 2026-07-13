"""Analysis helpers for aggregate Creator Center audience signals."""

from __future__ import annotations

from typing import Any

from backend.services.creator_stats.types import AccountStatsOverview, NoteStats


def _number(value: Any) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def _label(item: dict[str, Any]) -> str:
    for key in ("title", "name", "label", "text", "start_point"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return "未命名"


def summarize_audience(
    account: AccountStatsOverview | None,
    notes: list[NoteStats] | None = None,
) -> dict[str, Any]:
    """Return UI-ready aggregate audience distributions and safe conclusions.

    The Creator Center exposes aggregate buckets, not viewer identities.  A
    missing bucket is represented as an empty list and explicitly reflected in
    ``coverage`` so the UI does not imply that an uncollected dimension is
    zero.
    """
    if account is None:
        return {
            "source_distribution": [],
            "peak_view_periods": [],
            "audience_profile": [],
            "coverage": {"sources": False, "periods": False, "profile": False},
            "insights": [],
        }

    sources = [dict(item) for item in account.audience_sources]
    sources.sort(key=lambda item: _number(item.get("value") or item.get("count")), reverse=True)
    periods = [dict(item) for item in account.audience_view_periods]
    periods.sort(key=lambda item: _number(item.get("count") or item.get("value")), reverse=True)
    profile = [dict(item) for item in account.audience_profile]

    insights: list[str] = []
    if sources:
        top = sources[0]
        count = int(_number(top.get("value") or top.get("count")))
        insights.append(f"主要观看来源：{_label(top)}（{count}）")
    if periods:
        top_period = periods[0]
        start = top_period.get("start_point", "")
        end = top_period.get("end_point", "")
        span = f"{start}-{end}" if start or end else _label(top_period)
        insights.append(f"高峰观看时段：{span}")
    if profile:
        insights.append("已获得聚合观众画像，可结合高峰时段优化选题和发布时间")
    if not sources and not periods and not profile:
        insights.append("当前账号暂无可用的观众聚合数据，请重新打开创作者中心后导入")

    return {
        "source_distribution": sources,
        "peak_view_periods": periods[:8],
        "audience_profile": profile,
        "detail_metrics": dict(account.detail_metrics),
        "coverage": {
            "sources": bool(sources),
            "periods": bool(periods),
            "profile": bool(profile),
            "notes_with_view_sources": sum(bool(note.view_sources) for note in (notes or [])),
        },
        "insights": insights,
    }
