"""小红书持久 CDP 互动器 — 评论回复与私信处理.

互动必须复用账号已经登录的 headed Chrome。这里不启动新的浏览器、不创建
临时 context，也不注入 Cookie；没有账号 CDP 时直接闭环失败。
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Any, TypeVar, cast

if TYPE_CHECKING:
    from playwright.async_api import Browser, Page

logger = logging.getLogger("xhs_growth.engagement")

_T = TypeVar("_T")

# Outcome vocabulary. Four words, and the difference between the last two is the
# whole point: ``failed`` means the effect certainly did not happen, ``unknown``
# means it may have. Reporting the second as the first is how a duplicate reply
# gets sent to a real person.
SENT = "sent"
BLOCKED = "blocked"
FAILED = "failed"
UNKNOWN = "unknown"

# Codes whose cause is a *moment* rather than a *state*: the same call can
# succeed shortly after. Everything else — quota, target not allowed, risk
# control, misconfiguration — and every code this module has never seen is
# terminal for automation. Defaulting the unknown ones to "do not retry" is
# deliberate: retrying a write you cannot explain spends the account's quota and
# can reach a real person twice.
_TRANSIENT_ERROR_CODES = frozenset(
    {
        "cdp_busy",
        "browser_action_cooldown",
        "engagement_cooldown",
    }
)

# Statuses that count against the daily quota. ``unknown`` is included on
# purpose: a possible send has to be treated as a send, or the ceiling stops
# bounding anything — the operator cannot un-send it to stay under the limit.
_QUOTA_STATUSES = frozenset({SENT, UNKNOWN})


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
    def _blocked_result(
        error_code: str, message: str, *, correlation_id: str = ""
    ) -> dict[str, Any]:
        return XHSEngagement._result(
            BLOCKED, error_code=error_code, error=message, correlation_id=correlation_id
        )

    @staticmethod
    def _result(
        status: str,
        *,
        error_code: str = "",
        error: str = "",
        receipt_id: str = "",
        correlation_id: str = "",
        verified: bool = False,
    ) -> dict[str, Any]:
        """One shape for every engagement outcome, so callers stop guessing.

        Four fields carry meaning and the rest exist so no caller has to tell
        "absent" from "unknown":

        * ``success`` is True only when the submit is believed to have landed --
          not when it *might* have. ``unknown`` is therefore not success, even
          though it is also not a failure the caller may retry.
        * ``receipt_id`` is the platform's own id and **only** the platform's.
          This module used to mint ``reply_<timestamp>`` / ``dm_<timestamp>``
          and hand it out as ``reply_id``: a clock reading that every other
          fabrication collides with, wearing the name of a receipt. When the
          platform echoed nothing the honest answer is ``""`` with
          ``receipt_source="none"``.
        * ``verified`` says whether the platform's own surface confirmed the
          effect. A DM cannot be confirmed today (no read-back is attempted), so
          it reports ``sent`` with ``verified=False`` rather than pretending the
          click was proof.
        * ``retryable`` is derived here, once, from the error code -- see
          ``_TRANSIENT_ERROR_CODES`` for why the default is *no*.
        """
        return {
            "success": status == SENT,
            "status": status,
            "error_code": error_code,
            "error": error,
            "receipt_id": receipt_id,
            "receipt_source": "platform" if receipt_id else "none",
            "correlation_id": correlation_id,
            "verified": verified,
            "retryable": status != SENT and error_code in _TRANSIENT_ERROR_CODES,
        }

    @staticmethod
    def _correlation_id(kind: str) -> str:
        """A local handle for logs — explicitly *not* a receipt (see ``_result``)."""
        return f"{kind}-{secrets.token_hex(4)}"

    async def _hold_cdp(self) -> _EngagementCdpHold:
        """Shared CDP lock so stats/publish/engagement never attach together."""
        from backend.services.cdp_session_lock import hold_cdp_session
        from backend.services.xhs_risk_gate import (
            check_engagement_allowed,
        )

        block = check_engagement_allowed(self.account_id, cdp_endpoint=self.cdp_endpoint)
        if block is not None:
            # Sleep out account-level engagement cool-down when possible.
            wait_s = max(0, int(block.retry_after_seconds or 0))
            if wait_s > 0:
                await asyncio.sleep(min(float(wait_s), 30.0))
            block2 = check_engagement_allowed(self.account_id, cdp_endpoint=self.cdp_endpoint)
            if block2 is not None:
                raise EngagementRiskError(block2.risk_code, block2.message)

        timeout = 120.0
        try:
            timeout = float(os.environ.get("XHS_CDP_ENGAGEMENT_LOCK_TIMEOUT_S", "120") or 120)
        except (TypeError, ValueError, OverflowError):
            timeout = 120.0
        cm = hold_cdp_session(
            account_id=self.account_id,
            cdp_endpoint=self.cdp_endpoint,
            owner="engagement",
            wait=True,
            timeout=timeout,
        )
        # Wrap so release notes engagement cool-down for the next session.
        return _EngagementCdpHold(cm, self.account_id, self.cdp_endpoint)

    def _precheck_engagement(self, *, kind: str, correlation_id: str = "") -> dict[str, Any] | None:
        """Account pause + daily quota before any browser attach."""
        from backend.services.xhs_risk_gate import (
            check_comment_reply_quota,
            check_dm_quota,
            check_engagement_risk_pause,
        )

        pause = check_engagement_risk_pause(self.account_id)
        if pause is not None:
            return self._blocked_result(
                pause.risk_code, pause.message, correlation_id=correlation_id
            )
        if kind == "dm":
            quota = check_dm_quota(self.account_id)
        else:
            quota = check_comment_reply_quota(self.account_id)
        if quota is not None:
            return self._blocked_result(
                quota.risk_code, quota.message, correlation_id=correlation_id
            )
        return None

    async def reply_to_comment(
        self,
        note_id: str,
        comment_id: str,
        reply_content: str,
    ) -> dict[str, Any]:
        """回复评论；遇到登录/风控页面后立即停止且不重试。

        ``nobody`` mode closes even this: answering a comment still touches a
        person, and a policy that says "touch nobody" means it (§9.5).
        """
        from backend.services.cdp_session_lock import CdpSessionBusyError
        from backend.services.xhs_outreach_policy import load_outreach_policy

        correlation_id = self._correlation_id("comment_reply")
        blocked = self._precheck_engagement(kind="comment_reply", correlation_id=correlation_id)
        if blocked is not None:
            return blocked
        policy = await load_outreach_policy(self.account_id)
        if not policy.allows_engagement:
            return self._blocked_result(
                "outreach_suspended",
                (
                    "该账号触达策略为 nobody（不触达任何人，含应答式回复）。"
                    "如需恢复，请为该账号调整触达策略。"
                ),
                correlation_id=correlation_id,
            )

        try:
            async with await self._hold_cdp(), self._guard.lock:
                result = await self._reply_to_comment_locked(
                    note_id, comment_id, reply_content, correlation_id=correlation_id
                )
            # Quota counts a *possible* send too: an unknown submit cannot be
            # un-sent, so letting it go uncounted would make the ceiling stop
            # bounding anything.
            if result.get("status") in _QUOTA_STATUSES:
                from backend.services.xhs_risk_gate import note_comment_reply_sent

                note_comment_reply_sent(self.account_id)
            elif result.get("error_code") == "risk_control":
                from backend.services.xhs_risk_gate import note_engagement_risk_pause

                note_engagement_risk_pause(self.account_id, reason="risk_control")
            return result
        except EngagementRiskError as exc:
            if exc.error_code == "risk_control":
                from backend.services.xhs_risk_gate import note_engagement_risk_pause

                note_engagement_risk_pause(self.account_id, reason="risk_control")
            return self._blocked_result(exc.error_code, str(exc))
        except CdpSessionBusyError as exc:
            return self._blocked_result("cdp_busy", f"CDP session busy (held by {exc.holder})")

    async def _reply_to_comment_locked(
        self,
        note_id: str,
        comment_id: str,
        reply_content: str,
        *,
        correlation_id: str = "",
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
                return self._result(
                    FAILED,
                    error_code="comment_not_found",
                    error="未找到目标评论",
                    correlation_id=correlation_id,
                )
            await self._assert_safe_page(page)
            reply_btn = await comment_element.query_selector("text=回复, .reply-btn")
            if reply_btn:
                await self._paced(reply_btn.click)
                await self._assert_safe_page(page)

            reply_input = await page.query_selector(
                "textarea[placeholder*=回复], .reply-input, input.reply-input"
            )
            if reply_input is None:
                return self._result(
                    FAILED,
                    error_code="reply_input_missing",
                    error="无法找到回复输入框",
                    correlation_id=correlation_id,
                )
            await self._paced(lambda: reply_input.fill(reply_content))
            send_btn = await page.query_selector("text=发送, button.send-btn")
            if send_btn is None:
                # Nothing was submitted, so this is a definite failure -- and it
                # must say *which* failure. Treating the missing button as
                # "nothing to click" and reporting success is how a page change
                # turns into silent data loss (the DM path did exactly that).
                return self._result(
                    FAILED,
                    error_code="send_button_missing",
                    error="未找到发送按钮：回复未提交",
                    correlation_id=correlation_id,
                )
            await self._paced(send_btn.click)
            await self._assert_safe_page(page)
            try:
                await page.wait_for_function(
                    """
                        const replies = document.querySelectorAll('.reply-item');
                        return replies.length > 0;
                        """,
                    timeout=5000,
                )
            except Exception as exc:
                # The submit was already issued, so *any* failure from here on
                # means "it may have been posted". Reporting that as a plain
                # failure invites the operator to send the same reply twice.
                logger.warning("回复已提交但无法确认: %s (correlation=%s)", exc, correlation_id)
                return self._result(
                    UNKNOWN,
                    error_code="verification_timeout",
                    error=f"回复已提交，但页面未在 5s 内确认: {exc}",
                    correlation_id=correlation_id,
                )
            # ``verified`` comes from the DOM check above; ``receipt_id`` stays
            # empty because the page never hands us the platform's reply id --
            # the old ``reply_<timestamp>`` was a clock reading in a receipt's
            # clothing, and two replies in the same second shared it.
            return self._result(SENT, correlation_id=correlation_id, verified=True)
        except EngagementRiskError as exc:
            logger.warning(
                "engagement stopped without retry account=%s code=%s: %s",
                self.account_id or "unknown",
                exc.error_code,
                exc,
            )
            return self._blocked_result(exc.error_code, str(exc), correlation_id=correlation_id)
        except EngagementConfigurationError as exc:
            logger.warning("engagement unavailable: %s", exc)
            return self._blocked_result("configuration", str(exc), correlation_id=correlation_id)
        except Exception as exc:
            logger.error("回复评论失败: %s", exc, exc_info=True)
            return self._result(
                FAILED,
                error_code="exception",
                error=f"{type(exc).__name__}: {exc}",
                correlation_id=correlation_id,
            )

    async def send_dm(
        self,
        target_user_id: str,
        message: str,
        *,
        human_confirmed: bool = False,
    ) -> dict[str, Any]:
        """发送私信；遇到登录/风控页面后立即停止且不重试。

        Cold-start (新建私信) is the account's *policy* question (§9.5), not a
        global switch: the resolved policy is loaded here, refuses outright
        when it allows nobody, and is handed to the target gate so the budget
        and the "who" answer come from the same table.  A target in the
        unread/inbound peer cache is a reply and passes either way.
        """
        from backend.services.cdp_session_lock import CdpSessionBusyError
        from backend.services.xhs_outreach_policy import load_outreach_policy
        from backend.services.xhs_risk_gate import (
            check_dm_target_allowed,
            is_inbound_peer,
            note_dm_sent,
            note_engagement_risk_pause,
        )

        correlation_id = self._correlation_id("dm")
        blocked = self._precheck_engagement(kind="dm", correlation_id=correlation_id)
        if blocked is not None:
            return blocked
        policy = await load_outreach_policy(self.account_id)
        if not policy.allows_engagement:
            return self._blocked_result(
                "outreach_suspended",
                (
                    "该账号触达策略为 nobody（不触达任何人，含应答式私信）。"
                    "如需恢复，请为该账号调整触达策略。"
                ),
                correlation_id=correlation_id,
            )
        target_block = check_dm_target_allowed(
            self.account_id,
            target_user_id,
            human_confirmed=human_confirmed,
            policy=policy,
        )
        if target_block is not None:
            return self._blocked_result(
                target_block.risk_code, target_block.message, correlation_id=correlation_id
            )
        # A reply to someone who wrote first never spends the outreach budget;
        # anything the target gate let through as cold outreach does.
        proactive = not is_inbound_peer(self.account_id, target_user_id)

        try:
            async with await self._hold_cdp(), self._guard.lock:
                result = await self._send_dm_locked(
                    target_user_id,
                    message,
                    human_confirmed=human_confirmed,
                    correlation_id=correlation_id,
                )
            # Same rule as the comment path: a *possible* send counts against
            # the daily ceiling, because it cannot be taken back.
            if result.get("status") in _QUOTA_STATUSES:
                note_dm_sent(self.account_id, proactive=proactive)
            elif result.get("error_code") == "risk_control":
                note_engagement_risk_pause(self.account_id, reason="risk_control")
            return result
        except EngagementRiskError as exc:
            if exc.error_code == "risk_control":
                note_engagement_risk_pause(self.account_id, reason="risk_control")
            return self._blocked_result(exc.error_code, str(exc), correlation_id=correlation_id)
        except CdpSessionBusyError as exc:
            return self._blocked_result(
                "cdp_busy",
                f"CDP session busy (held by {exc.holder})",
                correlation_id=correlation_id,
            )

    async def _send_dm_locked(
        self,
        target_user_id: str,
        message: str,
        *,
        human_confirmed: bool,
        correlation_id: str,
    ) -> dict[str, Any]:
        """The browser half of ``send_dm``; the caller owns the lock and quota.

        Split out for the same reason ``_reply_to_comment_locked`` is: quota
        accounting must read the *verdict*, so it cannot live inside the block
        that produces it (the old code noted the quota before it knew whether
        anything had been sent).
        """
        try:
            page = await self._ensure_page()
            await self._assert_safe_page(page)
            await self._paced(lambda: page.goto(self.DM_URL, wait_until="domcontentloaded"))
            await self._assert_safe_page(page)

            # Never click 「新建私信」 for inbound replies. Cold-start
            # (outbound) only when the caller already passed the
            # whitelist/confirm gate above with human_confirmed=True.
            from backend.services.xhs_risk_gate import is_inbound_peer

            if human_confirmed and not is_inbound_peer(self.account_id, target_user_id):
                new_dm_btn = await page.query_selector("text=新建私信, .new-dm-btn")
                if new_dm_btn:
                    await self._paced(new_dm_btn.click)
                    await self._assert_safe_page(page)
            search_input = await page.query_selector("input[placeholder*=搜索], .dm-search-input")
            if search_input:
                await self._paced(lambda: search_input.fill(target_user_id))
                user_result = await page.query_selector(
                    f".user-item[data-id='{target_user_id}'], .search-result-item"
                )
                if user_result:
                    await self._paced(user_result.click)
                    await self._assert_safe_page(page)

            dm_input = await page.query_selector("textarea[placeholder*=输入], .dm-input")
            if dm_input is None:
                return self._result(
                    FAILED,
                    error_code="dm_input_missing",
                    error="无法找到私信输入框",
                    correlation_id=correlation_id,
                )
            await self._paced(lambda: dm_input.fill(message))
            send_btn = await page.query_selector("text=发送, button.send-btn")
            if send_btn is None:
                # The old code skipped the click and reported ``success: True``
                # with a minted message id: a DM nobody received, plus a quota
                # unit spent, indistinguishable from a delivery. Nothing was
                # submitted here, so this is a definite failure.
                return self._result(
                    FAILED,
                    error_code="send_button_missing",
                    error="未找到发送按钮：私信未发送",
                    correlation_id=correlation_id,
                )
            await self._paced(send_btn.click)
            await self._assert_safe_page(page)
            # No read-back exists yet, so ``verified`` stays False: the click is
            # evidence that we submitted, not that the platform accepted. And
            # ``receipt_id`` is empty for the same reason the comment path's is:
            # the page echoes no id, and the old ``dm_<timestamp>`` was a clock
            # reading wearing a receipt's name.
            return self._result(SENT, correlation_id=correlation_id)
        except EngagementRiskError as exc:
            logger.warning(
                "engagement stopped without retry account=%s code=%s: %s",
                self.account_id or "unknown",
                exc.error_code,
                exc,
            )
            return self._blocked_result(exc.error_code, str(exc), correlation_id=correlation_id)
        except EngagementConfigurationError as exc:
            logger.warning("engagement unavailable: %s", exc)
            return self._blocked_result("configuration", str(exc), correlation_id=correlation_id)
        except Exception as exc:
            logger.error("发送私信失败: %s", exc, exc_info=True)
            return self._result(
                FAILED,
                error_code="exception",
                error=f"{type(exc).__name__}: {exc}",
                correlation_id=correlation_id,
            )

    async def get_unread_messages(self) -> list[dict[str, Any]]:
        """获取未读私信列表；登录/风控页面返回空结果并停止。"""
        from backend.services.cdp_session_lock import CdpSessionBusyError

        try:
            async with await self._hold_cdp(), self._guard.lock:
                try:
                    page = await self._ensure_page()
                    await self._assert_safe_page(page)
                    await self._paced(lambda: page.goto(self.DM_URL, wait_until="domcontentloaded"))
                    await self._assert_safe_page(page)
                    unread_items = await page.query_selector_all(
                        ".message-item.unread, .unread-badge"
                    )
                    messages = []
                    peer_ids: list[str] = []
                    for item in unread_items:
                        sender = await item.query_selector(".sender-name")
                        content = await item.query_selector(".message-preview")
                        sender_id_attr = await item.get_attribute("data-user-id")
                        if sender_id_attr:
                            peer_ids.append(str(sender_id_attr))
                        if sender and content:
                            messages.append(
                                {
                                    "sender_name": await sender.inner_text(),
                                    "sender_id": str(sender_id_attr or ""),
                                    "preview": await content.inner_text(),
                                    "is_unread": True,
                                }
                            )
                    if peer_ids:
                        from backend.services.xhs_risk_gate import note_inbound_peers

                        note_inbound_peers(self.account_id, peer_ids)
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


class _EngagementCdpHold:
    """Async context that notes engagement cool-down on exit."""

    def __init__(self, cm: Any, account_id: str, cdp_endpoint: str) -> None:
        self._cm = cm
        self._account_id = account_id
        self._cdp_endpoint = cdp_endpoint

    async def __aenter__(self) -> str:
        return cast("str", await self._cm.__aenter__())

    async def __aexit__(self, *exc: Any) -> None:
        try:
            await self._cm.__aexit__(*exc)
        finally:
            from backend.services.xhs_risk_gate import note_engagement

            note_engagement(self._account_id, cdp_endpoint=self._cdp_endpoint)
