"""XHS trending scraper tool — 获取热门话题和趋势数据."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.tools import tool

if TYPE_CHECKING:
    from backend.services.xhs_client import XHSClient

logger = logging.getLogger("xhs_growth.tools.trending")


async def _get_client(account_id: str = "") -> XHSClient:
    """获取 XHSClient 实例.

    account_id is kept for workflow/tool-call compatibility; XHS browser login
    state is resolved by CDP profile during publishing, not by HTTP credentials.
    """
    from backend.config.settings import Settings
    from backend.services.xhs_client import XHSClient

    settings = Settings()
    return XHSClient(
        use_browser=settings.platform.use_browser,
        headless=settings.platform.headless,
    )


@tool
async def xhs_trending(category: str = "", account_id: str = "") -> list[dict[str, Any]]:
    """获取小红书热门话题和趋势数据.

    Args:
        category: 分类筛选（可选）
        account_id: 工作流账号 ID（保留用于兼容调用签名）

    Returns:
        热门话题列表，每个包含 topic_id, title, heat_score, growth_rate
    """
    logger.info(f"Fetching XHS trending for category: {category}")

    client = await _get_client(account_id=account_id)
    try:
        topics = await client.get_trending(category=category)

        # 转换为字典格式
        results = []
        for topic in topics:
            results.append(
                {
                    "topic_id": topic.topic_id,
                    "topic": topic.title,
                    "heat_score": topic.heat_score,
                    "growth_rate": topic.growth_rate,
                    "related_keywords": topic.related_keywords[:5],
                    "category": topic.category,
                }
            )

        return results

    except Exception as e:
        logger.error(f"获取热门话题失败: {e}")
        return []

    finally:
        await client.close()


@tool
async def keyword_monitor(keywords: list[str], account_id: str = "") -> list[dict[str, Any]]:
    """监控指定关键词在小红书上的热度变化.

    Args:
        keywords: 关键词列表
        account_id: 工作流账号 ID（保留用于兼容调用签名）

    Returns:
        每个关键词的热度数据，包含 post_count, total_likes, avg_likes
    """
    logger.info(f"Monitoring keywords: {keywords}")

    if not keywords:
        return []

    client = await _get_client(account_id=account_id)
    try:
        results = await client.monitor_keywords(keywords)

        # 计算趋势
        for result in results:
            avg_likes = result.get("avg_likes", 0)
            if avg_likes > 500:
                result["trend"] = "rising"
            elif avg_likes > 100:
                result["trend"] = "stable"
            else:
                result["trend"] = "declining"

        return results

    except Exception as e:
        logger.error(f"关键词监控失败: {e}")
        return []

    finally:
        await client.close()


@tool
async def competitor_analyzer(
    account_id: str, niche: str = "", credential_account_id: str = ""
) -> list[dict[str, Any]]:
    """分析竞品账号的内容策略和表现.

    Args:
        account_id: 竞品账号 ID 或搜索关键词
        niche: 所属垂直领域
        credential_account_id: 工作流账号 ID（保留用于兼容调用签名）

    Returns:
        竞品分析结果，包含热门帖子、平均互动数据
    """
    logger.info(f"Analyzing competitor: {account_id}, niche: {niche}")

    # 使用账号名作为搜索关键词
    search_keyword = account_id
    if niche:
        search_keyword = f"{niche} {account_id}"

    client = await _get_client(account_id=credential_account_id)
    try:
        # 搜索该账号/领域的内容
        posts = await client.search_posts(keyword=search_keyword, limit=30)

        if not posts:
            return []

        # 计算统计数据
        total_likes = sum(p.likes for p in posts)
        total_comments = sum(p.comments for p in posts)
        total_collects = sum(p.collects for p in posts)

        avg_likes = total_likes / len(posts) if posts else 0
        avg_comments = total_comments / len(posts) if posts else 0

        # 找出表现最好的帖子
        top_posts = sorted(posts, key=lambda x: x.likes, reverse=True)[:5]

        return [
            {
                "account": account_id,
                "niche": niche,
                "post_count": len(posts),
                "avg_likes": round(avg_likes, 2),
                "avg_comments": round(avg_comments, 2),
                "avg_collects": round(total_collects / len(posts) if posts else 0, 2),
                "top_posts": [
                    {
                        "note_id": p.note_id,
                        "title": p.title,
                        "likes": p.likes,
                        "url": p.note_url,
                    }
                    for p in top_posts
                ],
            }
        ]

    except Exception as e:
        logger.error(f"竞品分析失败: {e}")
        return []

    finally:
        await client.close()
