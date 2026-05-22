"""服务模块 — 外部平台客户端.

Components:
- xhs_client: 小红书平台交互客户端
"""

from xhs_growth.services.xhs_client import (
    XHSClient,
    XHSPost,
    XHSAnalytics,
    XHSComment,
    XHSDirectMessage,
    XHSRateLimitError,
    XHSAuthError,
    XHSPublishError,
)

__all__ = [
    "XHSClient",
    "XHSPost",
    "XHSAnalytics",
    "XHSComment",
    "XHSDirectMessage",
    "XHSRateLimitError",
    "XHSAuthError",
    "XHSPublishError",
]