"""Xiaohongshu platform client — API + Playwright hybrid mode.

混合架构:
- HTTP API: 用于简单查询 (热门话题、搜索、获取评论)
- Playwright: 用于复杂操作 (发布、回复评论、私信)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from backend.services.xhs_api import XHSApiEndpoints, XHSApiHeaders, XHSApiParams
from backend.services.xhs_signature import XHSCookieParser, XHSSignature

if TYPE_CHECKING:
    from backend.services.xhs_engagement import XHSEngagement
    from backend.services.xhs_publisher import XHSPublisher

logger = logging.getLogger("xhs_growth.xhs_client")


# ── Exceptions ──────────────────────────────────────────────────────────────


class XHSRateLimitError(Exception):
    """请求频率限制"""

    pass


class XHSAuthError(Exception):
    """认证失败"""

    pass


class XHSPublishError(Exception):
    """发布失败"""

    pass


class XHSApiError(Exception):
    """API 请求失败"""

    pass


# ── Data Classes ────────────────────────────────────────────────────────────


@dataclass
class XHSPost:
    """小红书帖子"""

    title: str
    body: str
    hashtags: list[str] = field(default_factory=list)
    image_paths: list[str] = field(default_factory=list)
    category: str = ""
    location: str = ""
    is_private: bool = False
    scheduled_time: str = ""


@dataclass
class XHSAnalytics:
    """帖子数据分析"""

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
    """评论"""

    comment_id: str
    post_id: str
    user_name: str
    content: str
    user_id: str = ""
    like_count: int = 0
    created_at: str = ""
    is_reply: bool = False


@dataclass
class XHSDirectMessage:
    """私信"""

    message_id: str
    sender_id: str
    sender_name: str
    content: str
    timestamp: str = ""


@dataclass
class XHSTrendingTopic:
    """热门话题"""

    topic_id: str
    title: str
    heat_score: int
    growth_rate: float = 0.0
    related_keywords: list[str] = field(default_factory=list)
    category: str = ""


@dataclass
class XHSSearchResult:
    """搜索结果"""

    note_id: str
    title: str
    user_name: str
    user_id: str
    likes: int
    comments: int
    collects: int
    cover_url: str = ""
    note_url: str = ""


# ── HTTP API Client ─────────────────────────────────────────────────────────


class _HTTPClient:
    """小红书 HTTP API 客户端"""

    def __init__(self, cookie: str, timeout: float = 30.0):
        self.cookie = cookie
        self._http = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._http.aclose()

    async def _request(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        method: str = "GET",
    ) -> dict[str, Any]:
        """发送 API 请求"""
        url = XHSApiEndpoints.full_url(endpoint)
        headers = XHSApiHeaders.build(cookie=self.cookie)

        # 添加签名
        if params:
            headers = XHSSignature.add_sign_to_headers(params, headers)

        try:
            if method == "GET":
                response = await self._http.get(url, headers=headers, params=params or {})
            else:
                response = await self._http.post(url, headers=headers, json=params or {})

            # 检查响应
            if response.status_code == 429:
                raise XHSRateLimitError("请求频率限制")
            if response.status_code == 401:
                raise XHSAuthError("认证失败，Cookie 可能已过期")

            data = response.json()

            # 检查业务状态
            if not data.get("success"):
                error_msg = data.get("msg", "Unknown error")
                raise XHSApiError(f"API error: {error_msg}")

            return cast(dict[str, Any], data.get("data", {}))

        except httpx.TimeoutException as e:
            raise TimeoutError("API 请求超时") from e
        except httpx.RequestError as e:
            raise ConnectionError(f"网络错误: {e}") from e

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        retry=retry_if_exception_type((XHSRateLimitError, ConnectionError, TimeoutError)),
        reraise=True,
    )
    async def get_homefeed(self, category: str = "", cursor: str = "") -> list[dict[str, Any]]:
        """获取首页推荐 / 热门"""
        params = XHSApiParams.homefeed_params(cursor=cursor, category=category)
        data = await self._request(XHSApiEndpoints.HOMEFEED, params)
        return cast(list[dict[str, Any]], data.get("notes", []))

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        retry=retry_if_exception_type((XHSRateLimitError, ConnectionError, TimeoutError)),
    )
    async def search_notes(
        self, keyword: str, page: int = 1, sort: str = "general"
    ) -> list[dict[str, Any]]:
        """搜索笔记"""
        params = XHSApiParams.search_params(keyword=keyword, page=page, sort_type=sort)
        data = await self._request(XHSApiEndpoints.SEARCH_NOTE, params)
        return cast(list[dict[str, Any]], data.get("notes", []))

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        retry=retry_if_exception_type((XHSRateLimitError, ConnectionError, TimeoutError)),
    )
    async def get_comments(self, note_id: str, cursor: str = "") -> list[dict[str, Any]]:
        """获取评论列表"""
        params = XHSApiParams.comments_params(note_id=note_id, cursor=cursor)
        data = await self._request(XHSApiEndpoints.COMMENTS_LIST, params)
        return cast(list[dict[str, Any]], data.get("comments", []))

    async def get_note_detail(self, note_id: str) -> dict[str, Any]:
        """获取笔记详情"""
        params = {"note_id": note_id}
        return await self._request(XHSApiEndpoints.NOTE_DETAIL, params)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        retry=retry_if_exception_type((XHSRateLimitError, ConnectionError, TimeoutError)),
    )
    async def search_users(self, keyword: str, page: int = 1) -> list[dict[str, Any]]:
        """搜索用户"""
        params = XHSApiParams.search_users_params(keyword=keyword, page=page)
        data = await self._request(XHSApiEndpoints.SEARCH_USER, params)
        return cast(list[dict[str, Any]], data.get("users", []))

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        retry=retry_if_exception_type((XHSRateLimitError, ConnectionError, TimeoutError)),
    )
    async def get_user_info(self, user_id: str) -> dict[str, Any]:
        """获取用户信息"""
        params = XHSApiParams.user_info_params(user_id=user_id)
        return await self._request(XHSApiEndpoints.USER_INFO, params)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        retry=retry_if_exception_type((XHSRateLimitError, ConnectionError, TimeoutError)),
    )
    async def get_user_notes(self, user_id: str, cursor: str = "") -> dict[str, Any]:
        """获取用户笔记列表"""
        params = XHSApiParams.user_notes_params(user_id=user_id, cursor=cursor)
        return await self._request(XHSApiEndpoints.USER_NOTES, params)


# ── Main XHSClient ───────────────────────────────────────────────────────────


class XHSClient:
    """小红书平台交互客户端，混合架构"""

    def __init__(
        self,
        cookie: str = "",
        user_id: str = "",
        use_browser: bool = False,
        headless: bool = False,
        cdp_endpoint: str = "",
        account_id: str = "",
    ):
        self.cookie = cookie
        self.user_id = user_id
        self.use_browser = use_browser
        # Kept for compatibility with older callers; XHS browser services are
        # always headed and ignore this legacy switch.
        self.headless = False
        self.cdp_endpoint = cdp_endpoint
        self.account_id = (account_id or "").strip()

        # HTTP API 客户端
        self._http = _HTTPClient(cookie=cookie) if cookie else None

        # Playwright 客户端 (懒加载)
        self._publisher: XHSPublisher | None = None
        self._engagement: XHSEngagement | None = None

        # Cookie 验证
        self._cookie_valid = XHSCookieParser.is_valid(cookie) if cookie else False

    async def close(self) -> None:
        """关闭所有连接"""
        if self._http:
            await self._http.close()
        if self._publisher:
            await self._publisher.close()
        if self._engagement:
            await self._engagement.close()

    # ── HTTP API 方法 (简单查询) ─────────────────────────────────────────────

    async def get_trending(self, category: str = "") -> list[XHSTrendingTopic]:
        """获取热门话题 (HTTP API)"""
        if not self._http:
            logger.warning("未配置 Cookie，无法获取热门话题")
            return []

        logger.info(f"Fetching trending topics for category: {category}")

        try:
            notes = await self._http.get_homefeed(category=category)

            # 解析为 XHSTrendingTopic
            topics = []
            for note in notes[:20]:  # 取前 20 个
                topics.append(
                    XHSTrendingTopic(
                        topic_id=note.get("note_id", ""),
                        title=note.get("display_title", ""),
                        heat_score=note.get("like_count", 0),
                        growth_rate=0.0,
                        related_keywords=note.get("tag_list", []),
                        category=category,
                    )
                )

            return topics

        except Exception as e:
            logger.error(f"获取热门话题失败: {type(e).__name__}: {e}")
            return []

    async def search_posts(self, keyword: str, limit: int = 20) -> list[XHSSearchResult]:
        """搜索帖子 (HTTP API)"""
        if not self._http:
            logger.warning("未配置 Cookie，无法搜索")
            return []

        logger.info(f"Searching posts for keyword: {keyword}")

        try:
            notes = await self._http.search_notes(keyword=keyword)

            results = []
            for note in notes[:limit]:
                note_id = note.get("id", note.get("note_id", ""))
                results.append(
                    XHSSearchResult(
                        note_id=note_id,
                        title=note.get("display_title", ""),
                        user_name=note.get("user", {}).get("nickname", ""),
                        user_id=note.get("user", {}).get("user_id", ""),
                        likes=note.get("like_count", 0),
                        comments=note.get("comment_count", 0),
                        collects=note.get("collect_count", 0),
                        cover_url=note.get("cover", {}).get("url", ""),
                        note_url=f"https://www.xiaohongshu.com/explore/{note_id}",
                    )
                )

            return results

        except Exception as e:
            logger.error(f"搜索帖子失败: {type(e).__name__}: {e}")
            return []

    async def get_comments(self, post_id: str, limit: int = 20) -> list[XHSComment]:
        """获取帖子评论 (HTTP API)"""
        if not self._http:
            return []

        logger.info(f"Fetching comments for post: {post_id}")

        try:
            comments_data = await self._http.get_comments(note_id=post_id)

            comments = []
            for item in comments_data[:limit]:
                comments.append(
                    XHSComment(
                        comment_id=item.get("id", ""),
                        post_id=post_id,
                        user_name=item.get("user", {}).get("nickname", ""),
                        user_id=item.get("user", {}).get("user_id", ""),
                        content=item.get("content", ""),
                        like_count=item.get("like_count", 0),
                        created_at=item.get("create_time", ""),
                        is_reply=item.get("target_comment", {}).get("id", ""),
                    )
                )

            return comments

        except Exception as e:
            logger.error(f"获取评论失败: {type(e).__name__}: {e}")
            return []

    async def get_post_analytics(self, post_id: str) -> XHSAnalytics:
        """获取帖子数据分析"""
        logger.info(f"Fetching analytics for post: {post_id}")

        # TODO: 需要从创作者中心获取数据，目前返回基础信息
        try:
            if self._http:
                detail = await self._http.get_note_detail(note_id=post_id)
                return XHSAnalytics(
                    post_id=post_id,
                    views=detail.get("view_count", 0),
                    likes=detail.get("like_count", 0),
                    collects=detail.get("collect_count", 0),
                    comments=detail.get("comment_count", 0),
                    shares=detail.get("share_count", 0),
                    engagement_rate=detail.get("engagement_rate", 0.0),
                    fetched_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                )
        except Exception as e:
            logger.warning(f"获取分析数据失败: {e}")

        return XHSAnalytics(post_id=post_id)

    async def monitor_keywords(self, keywords: list[str]) -> list[dict[str, Any]]:
        """关键词监控"""
        logger.info(f"Monitoring keywords: {keywords}")

        results = []
        for keyword in keywords:
            try:
                posts = await self.search_posts(keyword=keyword, limit=10)
                total_likes = sum(p.likes for p in posts)
                results.append(
                    {
                        "keyword": keyword,
                        "post_count": len(posts),
                        "total_likes": total_likes,
                        "avg_likes": total_likes / len(posts) if posts else 0,
                        "top_posts": posts[:3],
                    }
                )
            except Exception as e:
                logger.warning(f"关键词 {keyword} 监控失败: {e}")

        return results

    # ── 博主搜索方法 ──────────────────────────────────────────────────────

    async def search_users(self, keyword: str, limit: int = 20) -> list[dict[str, Any]]:
        """搜索博主 (HTTP API)"""
        if not self._http:
            logger.warning("未配置 Cookie，无法搜索用户")
            return []

        logger.info(f"Searching users for keyword: {keyword}")

        try:
            users = await self._http.search_users(keyword=keyword)
            return users[:limit]
        except Exception as e:
            logger.error(f"搜索用户失败: {type(e).__name__}: {e}")
            return []

    async def get_user_info(self, user_id: str) -> dict[str, Any]:
        """获取博主信息 (HTTP API)"""
        if not self._http:
            logger.warning("未配置 Cookie，无法获取用户信息")
            return {}

        logger.info(f"Fetching user info for: {user_id}")

        try:
            return await self._http.get_user_info(user_id=user_id)
        except Exception as e:
            logger.error(f"获取用户信息失败: {type(e).__name__}: {e}")
            return {}

    async def get_user_notes(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """获取博主笔记列表 (HTTP API, 自动翻页)"""
        if not self._http:
            logger.warning("未配置 Cookie，无法获取用户笔记")
            return []

        logger.info(f"Fetching notes for user: {user_id}, limit: {limit}")

        try:
            all_notes: list[dict[str, Any]] = []
            cursor = ""
            while len(all_notes) < limit:
                data = await self._http.get_user_notes(user_id=user_id, cursor=cursor)
                notes = data.get("notes", [])
                if not notes:
                    break
                all_notes.extend(notes)
                cursor = data.get("cursor", "")
                has_more = data.get("has_more", False)
                if not has_more:
                    break
            return all_notes[:limit]
        except Exception as e:
            logger.error(f"获取用户笔记失败: {type(e).__name__}: {e}")
            return []

    # ── Playwright 方法 (复杂操作) ───────────────────────────────────────────

    async def _ensure_publisher(self) -> XHSPublisher | None:
        """确保发布器已初始化"""
        if self._publisher is None and self.use_browser:
            from backend.services.xhs_publisher import XHSPublisher

            self._publisher = XHSPublisher(
                cookie=self.cookie,
                headless=False,
                cdp_endpoint=self.cdp_endpoint,
            )
        return self._publisher

    async def _ensure_engagement(self) -> XHSEngagement | None:
        """确保互动器已初始化"""
        if self._engagement is None and self.use_browser:
            from backend.services.xhs_engagement import XHSEngagement

            cdp_endpoint = self.cdp_endpoint.strip()
            if not cdp_endpoint and self.account_id:
                try:
                    from backend.db.accounts import get_account_cdp_endpoint

                    cdp_endpoint = (await get_account_cdp_endpoint(self.account_id)).strip()
                except Exception as exc:
                    logger.warning("无法解析账号 %s 的互动 CDP endpoint: %s", self.account_id, exc)
            if not cdp_endpoint:
                logger.warning(
                    "互动已闭环：账号 %s 没有持久 CDP endpoint",
                    self.account_id or "unknown",
                )
            self._engagement = XHSEngagement(
                cookie=self.cookie,
                headless=False,
                cdp_endpoint=cdp_endpoint,
                account_id=self.account_id,
            )
        return self._engagement

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=10, max=120),
        reraise=True,
    )
    async def publish_post(self, post: XHSPost) -> dict[str, Any]:
        """发布帖子 (Playwright)"""
        logger.info(f"Publishing post: {post.title}")

        if not self.use_browser:
            logger.warning("use_browser=False，无法发布帖子")
            return {"post_id": "", "status": "disabled"}

        publisher = await self._ensure_publisher()
        if not publisher:
            return {"post_id": "", "status": "error", "error": "无法初始化发布器"}

        result = await publisher.publish_note(
            title=post.title,
            body=post.body,
            image_paths=post.image_paths,
            hashtags=post.hashtags,
            category=post.category,
            location=post.location,
            scheduled_time=post.scheduled_time,
            is_private=post.is_private,
        )

        return result

    async def reply_to_comment(self, comment_id: str, post_id: str, reply: str) -> bool:
        """回复评论 (Playwright)"""
        logger.info(f"Replying to comment: {comment_id}")

        if not self.use_browser:
            return False

        engagement = await self._ensure_engagement()
        if not engagement:
            return False

        result = await engagement.reply_to_comment(
            note_id=post_id,
            comment_id=comment_id,
            reply_content=reply,
        )

        return cast(bool, result.get("success", False))

    async def get_direct_messages(self, limit: int = 20) -> list[XHSDirectMessage]:
        """获取私信 (Playwright)"""
        logger.info("Fetching direct messages")

        if not self.use_browser:
            return []

        engagement = await self._ensure_engagement()
        if not engagement:
            return []

        unread = await engagement.get_unread_messages()

        messages = []
        for msg in unread[:limit]:
            messages.append(
                XHSDirectMessage(
                    message_id=f"dm_{int(time.time())}",
                    sender_id=msg.get("sender_id", ""),
                    sender_name=msg.get("sender_name", ""),
                    content=msg.get("preview", ""),
                    timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
                )
            )

        return messages

    async def send_dm(self, user_id: str, message: str) -> bool:
        """发送私信 (Playwright)"""
        logger.info(f"Sending DM to user: {user_id}")

        if not self.use_browser:
            return False

        engagement = await self._ensure_engagement()
        if not engagement:
            return False

        result = await engagement.send_dm(
            target_user_id=user_id,
            message=message,
        )

        return cast(bool, result.get("success", False))
