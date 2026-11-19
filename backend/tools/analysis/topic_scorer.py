"""话题评分工具 — 评估话题热度与传播潜力.

整合小红书真实数据分析，结合热门话题、搜索趋势和竞品分析.

Two things were fixed here rather than left for a later pass, because they were
the same defect wearing two coats:

1. **It read as nobody.**  ``XHSClient()`` was built with no cookie at all, so
   ``search_posts``/``monitor_keywords`` raised on every call — while this
   capability declares ``auth_scope=("xhs:read",)``, a grant nothing could
   satisfy.  It now resolves the account's credential through
   ``services/xhs_client.client_for_account``, the same owner the three
   ``xhs.*`` read capabilities use.
2. **It answered "unreadable" with a score.**  The ``except`` turned every
   failure into ``heat_score=50, potential_score=25.0``, which the caller wrote
   into the prompt as if measured.  Nothing here may invent a measurement: the
   guard raises, the Gateway files ``ToolResult(ok=False)``, and the caller
   skips the topic.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from langchain_core.tools import tool

from backend.tools.analysis.collect_first import (
    PostFeatures,
    fit_calibration,
    forecast_payload,
)
from backend.tools.content.novelty import novelty_penalty

logger = logging.getLogger("xhs_growth.tools.topic_scorer")

_PREFERRED_HOURS = {
    "美食": {8, 12, 19},
    "穿搭": {8, 20},
    "旅行": {21},
    "护肤": {20, 21, 22},
}
_DEFAULT_HOURS = {20, 21, 22}


def _parse_published_at(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _slot_performance(history_records: list[dict[str, Any]] | None) -> dict[int, list[float]]:
    """Bucket historical engagement by half-hour publishing slot."""
    buckets: dict[int, list[float]] = {}
    for record in history_records or []:
        if not isinstance(record, dict):
            continue
        published = _parse_published_at(record.get("published_at"))
        if published is None:
            continue
        slot = published.hour * 2 + (1 if published.minute >= 30 else 0)
        engagement_rate = record.get("engagement_rate")
        if isinstance(engagement_rate, (int, float)):
            value = max(0.0, float(engagement_rate))
        else:
            views = record.get("views")
            if not isinstance(views, (int, float)) or float(views) <= 0:
                continue
            interactions = sum(
                float(record.get(key) or 0) for key in ("likes", "collects", "comments", "shares")
            )
            value = interactions / float(views)
        buckets.setdefault(slot, []).append(value)
    return buckets


def _time_pop(
    now: datetime,
    niche: str,
    history_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """TimePop features plus history-aware half-hour slot recommendations."""
    from backend.services.temporal_contracts import encode_time_features, rank_counterfactual_slots

    preferred = _PREFERRED_HOURS.get(niche, _DEFAULT_HOURS)
    bucket = _slot_performance(history_records)
    slot_average = {
        slot: sum(values) / len(values) for slot, values in bucket.items() if len(values) >= 2
    }
    best_average = max(slot_average.values(), default=0.0)

    def prior_score(slot: dict[str, Any]) -> float:
        hour = int(str(slot.get("label", "20:00"))[:2])
        distance = min(abs(hour - pref) for pref in preferred)
        return 100.0 if distance == 0 else max(0.0, 90.0 - distance * 10.0)

    def score(slot: dict[str, Any]) -> float:
        average = slot_average.get(int(slot["slot"]))
        if average is None or best_average <= 0:
            return 0.5 * prior_score(slot)
        historical = 100.0 * average / best_average
        return 0.95 * historical + 0.05 * prior_score(slot)

    ranked = rank_counterfactual_slots(now.date(), score)[:3]
    recommended: list[dict[str, Any]] = []
    for item in ranked:
        samples = len(bucket.get(int(item["slot"]), ()))
        recommended.append(
            {
                "label": item["label"],
                "slot": item["slot"],
                "score": round(float(item["score"]), 3),
                "source": "history" if samples >= 2 else "prior",
                "samples": samples,
            }
        )
    return {
        "features": encode_time_features(now).as_dict(),
        "recommended_slots": recommended,
    }


def _history_inhibition(
    history_records: list[dict[str, Any]] | None,
    candidate: str,
    now: datetime,
) -> dict[str, Any]:
    """Apply the refractory-window gate to the nearest recent published note."""
    from backend.services.temporal_contracts import inhibit_factor

    latest: tuple[datetime, str] | None = None
    for record in history_records or []:
        if not isinstance(record, dict):
            continue
        published = _parse_published_at(record.get("published_at"))
        title = str(record.get("title") or record.get("selected_title") or "")
        if published is None or not title:
            continue
        if latest is None or published > latest[0]:
            latest = (published, title)
    if latest is None:
        return {"active": False, "factor": 1.0}
    age_hours = max(0.0, (now - latest[0]).total_seconds() / 3600.0)
    similarity = novelty_penalty(candidate, [latest[1]]).max_similarity
    factor = inhibit_factor(age_hours, similarity)
    return {
        "active": factor < 1.0,
        "factor": round(factor, 6),
        "delta_hours": round(age_hours, 3),
        "similarity": round(similarity, 6),
        "reference_title": latest[1],
    }


@tool
async def topic_scorer(
    topic: str,
    keywords: list[str] | None = None,
    niche: str = "",
    time_window: str = "7d",
    account_id: str = "",
    history_titles: list[str] | None = None,
    history_records: list[dict[str, Any]] | None = None,
    snapshots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """评估小红书话题的热度得分与传播潜力.

    Args:
        topic: 待评估的话题名称
        keywords: 相关关键词列表
        niche: 所属垂直领域
        time_window: 数据时间窗口
        account_id: 用谁的凭据去读平台。空 = 部署级凭据（单账号部署）
        history_titles: 该账号最近已发布笔记标题（用于 Novelty Penalty）
        history_records: 同一批笔记的历史表现记录（用于账号级预测校准）
        snapshots: 最近互动快照序列（用于账号级 Hawkes 拟合）

    Returns:
        话题评分结果，包含热度得分、增长趋势、竞争度、推荐等级，
        以及 Collect-First 四头预测 / 14 天扩散曲线 / 新颖度惩罚

    Raises:
        XHSAuthError: 无可用 Cookie（见
            :func:`backend.services.xhs_client.require_readable`）。**这条以前不存在**：
            空 cookie 的 ``XHSClient()`` 让每次读取都抛异常，而下面的 except 把它变成
            ``heat_score=50, potential_score=25.0`` —— 一个从未测量过的分数，被调用方
            当作真实数据写进 prompt（"趋势 N/A、热度 50"）。删掉那层兜底而不是给它
            加日志，是因为"读不到"与"读了，分数是 50"必须是两个答案。
    """
    if keywords is None:
        keywords = []
    logger.info(f"Scoring topic: {topic}")

    from backend.services.xhs_client import client_for_account, require_readable

    client = await client_for_account(account_id)
    try:
        require_readable(client, "topic_scorer")
        # 1. 搜索话题相关帖子
        search_posts = await client.search_posts(keyword=topic, limit=50)

        # 2. 监控关键词热度
        all_keywords = [topic] + keywords[:5]
        keyword_data = await client.monitor_keywords(all_keywords)

        # 3. 计算得分
        base_score = 50

        # 搜索量评分 (帖子数量)
        post_count = len(search_posts)
        post_score = min(post_count * 2, 30)  # 最高 30 分

        # 平均互动评分
        if search_posts:
            avg_likes = sum(p.likes for p in search_posts) / len(search_posts)
            avg_comments = sum(p.comments for p in search_posts) / len(search_posts)
            interaction_score = min(avg_likes / 100 + avg_comments / 20, 20)  # 最高 20 分
        else:
            interaction_score = 0

        # 关键词热度评分
        keyword_score = 0
        for kw_data in keyword_data:
            if kw_data.get("keyword") == topic:
                kw_avg = kw_data.get("avg_likes", 0)
                keyword_score = min(kw_avg / 50, 10)  # 最高 10 分
                break

        # 垂直领域加分
        hot_niches = ["美食", "穿搭", "旅行", "护肤", "健身", "家居"]
        niche_bonus = 10 if niche in hot_niches else 0

        final_score = base_score + post_score + interaction_score + keyword_score + niche_bonus

        # 确定趋势
        if avg_likes > 500 if search_posts else False:
            growth_trend = "爆发期"
        elif avg_likes > 200 if search_posts else False:
            growth_trend = "上升期"
        elif avg_likes > 50 if search_posts else False:
            growth_trend = "平稳期"
        else:
            growth_trend = "衰退期"

        # 确定竞争度
        if post_count > 100:
            competition_level = "激烈"
        elif post_count > 30:
            competition_level = "中等"
        else:
            competition_level = "低"

        # 推荐等级
        if final_score >= 80:
            recommendation = "强烈推荐"
            action = "立即跟进，抢占热点"
        elif final_score >= 70:
            recommendation = "推荐"
            action = "优先考虑，尽快产出"
        elif final_score >= 60:
            recommendation = "可选"
            action = "观察趋势，适时切入"
        elif final_score >= 50:
            recommendation = "谨慎"
            action = "需要差异化角度"
        else:
            recommendation = "暂不推荐"
            action = "等待时机或换话题"

        # 最佳发布时间 (基于小红书用户活跃规律)
        best_times = {
            "美食": "早8点、午12点、晚7点",
            "穿搭": "早8点、晚8点",
            "旅行": "晚9点",
            "护肤": "晚8-10点",
            "default": "晚8-10点",
        }
        best_posting_window = best_times.get(niche, best_times["default"])

        # 获取相关热门帖子作为参考
        top_posts = sorted(search_posts, key=lambda x: x.likes, reverse=True)[:3]
        reference_posts = [
            {
                "note_id": p.note_id,
                "title": p.title,
                "likes": p.likes,
                "url": p.note_url,
            }
            for p in top_posts
        ]

        # growth_rate: 0.0-1.0 scale based on trend phase
        growth_rate_map = {
            "爆发期": 0.8,
            "上升期": 0.5,
            "平稳期": 0.2,
            "衰退期": -0.1,
        }
        growth_rate = growth_rate_map.get(growth_trend, 0.0)

        # potential_score: composite of heat and growth
        potential_score = round(final_score * max(growth_rate, 0) * 1.25, 1)
        potential_score = min(potential_score, 100.0)

        # OranSim-style Collect-First forecast (deterministic, no extra API).
        sample_title = str(getattr(top_posts[0], "title", "") if top_posts else topic) or topic
        sample_body = str(getattr(top_posts[0], "content", "") if top_posts else "") or sample_title
        calibration = fit_calibration(history_records or [])
        collect_forecast = forecast_payload(
            PostFeatures(title=sample_title, body=sample_body, tags=tuple(keywords or ())),
            snapshots=snapshots,
            calibration=calibration,
        )
        now = datetime.now(UTC)
        inhibition = _history_inhibition(
            history_records,
            f"{topic} {sample_title}",
            now,
        )
        if inhibition.get("active"):
            factor = float(inhibition["factor"])
            for key in (
                "predicted_read",
                "predicted_like",
                "predicted_collect",
                "predicted_comment",
            ):
                value = collect_forecast.get(key)
                if isinstance(value, (int, float)):
                    collect_forecast[key] = round(float(value) * factor, 3)
        collect_forecast["inhibition"] = inhibition
        time_pop = _time_pop(now, niche, history_records)

        # AutoViralAI-style novelty penalty against the account's recent notes.
        novelty = novelty_penalty(f"{topic} {sample_title}", history_titles or [])
        if novelty.is_duplicate_risk:
            potential_score = max(0.0, round(potential_score - novelty.penalty, 1))

        return {
            "topic": topic,
            "heat_score": round(final_score, 1),
            "heat_percentage": round(final_score, 1),
            "potential_score": potential_score,
            "score_breakdown": {
                "base": base_score,
                "post_count_score": round(post_score, 1),
                "interaction_score": round(interaction_score, 1),
                "keyword_score": round(keyword_score, 1),
                "niche_bonus": niche_bonus,
            },
            "data_metrics": {
                "post_count": post_count,
                "avg_likes": round(avg_likes, 1) if search_posts else 0,
                "avg_comments": round(avg_comments, 1) if search_posts else 0,
            },
            "growth_trend": growth_trend,
            "growth_rate": growth_rate,
            "competition_level": competition_level,
            "recommendation": recommendation,
            "suggested_action": action,
            "related_keywords": keywords[:5] if keywords else [f"#{topic}"],
            "best_posting_window": best_posting_window,
            "reference_posts": reference_posts,
            "predicted_collect": collect_forecast.get("predicted_collect"),
            "collect_first": collect_forecast,
            "time_pop": time_pop,
            "inhibition": inhibition,
            "novelty": novelty.as_dict()
            if hasattr(novelty, "as_dict")
            else {
                "max_similarity": novelty.max_similarity,
                "threshold": novelty.threshold,
                "penalty": novelty.penalty,
                "is_duplicate_risk": novelty.is_duplicate_risk,
            },
        }

    finally:
        await client.close()
