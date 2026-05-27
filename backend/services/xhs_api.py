"""小红书 HTTP API endpoints — 逆向工程接口定义.

注意: 小红书 API 可能随时更新，此模块需要持续维护。
参考开源项目: https://github.com/NanmiCoder/XHS-Spider
"""

from __future__ import annotations


class XHSApiEndpoints:
    """小红书 Web API endpoints (逆向工程)"""

    # 基础 URL
    BASE_URL = "https://edith.xiaohongshu.com"
    CREATOR_URL = "https://creator.xiaohongshu.com"

    # ── 发现页 / 热门 ────────────────────────────────────────────────────────

    # 首页推荐 feed
    HOMEFEED = "/api/sns/web/v1/homefeed"

    # 分类热门
    CATEGORY_FEED = "/api/sns/web/v2/category/feed"

    # 热门话题榜
    HOT_TOPIC = "/api/sns/web/v1/hot/topic"

    # ── 搜索 ─────────────────────────────────────────────────────────────────

    # 搜索笔记
    SEARCH_NOTE = "/api/sns/web/v1/search/notes"

    # 搜索用户
    SEARCH_USER = "/api/sns/web/v1/search/user"

    # ── 笔记 ─────────────────────────────────────────────────────────────────

    # 笔记详情
    NOTE_DETAIL = "/api/sns/web/v1/note/detail"

    # 笔记统计数据
    NOTE_STATISTICS = "/api/sns/web/v2/note/statistics"

    # ── 评论 ─────────────────────────────────────────────────────────────────

    # 评论列表
    COMMENTS_LIST = "/api/sns/web/v2/comment/page"

    # 评论回复列表
    COMMENTS_SUB = "/api/sns/web/v2/comment/sub/page"

    # ── 用户 ─────────────────────────────────────────────────────────────────

    # 用户信息
    USER_INFO = "/api/sns/web/v1/user/info"

    # 用户笔记列表
    USER_NOTES = "/api/sns/web/v1/user/posted"

    # ── 私信 ─────────────────────────────────────────────────────────────────

    # 私信列表 (需要 Playwright，API 不稳定)
    DM_LIST = "/api/sns/web/v1/im/session/list"

    @classmethod
    def full_url(cls, endpoint: str, base: str = None) -> str:
        """构建完整 URL"""
        return f"{base or cls.BASE_URL}{endpoint}"


class XHSApiHeaders:
    """小红书 API 请求头构造"""

    # 标准请求头模板
    DEFAULT_HEADERS = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Origin": "https://www.xiaohongshu.com",
        "Pragma": "no-cache",
        "Referer": "https://www.xiaohongshu.com/",
        "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"macOS"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    }

    @classmethod
    def build(cls, cookie: str = "", extra: dict = None) -> dict:
        """构建请求头"""
        headers = cls.DEFAULT_HEADERS.copy()
        if cookie:
            headers["Cookie"] = cookie
        if extra:
            headers.update(extra)
        return headers


class XHSApiParams:
    """小红书 API 常用参数"""

    @staticmethod
    def homefeed_params(cursor: str = "", category: str = "") -> dict:
        """首页推荐参数"""
        return {
            "cursor": cursor,
            "num": 40,
            "refresh_type": 1,
            "note_index": 0,
            "sort_type": 0 if category else 1,
            "need_title_cover": 1,
            "search_channel_id": category,
        }

    @staticmethod
    def search_params(keyword: str, page: int = 1, sort_type: str = "general") -> dict:
        """搜索参数"""
        return {
            "keyword": keyword,
            "page": page,
            "page_size": 20,
            "sort": sort_type,  # general, time_descending, hot_descending
            "note_type": 0,  # 0=全部
        }

    @staticmethod
    def comments_params(note_id: str, cursor: str = "") -> dict:
        """评论参数"""
        return {
            "note_id": note_id,
            "cursor": cursor,
            "num": 20,
            "image_scenes": "CRD,CRD_DT",
        }