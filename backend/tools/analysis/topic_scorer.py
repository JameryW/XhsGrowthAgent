"""话题评分工具 — 评估话题热度与传播潜力.

整合小红书真实数据分析，结合热门话题、搜索趋势和竞品分析.
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
) -> dict[str, Any]:
    """评估小红书话题的热度得分与传播潜力.

    Args:
        topic: 待评估的话题名称
        keywords: 相关关键词列表
        niche: 所属垂直领域
        time_window: 数据时间窗口

    Returns:
        话题评分结果，包含热度得分、增长趋势、竞争度、推荐等级
    """
    if keywords is None:
        keywords = []
    logger.info(f"Scoring topic: {topic}")

    from backend.config.settings import Settings
    from backend.services.xhs_client import XHSClient

    settings = Settings()
    client = XHSClient(
        cookie=settings.platform.cookie,
        user_id=settings.platform.user_id,
    )

    try:
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

        return {
            "topic": topic,
            "heat_score": round(final_score, 1),
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
            "competition_level": competition_level,
            "recommendation": recommendation,
            "suggested_action": action,
            "related_keywords": keywords[:5] if keywords else [f"#{topic}"],
            "best_posting_window": best_posting_window,
            "reference_posts": reference_posts,
        }

    except Exception as e:
        logger.error(f"话题评分失败: {e}")

        # 返回基础评分作为降级方案
        return {
            "topic": topic,
            "heat_score": 50,
            "error": str(e),
            "recommendation": "数据获取失败，建议手动评估",
            "related_keywords": keywords[:5] if keywords else [f"#{topic}"],
        }

    finally:
        await client.close()