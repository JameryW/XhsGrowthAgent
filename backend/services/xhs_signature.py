"""Xiaohongshu cookie parsing helpers.

Fake HTTP request signing (`XHSSignature`) was removed: reverse-engineered MD5
shield headers are unreliable and unsafe. Callers that previously depended on
signed HTTP must fail closed with ``signature_unavailable`` instead of silent
empty success. Cookie validation for CDP/browser paths remains here.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("xhs_growth.signature")


class XHSCookieParser:
    """小红书 Cookie 解析工具"""

    @staticmethod
    def extract_from_string(cookie_str: str) -> dict[str, str]:
        """从 Cookie 字符串提取键值对"""
        cookies: dict[str, str] = {}
        for item in cookie_str.split(";"):
            item = item.strip()
            if "=" in item:
                key, value = item.split("=", 1)
                cookies[key.strip()] = value.strip()
        return cookies

    @staticmethod
    def is_valid(cookie_str: str) -> bool:
        """检查 Cookie 是否有效 (包含必要字段)"""
        cookies = XHSCookieParser.extract_from_string(cookie_str)
        # 必要字段: a1 (登录态)
        return "a1" in cookies and len(cookies.get("a1", "")) > 10


__all__ = ["XHSCookieParser"]
