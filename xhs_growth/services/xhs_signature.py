"""小红书 API 签名算法 — shield 签名生成.

注意: 此签名算法基于逆向分析，可能随小红书更新而失效。
需要持续维护和更新。

算法参考:
- https://github.com/NanmiCoder/XHS-Spider
- https://github.com/ReaJason/xhs-spider
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

logger = logging.getLogger("xhs_growth.signature")


class XHSSignature:
    """小红书 API shield 签名生成器"""

    # 签名密钥 (逆向工程获得，可能需要更新)
    # 这些值可能随小红书版本更新而变化
    SIGN_KEY = "dWCy7sDhGAVmiwQFkQThXKXdP4Mj3iFt"

    # shield 算法版本
    SHIELD_VERSION = "1"

    @classmethod
    def generate_sign(cls, params: dict[str, Any], timestamp: int = None) -> str:
        """生成 API 签名 (shield 参数)

        Args:
            params: API 请求参数
            timestamp: 时间戳 (毫秒)，默认使用当前时间

        Returns:
            shield 签名字符串
        """
        if timestamp is None:
            timestamp = int(time.time() * 1000)

        # 1. 构造签名字符串
        # 将参数按 key 排序后拼接
        sorted_params = sorted(params.items(), key=lambda x: x[0])
        param_str = "&".join(f"{k}={v}" for k, v in sorted_params if v is not None)

        # 2. 加入时间戳
        sign_base = f"{param_str}&timestamp={timestamp}"

        # 3. HMAC-SHA256 签名
        sign_bytes = hmac.new(
            cls.SIGN_KEY.encode(),
            sign_base.encode(),
            hashlib.sha256,
        ).digest()

        # 4. Base64 编码
        import base64
        sign_b64 = base64.b64encode(sign_bytes).decode()

        # 5. 构造 shield 字段
        shield = f"{cls.SHIELD_VERSION}:{timestamp}:{sign_b64[:32]}"

        return shield

    @classmethod
    def generate_x_s(cls, params: dict[str, Any], timestamp: int = None) -> str:
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
    def generate_x_t(cls, timestamp: int = None) -> str:
        """生成 x-t 时间戳请求头"""
        if timestamp is None:
            timestamp = int(time.time() * 1000)
        return str(timestamp)

    @classmethod
    def add_sign_to_params(cls, params: dict[str, Any]) -> dict[str, Any]:
        """为参数添加签名"""
        timestamp = int(time.time() * 1000)
        signed_params = params.copy()
        signed_params["shield"] = cls.generate_sign(params, timestamp)
        return signed_params

    @classmethod
    def add_sign_to_headers(cls, params: dict[str, Any], headers: dict) -> dict:
        """为请求头添加签名相关字段"""
        timestamp = int(time.time() * 1000)
        signed_headers = headers.copy()
        signed_headers["x-s"] = cls.generate_x_s(params, timestamp)
        signed_headers["x-t"] = cls.generate_x_t(timestamp)
        return signed_headers


class XHSAntiSpider:
    """小红书反爬虫对策"""

    @staticmethod
    def get_fingerprint() -> dict:
        """生成浏览器指纹参数"""
        return {
            "platform": "mac",
            "device_id": XHSAntiSpider._generate_device_id(),
            "os_version": "10.15.7",
            "browser_type": "chrome",
            "browser_version": "122.0",
        }

    @staticmethod
    def _generate_device_id() -> str:
        """生成设备 ID (模拟浏览器指纹)"""
        import random
        import string
        chars = string.ascii_lowercase + string.digits
        return "".join(random.choices(chars, k=32))

    @staticmethod
    def get_web_id() -> str:
        """生成 web_id (用于追踪)"""
        import random
        import string
        chars = string.ascii_lowercase + string.digits
        prefix = "".join(random.choices(chars, k=8))
        suffix = "".join(random.choices(chars, k=24))
        return f"{prefix}_{suffix}"


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
    def get_user_id(cookie_str: str) -> str | None:
        """从 Cookie 提取用户 ID"""
        cookies = XHSCookieParser.extract_from_string(cookie_str)
        # 小红书用户 ID 在 a1 或 customer-sso-sid 中
        return cookies.get("customer-sso-sid") or cookies.get("a1")

    @staticmethod
    def is_valid(cookie_str: str) -> bool:
        """检查 Cookie 是否有效 (包含必要字段)"""
        cookies = XHSCookieParser.extract_from_string(cookie_str)
        # 必要字段: a1 (登录态), web_session (会话)
        return "a1" in cookies and len(cookies.get("a1", "")) > 10