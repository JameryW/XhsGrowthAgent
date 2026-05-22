"""话题评分工具 — 评估话题热度与传播潜力.

TODO: 接入真实数据分析，结合历史传播数据和实时热度.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool


@tool
async def topic_scorer(
    topic: str,
    keywords: list[str] = [],
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
    # TODO: 接入真实数据分析
    # 可参考 XHS 热门话题数据、搜索趋势、竞品分析
    # 综合评估热度、竞争度、时效性

    # Mock 评分逻辑
    base_score = 60

    # 关键词加分
    keyword_bonus = min(len(keywords) * 5, 20)

    # 垂直领域加分（热门领域）
    hot_niches = ["美食", "穿搭", "旅行", "护肤"]
    niche_bonus = 15 if niche in hot_niches else 0

    final_score = base_score + keyword_bonus + niche_bonus

    # 推荐等级判定
    if final_score >= 80:
        recommendation = "强烈推荐"
        action = "立即跟进"
    elif final_score >= 70:
        recommendation = "推荐"
        action = "优先考虑"
    elif final_score >= 60:
        recommendation = "可选"
        action = "观察趋势"
    else:
        recommendation = "暂不推荐"
        action = "等待时机"

    return {
        "topic": topic,
        "heat_score": final_score,
        "score_breakdown": {
            "base": base_score,
            "keyword_bonus": keyword_bonus,
            "niche_bonus": niche_bonus,
        },
        "growth_trend": "上升" if final_score > 65 else "平稳",
        "competition_level": "中等",
        "recommendation": recommendation,
        "suggested_action": action,
        "related_keywords": keywords[:5] if keywords else [f"#{topic}"],
        "best_posting_window": "晚8-10点",
        "note": "TODO: 接入真实数据分析",
    }