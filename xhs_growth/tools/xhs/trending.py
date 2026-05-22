"""XHS trending scraper tool."""

from langchain_core.tools import tool


@tool
async def xhs_trending(category: str = "") -> list[dict]:
    """获取小红书热门话题和趋势数据"""
    # TODO: 接入真实 XHS API
    return [{"topic": "示例热门话题", "heat_score": 100, "category": category or "综合"}]


@tool
async def keyword_monitor(keywords: list[str]) -> list[dict]:
    """监控指定关键词在小红书上的热度变化"""
    return [{"keyword": kw, "heat": 0, "trend": "stable"} for kw in keywords]


@tool
async def competitor_analyzer(account_id: str, niche: str = "") -> list[dict]:
    """分析竞品账号的内容策略和表现"""
    return [{"account": account_id, "niche": niche, "avg_likes": 0}]