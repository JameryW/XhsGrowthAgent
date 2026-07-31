"""小红书持久 CDP 互动器 — 评论回复与私信处理.

互动必须复用账号已经登录的 headed Chrome。这里不启动新的浏览器、不创建
临时 context，也不注入 Cookie；没有账号 CDP 时直接闭环失败。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from playwright.async_api import Browser, Page

logger = logging.getLogger("xhs_growth.engagement")

_T = TypeVar("_T")


class EngagementConfigurationError(RuntimeError):
    """Raised when engagement has no persistent account browser to attach to."""


class EngagementRiskError(RuntimeError):
    """Raised when the attached page shows a login or risk-control surface."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass
class _EngagementGuard:
    lock: asyncio.Lock
    last_action_at: float = 0.0


_ENGAGEMENT_GUARDS: dict[str, _EngagementGuard] = {}


class XHSEngagement:
    """通过账号持久 CDP Chrome 执行低频互动操作。"""

    NOTE_URL_TEMPLATE = "https://www.xiaohongshu.com/explore/{note_id}"
    DM_URL = "https://www.xiaohongshu.com/message"
    _RISK_MARKERS = (
        "风险控制",
        "安全验证",
        "人机验证",
        "滑块验证",
        "操作频繁",
        "访问受限",
        "异常访问",
        "captcha",
        "verify you are human",
    )
    _LOGIN_MARKERS = (
        "请先登录",
        "扫码登录",
        "短信登录",
        "手机号登录",
        "登录后继续",
        "登录即同意",
    )

    def __init__(
        self,
        cookie: str = "",
        headless: bool = False,
        slow_mo: int = 100,
        *,
        cdp_endpoint: str = "",
        account_id: str = "",
        cooldown_seconds: float | None = None,
    ) -> None:
        # Kept for source compatibility with older callers. Cookies/headless are
        # deliberately not used by the persistent-CDP implementation.
        self.cookie = cookie
        # Kept for source compatibility; persistent CDP is always headed.
        self.headless = False
        self.slow_mo = slow_mo
        self.cdp_endpoint = (cdp_endpoint or "").strip()
        self.account_id = (account_id or "").strip()
        if cooldown_seconds is None:
            try:
                cooldown_seconds = float(
                    os.environ.get("XHS_ENGAGEMENT_COOLDOWN_SECONDS", "5") or 5
                )
            except (TypeError, ValueError, OverflowError):
                cooldown_seconds = 5.0
        self.cooldown_seconds = max(0.0, cooldown_seconds)
        self._browser: Browser | None = None
        self._page: Page | None = None
        self._owns_page = False
        self._playwright: Any = None
        self._guard = self._get_guard()

    def _get_guard(self) -> _EngagementGuard:
        key = self.account_id or self.cdp_endpoint
        if not key:
            # All no-CDP instances share a guard, but fail before any browser
            # operation. This keeps accidental callers deterministic in tests.
            key = "missing-cdp"
        guard = _ENGAGEMENT_GUARDS.get(key)
        if guard is None:
            guard = _EngagementGuard(lock=asyncio.Lock())
            _ENGAGEMENT_GUARDS[key] = guard
        return guard

    async def _ensure_browser(self) -> Browser:
        """Attach to the account's already-running persistent Chrome only."""
        if not self.cdp_endpoint:
            raise EngagementConfigurationError(
                "engagement requires an account cdp_endpoint; refusing to launch a browser"
            )
        if self._browser is not None:
            return self._browser

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise EngagementConfigurationError(
                "playwright is not installed; install the browser extra"
            ) from exc

        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(self.cdp_endpoint)
        except Exception as exc:
            await self._stop_playwright()
            raise EngagementConfigurationError(
                f"unable to connect to account Chrome CDP {self.cdp_endpoint}: {exc}"
            ) from exc
        return self._browser

    async def _ensure_page(self) -> Page:
        """Reuse an existing account tab, or open one in the existing context."""
        if self._page is not None:
            return self._page
        browser = await self._ensure_browser()
        contexts = browser.contexts
        if not contexts:
            raise EngagementConfigurationError(
                "account Chrome CDP has no browser context; refusing to create one"
            )
        context = contexts[0]
        pages = list(context.pages)
        if pages:
            self._page = next(
                (page for page in pages if "xiaohongshu.com" in str(getattr(page, "url", ""))),
                pages[0],
            )
        else:
            # A new tab in the persistent context is allowed; new_context is not.
            self._page = await context.new_page()
            self._owns_page = True
        return self._page

    async def _page_signal(self, page: Page) -> tuple[str, str] | None:
        url = str(getattr(page, "url", "") or "").lower()
        if "/login" in url or "passport" in url:
            return "login_required", "attached Chrome is showing a login page"

        try:
            body = await page.evaluate("() => (document.body && document.body.innerText) || ''")
        except Exception:
            body = ""
        text = str(body or "").lower()
        if any(marker.lower() in text for marker in self._RISK_MARKERS):
            return "risk_control", "attached page shows a platform risk-control challenge"
        login_hits = sum(marker.lower() in text for marker in self._LOGIN_MARKERS)
        if login_hits >= 2:
            return "login_required", "attached page shows a login shell"
        return None

    async def _assert_safe_page(self, page: Page) -> None:
        signal = await self._page_signal(page)
        if signal is not None:
            raise EngagementRiskError(*signal)

    async def _paced(self, operation: Callable[[], Awaitable[_T]]) -> _T:
        """Enforce one fixed cooldown before every browser action."""
        elapsed = asyncio.get_running_loop().time() - self._guard.last_action_at
        wait_seconds = self.cooldown_seconds - elapsed
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
        result = await operation()
        self._guard.last_action_at = asyncio.get_running_loop().time()
        return result

    @staticmethod
    def _blocked_result(error_code: str, message: str) -> dict[str, Any]:
        return {
            "success": False,
            "status": "blocked",
            "error_code": error_code,
            "error": message,
        }

    async def _hold_cdp(self):
        """Shared CDP lock so stats/publish/engagement never attach together."""
        from backend.services.cdp_session_lock import hold_cdp_session

        timeout = 120.0
        try:
            timeout = float(os.environ.get("XHS_CDP_ENGAGEMENT_LOCK_TIMEOUT_S", "120") or 120)
        except (TypeError, ValueError, OverflowError):
            timeout = 120.0
        return hold_cdp_session(
            account_id=self.account_id,
            cdp_endpoint=self.cdp_endpoint,
            owner="engagement",
            wait=True,
            timeout=timeout,
        )

    async def reply_to_comment(
        self,
        note_id: str,
        comment_id: str,
        reply_content: str,
    ) -> dict[str, Any]:
        """回复评论；遇到登录/风控页面后立即停止且不重试。"""
        from backend.services.cdp_session_lock import CdpSessionBusyError

        try:
            async with await self._hold_cdp():
                async with self._guard.lock:
                    return await self._reply_to_comment_locked(
                        note_id, comment_id, reply_content
                    )
        except CdpSessionBusyError as exc:
            return self._blocked_result(
                "cdp_busy", f"CDP session busy (held by {exc.holder})"
            )

    async def _reply_to_comment_locked(
        self,
        note_id: str,
        comment_id: str,
        reply_content: str,
    ) -> dict[str, Any]:
            try:
                page = await self._ensure_page()
                await self._assert_safe_page(page)
                note_url = self.NOTE_URL_TEMPLATE.format(note_id=note_id)
                await self._paced(lambda: page.goto(note_url, wait_until="domcontentloaded"))
                await self._assert_safe_page(page)

                comment_selector = f".comment-item[data-id='{comment_id}'], .comment-wrapper"
                await page.wait_for_selector(comment_selector, timeout=10000)
                comment_element = await page.query_selector(comment_selector)
                if comment_element is None:
                    return {"success": False, "error": "未找到目标评论"}
                await self._assert_safe_page(page)
                reply_btn = await comment_element.query_selector("text=回复, .reply-btn")
                if reply_btn:
                    await self._paced(reply_btn.click)
                    await self._assert_safe_page(page)

                reply_input = await page.query_selector(
                    "textarea[placeholder*=回复], .reply-input, input.reply-input"
                )
                if reply_input is None:
                    return {"success": False, "error": "无法找到回复输入框"}
                await self._paced(lambda: reply_input.fill(reply_content))
                send_btn = await page.query_selector("text=发送, button.send-btn")
                if send_btn:
                    await self._paced(send_btn.click)
                    await self._assert_safe_page(page)
                await page.wait_for_function(
                    """
                    const replies = document.querySelectorAll('.reply-item');
                    return replies.length > 0;
                    """,
                    timeout=5000,
                )
                return {"success": True, "reply_id": f"reply_{int(time.time())}"}
            except EngagementRiskError as exc:
                logger.warning(
                    "engagement stopped without retry account=%s code=%s: %s",
                    self.account_id or "unknown",
                    exc.error_code,
                    exc,
                )
                return self._blocked_result(exc.error_code, str(exc))
            except EngagementConfigurationError as exc:
                logger.warning("engagement unavailable: %s", exc)
                return self._blocked_result("configuration", str(exc))
            except Exception as exc:
                logger.error("回复评论失败: %s", exc, exc_info=True)
                return {"success": False, "status": "failed", "error": str(exc)}

    async def send_dm(self, target_user_id: str, message: str) -> dict[str, Any]:
        """发送私信；遇到登录/风控页面后立即停止且不重试。"""
        from backend.services.cdp_session_lock import CdpSessionBusyError

        try:
            async with await self._hold_cdp():
                async with self._guard.lock:
                    try:
                        page = await self._ensure_page()
                        await self._assert_safe_page(page)
                        await self._paced(
                            lambda: page.goto(self.DM_URL, wait_until="domcontentloaded")
                        )
                        await self._assert_safe_page(page)

                        new_dm_btn = await page.query_selector("text=新建私信, .new-dm-btn")
                        if new_dm_btn:
                            await self._paced(new_dm_btn.click)
                            await self._assert_safe_page(page)
                        search_input = await page.query_selector(
                            "input[placeholder*=搜索], .dm-search-input"
                        )
                        if search_input:
                            await self._paced(lambda: search_input.fill(target_user_id))
                            user_result = await page.query_selector(
                                f".user-item[data-id='{target_user_id}'], .search-result-item"
                            )
                            if user_result:
                                await self._paced(user_result.click)
                                await self._assert_safe_page(page)

                        dm_input = await page.query_selector(
                            "textarea[placeholder*=输入], .dm-input"
                        )
                        if dm_input is None:
                            return {"success": False, "error": "无法找到私信输入框"}
                        await self._paced(lambda: dm_input.fill(message))
                        send_btn = await page.query_selector("text=发送, button.send-btn")
                        if send_btn:
                            await self._paced(send_btn.click)
                            await self._assert_safe_page(page)
                        return {"success": True, "message_id": f"dm_{int(time.time())}"}
                    except EngagementRiskError as exc:
                        logger.warning(
                            "engagement stopped without retry account=%s code=%s: %s",
                            self.account_id or "unknown",
                            exc.error_code,
                            exc,
                        )
                        return self._blocked_result(exc.error_code, str(exc))
                    except EngagementConfigurationError as exc:
                        logger.warning("engagement unavailable: %s", exc)
                        return self._blocked_result("configuration", str(exc))
                    except Exception as exc:
                        logger.error("发送私信失败: %s", exc, exc_info=True)
                        return {"success": False, "status": "failed", "error": str(exc)}
        except CdpSessionBusyError as exc:
            return self._blocked_result(
                "cdp_busy", f"CDP session busy (held by {exc.holder})"
            )

    async def get_unread_messages(self) -> list[dict[str, Any]]:
        """获取未读私信列表；登录/风控页面返回空结果并停止。"""
        from backend.services.cdp_session_lock import CdpSessionBusyError

        try:
            async with await self._hold_cdp():
                async with self._guard.lock:
                    try:
                        page = await self._ensure_page()
                        await self._assert_safe_page(page)
                        await self._paced(
                            lambda: page.goto(self.DM_URL, wait_until="domcontentloaded")
                        )
                        await self._assert_safe_page(page)
                        unread_items = await page.query_selector_all(
                            ".message-item.unread, .unread-badge"
                        )
                        messages = []
                        for item in unread_items:
                            sender = await item.query_selector(".sender-name")
                            content = await item.query_selector(".message-preview")
                            if sender and content:
                                messages.append(
                                    {
                                        "sender_name": await sender.inner_text(),
                                        "preview": await content.inner_text(),
                                        "is_unread": True,
                                    }
                                )
                        return messages
                    except (EngagementRiskError, EngagementConfigurationError) as exc:
                        logger.warning("message read stopped: %s", exc)
                        return []
                    except Exception as exc:
                        logger.error("获取未读消息失败: %s", exc, exc_info=True)
                        return []
        except CdpSessionBusyError:
            return []

    async def _stop_playwright(self) -> None:
        if self._playwright is not None:
            stop = getattr(self._playwright, "stop", None)
            if stop is not None:
                await stop()
            self._playwright = None

    async def close(self) -> None:
        """断开 Playwright，绝不关闭账号的持久 Chrome。"""
        if self._owns_page and self._page is not None:
            with_context = getattr(self._page, "close", None)
            if with_context is not None:
                await with_context()
        self._page = None
        self._owns_page = False
        self._browser = None
        await self._stop_playwright()

    async def __aenter__(self) -> XHSEngagement:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()
