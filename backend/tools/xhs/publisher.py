"""XHS publisher tool — 发布小红书笔记."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.tools import tool

if TYPE_CHECKING:
    from backend.services.xhs_publisher import XHSPublisher

logger = logging.getLogger("xhs_growth.tools.publisher")


def _get_publisher() -> XHSPublisher:
    """获取 XHSPublisher 实例"""
    from backend.config.settings import Settings
    from backend.services.xhs_publisher import XHSPublisher

    settings = Settings()
    return XHSPublisher(
        cookie="",
        headless=False,
        cdp_endpoint=settings.platform.cdp_endpoint,
    )


@tool
async def xhs_publisher(
    title: str,
    body: str,
    hashtags: list[str] | None = None,
    image_paths: list[str] | None = None,
    category: str = "",
    location: str = "",
    scheduled_time: str = "",
    is_private: bool = False,
) -> dict[str, Any]:
    """发布小红书笔记.

    Args:
        title: 笔记标题
        body: 正文内容
        hashtags: 标签列表 (最多5个)
        image_paths: 图片路径列表
        category: 内容分类
        location: 发布地点
        scheduled_time: 定时发布时间
        is_private: 是否仅自己可见

    Returns:
        发布结果: post_id, status, post_url
    """
    if hashtags is None:
        hashtags = []
    if image_paths is None:
        image_paths = []
    logger.info(f"Publishing note: {title}")

    publisher = _get_publisher()
    try:
        result = await publisher.publish_note(
            title=title,
            body=body,
            image_paths=image_paths,
            hashtags=hashtags[:5],
            category=category,
            location=location,
            scheduled_time=scheduled_time,
            is_private=is_private,
        )

        return {
            "post_id": result.get("post_id", ""),
            "post_url": result.get("post_url", ""),
            "status": result.get("status", "unknown"),
            "published_at": result.get("published_at", ""),
            "error": result.get("error", ""),
        }

    except Exception as e:
        logger.error(f"发布失败: {type(e).__name__}: {e}")
        return {"post_id": "", "status": "error", "error": str(e)}

    finally:
        await publisher.close()


@tool
async def ab_test_manager(
    base_post_id: str,
    variant_titles: list[str],
    duration_hours: int = 4,
) -> dict[str, Any]:
    """管理 A/B 测试 — 对比不同标题/封面的表现.

    Args:
        base_post_id: 基础帖子 ID
        variant_titles: 变体标题列表 (最多3个)
        duration_hours: 测试持续时间

    Returns:
        A/B 测试配置结果
    """
    logger.info(f"Setting up A/B test for post: {base_post_id}")

    import time

    test_id = f"ab_{int(time.time())}"

    return {
        "test_id": test_id,
        "base_post_id": base_post_id,
        "variants": [
            {"variant_id": f"v{i}", "title": title} for i, title in enumerate(variant_titles[:3])
        ],
        "duration_hours": duration_hours,
        "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "configured",
        "note": "需要数据库支持存储测试数据",
    }


@tool
async def post_scheduler(
    post_id: str,
    publish_time: str,
) -> dict[str, Any]:
    """调度帖子在最佳时间发布.

    Args:
        post_id: 帖子 ID
        publish_time: 发布时间 (格式: "2024-03-15 18:00")

    Returns:
        调度结果
    """
    logger.info(f"Scheduling post {post_id} for {publish_time}")

    return {
        "scheduled": True,
        "post_id": post_id,
        "publish_time": publish_time,
        "scheduler_note": "需要集成 APScheduler 实现真实调度",
        "status": "configured",
    }
