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
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger("xhs_growth.tools.topic_scorer")


@tool
async def topic_scorer(
    topic: str,
    keywords: list[str] | None = None,
    niche: str = "",
    time_window: str = "7d",
    account_id: str = "",
) -> dict[str, Any]:
    """评估小红书话题的热度得分与传播潜力.

    Args:
        topic: 待评估的话题名称
        keywords: 相关关键词列表
        niche: 所属垂直领域
        time_window: 数据时间窗口
        account_id: 用谁的凭据去读平台。空 = 部署级凭据（单账号部署）

    Returns:
        话题评分结果，包含热度得分、增长趋势、竞争度、推荐等级

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
        }

    finally:
        await client.close()
