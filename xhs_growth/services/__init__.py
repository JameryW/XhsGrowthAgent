"""服务模块 — 外部平台客户端.

Components:
- xhs_client: 小红书平台交互客户端 (混合架构)
- xhs_api: HTTP API endpoints 定义
- xhs_signature: API 签名算法
- xhs_publisher: Playwright 发布器
- xhs_engagement: Playwright 互动器
"""

from xhs_growth.services.xhs_client import (
    XHSClient,
    XHSPost,
    XHSAnalytics,
    XHSComment,
    XHSDirectMessage,
    XHSTrendingTopic,
    XHSSearchResult,
    XHSRateLimitError,
    XHSAuthError,
    XHSPublishError,
    XHSApiError,
)
from xhs_growth.services.xhs_api import XHSApiEndpoints, XHSApiHeaders, XHSApiParams
from xhs_growth.services.xhs_signature import XHSSignature, XHSCookieParser
from xhs_growth.services.xhs_publisher import XHSPublisher
from xhs_growth.services.xhs_engagement import XHSEngagement

__all__ = [
    # Main client
    "XHSClient",
    "XHSPost",
    "XHSAnalytics",
    "XHSComment",
    "XHSDirectMessage",
    "XHSTrendingTopic",
    "XHSSearchResult",
    # Exceptions
    "XHSRateLimitError",
    "XHSAuthError",
    "XHSPublishError",
    "XHSApiError",
    # API components
    "XHSApiEndpoints",
    "XHSApiHeaders",
    "XHSApiParams",
    "XHSSignature",
    "XHSCookieParser",
    # Playwright components
    "XHSPublisher",
    "XHSEngagement",
]