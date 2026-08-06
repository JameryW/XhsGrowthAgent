"""小红书 API 签名算法 — shield 签名生成.

注意: 此签名算法基于逆向分析，可能随小红书更新而失效。
需要持续维护和更新。

算法参考:
- https://github.com/NanmiCoder/XHS-Spider
- https://github.com/ReaJason/xhs-spider
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

logger = logging.getLogger("xhs_growth.signature")


class XHSSignature:
    """小红书 API shield 签名生成器"""

    @classmethod
    def generate_x_s(cls, params: dict[str, Any], timestamp: int | None = None) -> str:
        """生成 x-s 请求头 (小红书新版签名)

        算法: MD5(参数 + 时间戳 + 固定盐值)
        """
        if timestamp is None:
            timestamp = int(time.time() * 1000)

        # 构造签名字符串
        param_str = json.dumps(params, separators=(",", ":"), ensure_ascii=False)
        sign_str = f"{param_str}{timestamp}XHS_WEB"

        # MD5 计算
        sign_md5 = hashlib.md5(sign_str.encode()).hexdigest()

        return sign_md5

    @classmethod
    def generate_x_t(cls, timestamp: int | None = None) -> str:
        """生成 x-t 时间戳请求头"""
        if timestamp is None:
            timestamp = int(time.time() * 1000)
        return str(timestamp)

    @classmethod
    def add_sign_to_headers(cls, params: dict[str, Any], headers: dict[str, Any]) -> dict[str, Any]:
        """为请求头添加签名相关字段"""
        timestamp = int(time.time() * 1000)
        signed_headers = headers.copy()
        signed_headers["x-s"] = cls.generate_x_s(params, timestamp)
        signed_headers["x-t"] = cls.generate_x_t(timestamp)
        return signed_headers


# ── Cookie 解析工具 ─────────────────────────────────────────────────────────


class XHSCookieParser:
    """小红书 Cookie 解析工具"""

    @staticmethod
    def extract_from_string(cookie_str: str) -> dict[str, str]:
        """从 Cookie 字符串提取键值对"""
        cookies = {}
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
        # 必要字段: a1 (登录态), web_session (会话)
        return "a1" in cookies and len(cookies.get("a1", "")) > 10
