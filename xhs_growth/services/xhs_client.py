"""Xiaohongshu platform client — API + Playwright dual mode."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger("xhs_growth.xhs_client")


class XHSRateLimitError(Exception):
    pass


class XHSAuthError(Exception):
    pass


class XHSPublishError(Exception):
    pass


@dataclass
class XHSPost:
    title: str
    body: str
    hashtags: list[str] = field(default_factory=list)
    image_paths: list[str] = field(default_factory=list)
    category: str = ""
    location: str = ""
    is_private: bool = False
    post_type: str = "normal"


@dataclass
class XHSAnalytics:
    post_id: str
    views: int = 0
    likes: int = 0
    collects: int = 0
    comments: int = 0
    shares: int = 0
    engagement_rate: float = 0.0
    fetched_at: str = ""


@dataclass
class XHSComment:
    comment_id: str
    post_id: str
    user_name: str
    content: str
    like_count: int = 0
    created_at: str = ""


@dataclass
class XHSDirectMessage:
    message_id: str
    sender_id: str
    sender_name: str
    content: str
    timestamp: str = ""


class XHSClient:
    """小红书平台交互客户端，支持 API 和浏览器自动化两种模式"""

    def __init__(self, cookie: str = "", user_id: str = "", use_browser: bool = False, headless: bool = True):
        self.cookie = cookie
        self.user_id = user_id
        self.use_browser = use_browser
        self.headless = headless
        self._http = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        await self._http.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        retry=retry_if_exception_type((XHSRateLimitError, ConnectionError, TimeoutError)),
        reraise=True,
    )
    async def get_trending(self, category: str = "") -> list[dict[str, Any]]:
        """获取热门话题"""
        # TODO: 实现真实 API 调用或浏览器自动化
        logger.info(f"Fetching trending topics for category: {category}")
        return []

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        retry=retry_if_exception_type((XHSRateLimitError, ConnectionError, TimeoutError)),
    )
    async def search_posts(self, keyword: str, limit: int = 20) -> list[dict[str, Any]]:
        """搜索帖子（竞品分析）"""
        logger.info(f"Searching posts for keyword: {keyword}")
        return []

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=10, max=120),
        retry=retry_if_exception_type((XHSRateLimitError, ConnectionError, TimeoutError)),
        reraise=True,
    )
    async def publish_post(self, post: XHSPost) -> dict[str, Any]:
        """发布帖子"""
        logger.info(f"Publishing post: {post.title}")
        # TODO: 实现真实发布逻辑
        return {"post_id": "", "status": "pending"}

    async def get_post_analytics(self, post_id: str) -> XHSAnalytics:
        """获取帖子数据分析"""
        logger.info(f"Fetching analytics for post: {post_id}")
        return XHSAnalytics(post_id=post_id)

    async def get_comments(self, post_id: str, limit: int = 20) -> list[XHSComment]:
        """获取帖子评论"""
        logger.info(f"Fetching comments for post: {post_id}")
        return []

    async def reply_to_comment(self, comment_id: str, reply: str) -> bool:
        """回复评论"""
        logger.info(f"Replying to comment: {comment_id}")
        return True

    async def get_direct_messages(self, limit: int = 20) -> list[XHSDirectMessage]:
        """获取私信"""
        logger.info("Fetching direct messages")
        return []

    async def send_dm(self, user_id: str, message: str) -> bool:
        """发送私信"""
        logger.info(f"Sending DM to user: {user_id}")
        return True

    async def monitor_keywords(self, keywords: list[str]) -> list[dict[str, Any]]:
        """关键词监控"""
        logger.info(f"Monitoring keywords: {keywords}")
        return []