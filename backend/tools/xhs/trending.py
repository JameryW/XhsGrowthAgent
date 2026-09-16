"""XHS trending scraper tool — 获取热门话题和趋势数据.

These three are *read* capabilities reached through the Tool Gateway
(P1c-S3d), so they no longer normalise their own failures. Each one used to
answer every exception with ``[]``, which collapsed three different situations
into one value: the platform had nothing, the request failed, and we could not
ask at all. Normalisation now has exactly one home — the Gateway, which files a
raised exception as ``ToolResult(ok=False, error_kind=EXCEPTION)`` and lets the
caller degrade. An empty list returned from here therefore means one thing
only: the platform was asked and said nothing.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.tools import tool

if TYPE_CHECKING:
    from backend.services.xhs_client import XHSClient

logger = logging.getLogger("xhs_growth.tools.trending")


async def _get_client(account_id: str = "") -> XHSClient:
    """获取 XHSClient 实例 —— 带上这个账号的凭据.

    ``account_id`` used to be decorative here ("kept for workflow/tool-call
    compatibility"): the client was built with no cookie at all, so every HTTP
    read failed and ``_require_readable`` below fired on every call. Browser
    login state lives in the CDP profile and is only wired up for publishing, so
    the read path has to be credentialed from the credential store. That
    plumbing now lives in ``services/xhs_credentials``: this account's own row
    if it has one, otherwise the deployment credential, and an unusable answer
    stays unusable rather than being papered over here.
    """
    from backend.config.settings import Settings
    from backend.services.xhs_client import XHSClient
    from backend.services.xhs_credentials import load_credential

    settings = Settings()
    credential = await load_credential(account_id)
    return XHSClient(
        cookie=credential.cookie,
        user_id=credential.user_id,
        use_browser=settings.platform.use_browser,
        headless=False,
    )


def _require_readable(client: XHSClient, capability: str) -> None:
    """Refuse to treat an unreadable platform as an empty one.

    ``XHSClient`` needs a cookie for every HTTP read, and the credential this
    account holds is resolved in ``_get_client`` — so this fires when the
    resolved credential is missing, malformed, or could not be read at all.

    That is the point. Without it the previous path answered the same
    situation with ``[]`` from ``get_trending``/``search_posts`` and, worse,
    with one row of zero counts per keyword from ``monitor_keywords``, which
    ``trend_scout`` then fed the model as ``data_source="real"`` ("0 篇帖子,
    平均点赞 0, 趋势: declining" — fabricated evidence, asserted as real).
    Raising hands the problem to the Gateway; the caller falls back to the
    honest "no realtime data" branch instead.

    The precondition is knowable *before* the call and is not knowable after
    it, which is why it is checked here rather than inferred from the result.

    Which account's cookie, sourced from where, is answered in
    ``services/xhs_credentials`` (P2a-S5a); this guard only asks whether the
    answer was usable. The Gateway's scope check reads the same answer, so a
    read cannot be credentialed while its scope is denied.
    """
    if client.can_read:
        return
    from backend.services.xhs_client import XHSAuthError

    raise XHSAuthError(f"{capability}: 未配置 Cookie，无法读取小红书平台数据")


@tool
async def xhs_trending(category: str = "", account_id: str = "") -> list[dict[str, Any]]:
    """获取小红书热门话题和趋势数据.

    Args:
        category: 分类筛选（可选）
        account_id: 工作流账号 ID（保留用于兼容调用签名）

    Returns:
        热门话题列表，每个包含 topic_id, title, heat_score, growth_rate

    Raises:
        XHSAuthError: 无 Cookie，根本读不到平台 —— 调用方应降级，而不是把它
            当作"这个领域没有热点"。
    """
    logger.info(f"Fetching XHS trending for category: {category}")

    client = await _get_client(account_id=account_id)
    try:
        _require_readable(client, "xhs_trending")
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

    Raises:
        XHSAuthError: 无 Cookie（见 :func:`_require_readable` —— 此前这种情况
            会返回"每个关键词一行零"的假数据）。
    """
    logger.info(f"Monitoring keywords: {keywords}")

    if not keywords:
        return []

    client = await _get_client(account_id=account_id)
    try:
        _require_readable(client, "keyword_monitor")
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

    Raises:
        XHSAuthError: 无 Cookie，根本读不到平台（调用方应降级）。
    """
    logger.info(f"Analyzing competitor: {account_id}, niche: {niche}")

    # 使用账号名作为搜索关键词
    search_keyword = account_id
    if niche:
        search_keyword = f"{niche} {account_id}"

    client = await _get_client(account_id=credential_account_id)
    try:
        _require_readable(client, "competitor_analyzer")

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

    finally:
        await client.close()
