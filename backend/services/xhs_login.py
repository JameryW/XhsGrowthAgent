"""小红书扫码登录 service — connect_over_cdp 连 host 真实 Chrome，拦 qrcode 接口.

流程：
1. ``connect_over_cdp(account_cdp_endpoint)`` 连 launcher 管的 host 常驻 Chrome
   （真实 Chrome 指纹≠playwright bundled chromium，避 xhs 471 风控）。
2. 在 host Chrome 的 page 上 ``goto`` ``https://www.xiaohongshu.com/explore``，
   登录浮层自动触发 ``POST /api/sns/web/v1/login/qrcode/create``。
3. ``page.on("response")`` 拦截该 XHR，取 ``data.url`` + ``data.qr_id`` + ``data.code``。
4. headless/headed 下 xhs 前端 JS 都不自动轮询 ``qrcode/status``（实测），故
   ``get_status()`` 用 ``page.evaluate(fetch)`` 主动发 status GET，取 ``data.code_status``
   （0=待扫 / 1=已扫待确认 / 2=已确认）。复用页面 cookie + x-s/x-t 签名上下文。
5. ``code_status==2`` 即登录成功，cookie 已写 host Chrome 的 user-data-dir
   （= account.chrome_profile_path），常驻 Chrome 后续 CDP 发布复用——profile
   共享 gap 自然消解（host 单一来源）。
6. 二维码过期（超时无 2）→ 重新 ``goto`` 刷新 qrcode/create，返回新 qr_id+url。

每账号独立 ``XhsLoginSession``，但共用 host 常驻 Chrome（launcher 管 lifecycle）。
同一账号已有进行中会话则 ``start`` 复用（返回当前 qr_id+url）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse, urlunparse

# playwright is an optional [browser] extra. Import lazily inside methods so
# the module is importable (and unit-testable with mocks) without it installed.
# `from __future__ import annotations` keeps Browser/Page/Context annotations
# as strings, so they never force a runtime import.
if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page

logger = logging.getLogger("xhs_growth.login")

# www 站登录浮层自动触发 qrcode/create 的入口页。creator.xiaohongshu.com/login
# 无二维码 UI（spike 实测），只有 www 站 explore 页弹登录浮层才发 qrcode/create。
_EXPLORE_URL = "https://www.xiaohongshu.com/explore"

# 拦截的 XHR 路径片段（match by substring — full URL varies by CDN/gateway）。
_QR_CREATE_PATH = "/api/sns/web/v1/login/qrcode/create"
_QR_STATUS_PATH = "/api/sns/web/v1/login/qrcode/status"
_SECURITY_ERROR_PATH = "/website-login/error"
_LOGIN_COOKIE_NAMES = {
    "web_session",
    "id_token",
    "access-token-creator.xiaohongshu.com",
}
# Creator Center needs its own access token. A bare ``id_token`` often survives
# after the creator session expires and produces false "logged_in" status while
# creator APIs return 401 and the login shell is shown.
_CREATOR_LOGIN_COOKIE_NAMES = {
    "access-token-creator.xiaohongshu.com",
}
# Settings / preflight "logged_in" is creator-token only. www cookies alone
# (web_session + id_token) are a partial session — stats sync still 401s.
_STRONG_LOGIN_COOKIE_NAMES = {
    "access-token-creator.xiaohongshu.com",
}
# Partial www SSO cookies that keep explore on the feed (no login QR modal).
# Clearing them forces explore to re-show the scan-login shell.
_PARTIAL_WWW_AUTH_COOKIE_NAMES = frozenset({"web_session", "id_token"})
_LOGIN_STATUS_URLS = [_EXPLORE_URL, "https://creator.xiaohongshu.com"]
_CREATOR_HOME_URL = "https://creator.xiaohongshu.com/new/home"
_CREATOR_PAGE_READY_SIGNAL = "creator_page_ready"
_CREATOR_PAGE_STATUS_SCRIPT = r"""
() => {
    const host = String(window.location.hostname || '').toLowerCase();
    const path = String(window.location.pathname || '').toLowerCase();
    const isLoginPath =
        path.includes('/login') || path.includes('website-login') || path.includes('passport');
    if (host !== 'creator.xiaohongshu.com' || isLoginPath) {
        return { ready: false, signals: [] };
    }

    const bodyText = String(
        (document.body && (document.body.innerText || document.body.textContent)) || ''
    );
    const loginShellMarkers = ['短信登录', '扫码登录', '发送验证码', '请先登录', '登录即同意'];
    const loginShellHits = loginShellMarkers.filter((marker) => bodyText.includes(marker)).length;
    if (loginShellHits >= 2) {
        return { ready: false, signals: [] };
    }

    const businessMarkers = [
        ['creator_publish_note', '发布笔记'],
        ['creator_dashboard', '数据看板'],
        ['creator_note_manager', '笔记管理'],
        ['creator_followers', '粉丝'],
    ];
    const matched = businessMarkers
        .filter(([, marker]) => bodyText.includes(marker))
        .map(([signal]) => signal);
    return { ready: matched.length >= 2, signals: matched };
}
"""


def _cookie_names_mean_logged_in(cookie_names: set[str]) -> tuple[bool, list[str], str]:
    """Return (is_logged_in, signal_names, reason) from observed cookie names.

    Rules (creator-center readiness — not mere www presence):
    - ``access-token-creator.*`` alone is enough → ``logged_in`` / ``strong_cookie``.
    - Durable www pair ``web_session`` + ``id_token`` without creator token is
      **not** logged in for Creator Center (``www_only``). Live profiles often
      keep this pair after creator SSO expires while stats APIs return 401;
      treating it as green "已登录" misleads operators and skips preflight.
    - Lone ``id_token`` (no ``web_session``) is stale (``stale_id_token``).
    - Lone ``web_session`` or no auth cookies → ``missing_strong_cookie``.
    """
    names = {str(n) for n in cookie_names if n}
    creator_hits = sorted(names & _CREATOR_LOGIN_COOKIE_NAMES)
    if creator_hits:
        return True, creator_hits, "strong_cookie"
    has_id = "id_token" in names
    has_session = "web_session" in names
    if has_id and has_session:
        return False, sorted({"id_token", "web_session"}), "www_only"
    if has_id and not has_session:
        return False, ["id_token"], "stale_id_token"
    if has_session and not has_id:
        return False, ["web_session"], "missing_strong_cookie"
    return False, [], "missing_strong_cookie"


def _creator_page_state_is_ready(state: Any) -> bool:
    """Accept only the boolean page-evidence result, never page text."""
    return isinstance(state, dict) and state.get("ready") is True


def _creator_page_status(account_id: str) -> dict[str, Any]:
    """Return the stable login result used for Creator Center page evidence."""
    return {
        "account_id": account_id,
        "status": "logged_in",
        "is_logged_in": True,
        "reason": _CREATOR_PAGE_READY_SIGNAL,
        "signals": [_CREATOR_PAGE_READY_SIGNAL],
    }


# codeStatus 语义（spike + reverse-engineered CLI 源码确认）。
_CODE_WAITING = 0  # 待扫
_CODE_SCANNED = 1  # 已扫待确认
_CODE_CONFIRMED = 2  # 已确认登录
_CODE_EXPIRED = 3  # 已失效/需刷新

# 二维码等待确认的超时（秒）。超时未确认 → 判定过期，自动刷新。
# XHS qrcode/status 也会返回 code_status=3 表示当前二维码不可继续确认。
_QR_CONFIRM_TIMEOUT_S = 120.0

# 等待二维码就绪的窗口（秒）。优先取 qrcode/create 响应；若 XHS 前端
# 已渲染二维码但接口响应被 service worker/时序隐藏，则回退读取 DOM 图片。
# API route 外层有 10s 硬超时，内部等待必须短于它。
# Wait for qrcode/create or a rendered DOM QR. Keep under the API route's 10s
# outer timeout (accounts.start_qr_login wait_for(..., 10s)).
_QR_CREATE_WAIT_S = 5.0
_ALREADY_LOGIN_CHECK_S = 1.5
_EXPLORE_GOTO_TIMEOUT_MS = 12000
# XHS often commits explore then redirects to /website-login/error a moment later.
_SECURITY_REDIRECT_SETTLE_S = 1.5
# Settle pauses inside _ensure_login_modal: after each 登录-label click (SPA
# paint) and one final settle if no label opened the modal. Extracted as
# constants so tests can shrink them (the real waits are for live-browser
# rendering, irrelevant under the playwright mock).
_LOGIN_MODAL_CLICK_SETTLE_S = 0.8
_LOGIN_MODAL_FINAL_SETTLE_S = 0.5
# Creator SPA warm-up settle after navigating to creator home: lets the app
# mint access-token cookies before we check. Extracted so tests can shrink it
# (the mock page does no SPA rendering to settle).
_CREATOR_WARMUP_SETTLE_S = 1.5
# Polling intervals for the login-flow wait loops. Extracted so tests can
# shrink them — each fires once on the first poll iteration in the mock path.
_EXISTING_LOGIN_POLL_S = 0.2
_QR_READY_POLL_S = 0.3
_EXPLORE_POLL_S = 0.25

_VERIFICATION_CODE_FILL_SCRIPT = r"""
async (code) => {
    const isVisible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none'
            && style.visibility !== 'hidden'
            && rect.width > 0
            && rect.height > 0;
    };
    const setNativeValue = (el, value) => {
        el.focus();
        const proto = Object.getPrototypeOf(el);
        const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
        if (descriptor && descriptor.set) {
            descriptor.set.call(el, value);
        } else {
            el.value = value;
        }
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
    };
    const metaText = (input) => [
        input.placeholder,
        input.name,
        input.id,
        input.className,
        input.getAttribute('aria-label'),
        input.getAttribute('autocomplete'),
        input.closest('label')?.innerText,
        input.parentElement?.innerText,
        input.parentElement?.parentElement?.innerText,
    ].filter(Boolean).join(' ').toLowerCase();
    const scoreInput = (input) => {
        const type = (input.getAttribute('type') || 'text').toLowerCase();
        if (['hidden', 'password', 'checkbox', 'radio', 'file'].includes(type)) return -100;
        if (input.disabled || input.readOnly || !isVisible(input)) return -100;
        const text = metaText(input);
        let score = 0;
        if (['tel', 'text', 'number', 'search', ''].includes(type)) score += 2;
        if (/验证码|校验码|短信|安全|code|captcha|verify|verification|sms|otp/.test(text)) {
            score += 12;
        }
        const maxLength = Number(input.getAttribute('maxlength') || input.maxLength || 0);
        if (maxLength >= 4 && maxLength <= 8) score += 5;
        if (maxLength === 1) score += 3;
        if (input.inputMode === 'numeric') score += 3;
        if (String(input.value || '').match(/^\\d*$/)) score += 1;
        return score;
    };

    const inputs = Array.from(document.querySelectorAll('input'))
        .map((input) => ({ input, score: scoreInput(input) }))
        .filter((item) => item.score > 0)
        .sort((a, b) => b.score - a.score);
    if (!inputs.length) {
        return { filled: false, reason: 'verification_input_not_found', frame_url: location.href };
    }

    const digitInputs = inputs
        .filter((item) => {
            const input = item.input;
            const maxLength = Number(input.getAttribute('maxlength') || input.maxLength || 0);
            return maxLength === 1 || input.clientWidth <= 72;
        })
        .map((item) => item.input);

    let targetCount = 1;
    if (digitInputs.length >= code.length && code.length >= 4) {
        code.split('').forEach((digit, index) => setNativeValue(digitInputs[index], digit));
        targetCount = code.length;
    } else {
        setNativeValue(inputs[0].input, code);
    }

    await new Promise((resolve) => setTimeout(resolve, 300));
    const buttonWords = [
        '确认', '确定', '提交', '登录', '验证', '完成', '下一步', '继续',
        'confirm', 'submit', 'verify', 'login', 'next', 'continue', 'ok',
    ];
    const controls = Array.from(document.querySelectorAll(
        'button,[role="button"],input[type="button"],input[type="submit"]'
    ));
    const submit = controls.find((el) => {
        if (!isVisible(el) || el.disabled || el.getAttribute('aria-disabled') === 'true') {
            return false;
        }
        const text = [
            el.innerText,
            el.value,
            el.getAttribute('aria-label'),
            el.getAttribute('title'),
            el.className,
        ].filter(Boolean).join(' ').toLowerCase();
        return buttonWords.some((word) => text.includes(word.toLowerCase()));
    });
    if (submit) submit.click();

    return {
        filled: true,
        clicked: Boolean(submit),
        target_count: targetCount,
        frame_url: location.href,
    };
}
"""

_QR_IMAGE_EXTRACT_SCRIPT = """
() => {
    const visible = (img) => {
        const rect = img.getBoundingClientRect();
        const style = window.getComputedStyle(img);
        return rect.width >= 80 && rect.height >= 80
            && style.display !== 'none'
            && style.visibility !== 'hidden';
    };
    const score = (img) => {
        const src = String(img.currentSrc || img.src || '');
        const cls = String(img.className || '').toLowerCase();
        const alt = String(img.alt || '').toLowerCase();
        const w = Number(img.naturalWidth || img.width || 0);
        const h = Number(img.naturalHeight || img.height || 0);
        const square = w >= 96 && h >= 96 && Math.abs(w - h) <= 12;
        let value = 0;
        if (cls.includes('qrcode') || cls.includes('qr')) value += 10;
        if (alt.includes('qrcode') || alt.includes('二维码')) value += 8;
        if (src.startsWith('data:image/')) value += 5;
        if (src.includes('qrcode') || src.includes('qr')) value += 4;
        if (square) value += 3;
        if (!visible(img)) value -= 20;
        return { src, value };
    };
    const candidates = Array.from(document.images)
        .map(score)
        .filter((item) => item.src && item.value >= 8)
        .sort((a, b) => b.value - a.value);
    return candidates[0]?.src || '';
}
"""

_LOGIN_PAGE_STATE_SCRIPT = r"""
() => {
    const isVisible = (element) => {
        if (!element || !element.getClientRects().length) return false;
        let current = element;
        while (current && current.nodeType === 1) {
            const style = window.getComputedStyle(current);
            if (
                style.display === 'none'
                || style.visibility === 'hidden'
                || style.visibility === 'collapse'
                || style.opacity === '0'
                || current.getAttribute('aria-hidden') === 'true'
            ) {
                return false;
            }
            current = current.parentElement;
        }
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    };
    const isEnabled = (input) => (
        !input.disabled
        && !input.readOnly
        && input.getAttribute('aria-disabled') !== 'true'
    );
    const inputMetadata = (input) => {
        const labels = Array.from(input.labels || [])
            .map((label) => label.innerText || '')
            .join(' ');
        return [
            input.getAttribute('type'),
            input.getAttribute('name'),
            input.getAttribute('id'),
            input.getAttribute('class'),
            input.getAttribute('placeholder'),
            input.getAttribute('aria-label'),
            input.getAttribute('autocomplete'),
            input.getAttribute('inputmode'),
            input.getAttribute('pattern'),
            input.getAttribute('data-testid'),
            labels,
        ].filter(Boolean).join(' ').toLowerCase();
    };
    const codeMarker = new RegExp([
        '验证码', '校验码', '安全码', '动态码', '短信码', '一次性',
        'one[-_ ]?time', 'captcha', 'verification', 'verify', 'sms', 'otp',
        '\\bcode\\b',
    ].join('|'));
    const inputs = Array.from(document.querySelectorAll('input'))
        .filter((input) => isEnabled(input) && isVisible(input))
        .map((input) => {
            const type = (input.getAttribute('type') || 'text').toLowerCase();
            const inputMode = (input.getAttribute('inputmode') || '').toLowerCase();
            const autocomplete = (input.getAttribute('autocomplete') || '').toLowerCase();
            const pattern = input.getAttribute('pattern') || '';
            const maxLength = Number(
                input.getAttribute('maxlength') || input.maxLength || 0,
            );
            const metadata = inputMetadata(input);
            const marked = codeMarker.test(metadata);
            const numeric = (
                ['tel', 'number'].includes(type)
                || ['numeric', 'decimal', 'tel'].includes(inputMode)
                || autocomplete === 'one-time-code'
                || /\d/.test(pattern)
            );
            const codeType = ['text', 'search', 'tel', 'number'].includes(type);
            const rect = input.getBoundingClientRect();
            const singleBox = maxLength === 1 || (numeric && rect.width <= 72);
            const validLength = maxLength >= 4 && maxLength <= 8;
            const standalone = codeType && (marked || (numeric && validLength));
            return { input, marked, numeric, singleBox, standalone };
        });

    // A regular OTP field needs semantic/numeric evidence. A row of enabled
    // one-character boxes is also a code control even when its class/label is
    // opaque; unrelated body copy is deliberately never consulted here.
    const multiBoxCount = inputs.filter((item) => item.singleBox).length;
    const verificationRequired = inputs.some((item) => item.standalone)
        || (multiBoxCount >= 4 && multiBoxCount <= 8);

    const visibleText = String(document.body?.innerText || '');
    return {
        scanned: visibleText.includes('扫码成功') || visibleText.includes('请在手机上确认'),
        verification_required: verificationRequired,
        qr_expired: visibleText.includes('二维码已过期'),
    };
}
"""


async def _resolve_cdp_connect_endpoint(cdp_endpoint: str) -> str:
    """Return a Playwright-compatible CDP endpoint.

    Chrome DevTools rejects ``Host: host.containers.internal:<port>`` on
    ``/json/version``. Playwright cannot override that header when given an
    HTTP endpoint, so container deployments must pre-fetch the browser websocket
    URL with a localhost Host header, then rewrite the host back to the reachable
    container-to-host address.
    """
    endpoint = cdp_endpoint.strip()
    if endpoint.startswith(("ws://", "wss://")):
        return endpoint

    parsed = urlparse(endpoint)
    if not parsed.hostname or parsed.port is None:
        return endpoint
    if parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return endpoint

    version_url = urlunparse((parsed.scheme or "http", parsed.netloc, "/json/version", "", "", ""))
    loop = asyncio.get_running_loop()

    def _fetch_ws_url() -> str:
        req = urllib.request.Request(
            version_url,
            headers={"Host": f"127.0.0.1:{parsed.port}"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        ws_url = str(data.get("webSocketDebuggerUrl") or "")
        if not ws_url:
            return endpoint
        ws = urlparse(ws_url)
        return urlunparse((ws.scheme or "ws", parsed.netloc, ws.path, "", ws.query, ""))

    try:
        return await loop.run_in_executor(None, _fetch_ws_url)
    except Exception as e:
        logger.debug("CDP websocket endpoint 解析失败，回退原 endpoint: %s", e)
        return endpoint


def _should_try_raw_cdp_endpoint(cdp_endpoint: str) -> bool:
    parsed = urlparse(cdp_endpoint)
    return parsed.hostname not in {None, "127.0.0.1", "localhost", "::1"}


class LoginError(Exception):
    """扫码登录流程错误（启动失败 / playwright 未装 / 超时等）。"""


class XhsLoginSession:
    """管理一次账号的扫码登录会话.

    生命周期：
        ``start()`` → connect_over_cdp 连 host Chrome，开 explore 页拦 qrcode/create，
        返回 ``{qr_id, url}``。前端用 ``qrcode`` JS 库渲染 url 为二维码。
        ``get_status()`` → 主动 page.evaluate fetch qrcode/status，返回 code_status 映射
        （waiting/scanned/confirmed/expired）。expired 时自动刷新二维码。
        ``stop()`` → 关 page + 断 CDP 连接（host Chrome 由 launcher 管，不关）。

    登录态写 host Chrome 的 user-data-dir（= account.chrome_profile_path）——
    CDP 发布复用同 profile，无需单独导出 cookie。
    """

    def __init__(
        self,
        account_id: str,
        profile_path: str,
        cdp_endpoint: str = "",
        *,
        allow_persistent_fallback: bool = True,
    ) -> None:
        self.account_id = account_id
        self.profile_path = profile_path
        # host 真实 Chrome 的 CDP endpoint（connect_over_cdp 用）。显式允许时
        # 才回退到另一个持久化浏览器实例。
        self.cdp_endpoint = cdp_endpoint
        self.allow_persistent_fallback = allow_persistent_fallback
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        # connect_over_cdp 的 browser 句柄（CDP 模式）。None = persistent_context 模式。
        self._browser: Any = None
        # playwright async_playwright().start() handle — kept so stop() can .stop() it.
        self._playwright: Any = None
        # 当前二维码信息（start 时填充，刷新时更新）。
        self._qr_id: str = ""
        self._qr_url: str = ""
        self._qr_code: str = ""  # create 返回的 code，status 轮询参数
        # 最新 codeStatus（listener 异步更新）。
        self._code_status: int = _CODE_WAITING
        # codeStatus==2 时缓存的登录信息（含 session/user_id）。
        self._login_info: dict[str, Any] = {}
        self._confirmed = False
        self._force_refresh_qr = False
        # 启动时间戳，用于超时判定。
        self._started_at: float = 0.0
        # 最近一次 qrcode/create 响应到达时间，用于过期判定。
        self._qr_created_at: float = 0.0
        # Raw-CDP fallback for container → host Chrome deployments where
        # Playwright's connect_over_cdp handshake stalls behind the TCP forwarder.
        self._raw_ws: Any = None
        self._raw_target_id: str = ""
        self._raw_session_id: str = ""
        self._raw_msg_id: int = 0
        # Shared CDP mutex held from start() until stop() so stats/publish
        # cannot attach while the QR session owns the profile.
        self._cdp_hold: Any = None

    @property
    def qr_id(self) -> str:
        return self._qr_id

    @property
    def qr_url(self) -> str:
        return self._qr_url

    async def _ensure_cdp_hold(self) -> None:
        """Acquire the shared CDP session lock for the lifetime of this QR session."""
        if self._cdp_hold is not None:
            return
        from backend.services.cdp_session_lock import CdpSessionBusyError, hold_cdp_session

        timeout = 45.0
        try:
            timeout = float(os.environ.get("XHS_CDP_LOGIN_LOCK_TIMEOUT_S", "45") or 45)
        except (TypeError, ValueError, OverflowError):
            timeout = 45.0
        cm = hold_cdp_session(
            account_id=self.account_id,
            cdp_endpoint=self.cdp_endpoint,
            owner="qr_login",
            wait=True,
            timeout=timeout,
        )
        try:
            await cm.__aenter__()
        except CdpSessionBusyError as exc:
            raise LoginError(f"浏览器正被其他任务占用（{exc.holder}），请稍后再扫码登录。") from exc
        self._cdp_hold = cm

    async def _release_cdp_hold(self) -> None:
        cm = self._cdp_hold
        self._cdp_hold = None
        if cm is None:
            return
        with contextlib.suppress(Exception):
            await cm.__aexit__(None, None, None)

    async def start(self) -> dict[str, Any]:
        """启动 Chrome（headed），拦截 qrcode/create，返回 ``{qr_id, url}``.

        若会话已启动且二维码有效，复用现有会话（返回当前 qr_id+url）。
        若二维码已过期，自动刷新。
        """
        if self._confirmed:
            return {
                "status": "confirmed",
                "qr_id": self._qr_id,
                "url": "",
                "account_id": self.account_id,
            }

        # Serialize against creator-stats / publish / engagement on this profile.
        await self._ensure_cdp_hold()

        # Raw-CDP sessions do not populate _context. Treat them as active
        # sessions here as well, otherwise repeated start() calls open a new
        # websocket while reusing the previous target session id.
        if self._raw_ws is not None and not self._confirmed:
            if self._qr_id and self._qr_url and not self._is_qr_expired():
                return {
                    "qr_id": self._qr_id,
                    "url": self._qr_url,
                    "account_id": self.account_id,
                }
            await self.stop()

        # 已有进行中会话：复用（返回当前 qr_id+url），符合"同一账号 start 复用"约定。
        if self._context is not None and self._qr_id and not self._confirmed:
            if not self._is_qr_expired():
                return {
                    "qr_id": self._qr_id,
                    "url": self._qr_url,
                    "account_id": self.account_id,
                }
            # 过期 → 刷新二维码（复用已开的 context，重新 goto）。
            return await self._refresh_qr()

        # 残留 context（上一轮刷新失败/异常中断留下的 zombie）→ 先关掉再重开，
        # 否则下面的 launch_persistent_context 会覆盖引用造成 Chrome 进程泄漏。
        if self._context is not None:
            await self.stop()

        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise LoginError("playwright 未安装。运行: pip install -e '.[browser]'") from e

        self._started_at = time.time()

        try:
            self._playwright = await async_playwright().start()

            if self.cdp_endpoint:
                # connect_over_cdp：连 host 真实 Chrome（launcher 管的常驻实例）。
                # 真实 Chrome 指纹≠playwright bundled chromium，避 xhs 471 风控。
                # 登录态写 host Chrome 的 user-data-dir（= account.chrome_profile_path），
                # 后续 CDP 发布复用同 profile——profile 共享 gap 自然消解。
                if self._should_try_raw_cdp():
                    with contextlib.suppress(Exception):
                        await self._playwright.stop()
                    self._playwright = None
                    return await self._start_raw_cdp()
                try:
                    connect_endpoint = await _resolve_cdp_connect_endpoint(self.cdp_endpoint)
                    self._browser = await self._playwright.chromium.connect_over_cdp(
                        connect_endpoint
                    )
                except Exception as e:
                    if self._should_try_raw_cdp():
                        logger.warning(
                            "Playwright CDP 连接失败，尝试 raw CDP fallback account=%s: %s",
                            self.account_id,
                            e,
                        )
                        with contextlib.suppress(Exception):
                            await self._playwright.stop()
                        self._playwright = None
                        return await self._start_raw_cdp()
                    raise LoginError(
                        f"连接 host Chrome CDP 失败: {self.cdp_endpoint} ({type(e).__name__}: {e})"
                        "——确认 launcher 已启动该账号 Chrome（chrome-profiles.sh start）"
                    ) from e
                contexts = self._browser.contexts
                if not contexts:
                    raise LoginError(
                        "绑定 Chrome 没有可用 browser context，请启动账号 Chrome 后重试。"
                    )
                # CDP 登录必须复用 launcher 创建的持久 profile context。
                # 绝不能创建隔离 context，否则扫码态可能写入错误的 profile。
                self._context = contexts[0]
                logger.info("扫码登录连 host Chrome: %s", self.cdp_endpoint)
            else:
                if not self.allow_persistent_fallback:
                    raise LoginError(
                        "绑定账号缺少可用 CDP endpoint；为避免启动第二个浏览器，请先启动账号 Chrome"
                    )
                # 回退：launch_persistent_context（playwright bundled chromium）。
                # 会被 xhs 471 风控——仅 cdp_endpoint 不可用时兜底。
                # headless 已完全禁止（风控拦截），固定 headed。
                Path(self.profile_path).mkdir(parents=True, exist_ok=True)
                self._context = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=self.profile_path,
                    headless=False,
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                    locale="zh-CN",
                    args=[
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                )
                # 回退路径才需 stealth（connect_over_cdp 连真实 Chrome 不注 stealth——
                # 注入伪装脚本到已合法浏览器反而是自动化特征，会被 shield 标红，见
                # xhs_publisher._ensure_page CDP 分支注释）。
                await self._apply_stealth(self._context)

            # Always use a short-lived login page. Reusing an existing business
            # tab (creator publish page, etc.) can navigate/close the operator's
            # active page when this login session fails or stops.
            self._page = await self._context.new_page()

            # 注册响应拦截器：监听 qrcode/create + qrcode/status。
            self._page.on("response", self._on_response)

            # ── Creator-first path (avoid clearing cookies when possible) ──
            # www_only sessions often still mint access-token-creator after a
            # creator-home visit. Clearing cookies first forces a full re-login
            # and raises 300012 risk on datacenter IPs.
            cookie_names = await self._cookie_names_from_context()
            is_creator, _signals, reason = _cookie_names_mean_logged_in(cookie_names)
            if is_creator:
                return await self._confirm_existing_creator_login()

            if reason == "www_only":
                logger.info(
                    "www_only session: warm creator home before clearing cookies account=%s",
                    self.account_id,
                )
                await self._warm_creator_session()
                # Security page on creator origin is a real risk signal.
                security_error = await self._detect_security_restriction()
                if security_error:
                    raise LoginError(security_error)
                cookie_names = await self._cookie_names_from_context()
                is_creator, _signals, reason = _cookie_names_mean_logged_in(cookie_names)
                if is_creator:
                    return await self._confirm_existing_creator_login(already_warmed=True)

            # Still no creator token — clear partial www SSO so explore paints QR.
            if cookie_names & (_PARTIAL_WWW_AUTH_COOKIE_NAMES | _CREATOR_LOGIN_COOKIE_NAMES):
                await self._clear_partial_login_cookies()

            # 开 explore 页——登录浮层自动触发 qrcode/create。
            await self._goto_explore()
            # Partial sessions keep the feed open without a QR modal — click 登录.
            await self._ensure_login_modal()

            # Creator token may appear mid-flow; only then skip QR.
            if await self._wait_for_existing_login(timeout=_ALREADY_LOGIN_CHECK_S):
                qr_early = await self._extract_qr_image_from_dom()
                if qr_early:
                    self._qr_id = f"dom-{int(time.time() * 1000)}"
                    self._qr_url = qr_early
                    self._qr_created_at = time.time()
                    self._code_status = _CODE_WAITING
                    logger.info(
                        "profile 有 cookie 但登录浮层仍在，返回 DOM 二维码: account=%s",
                        self.account_id,
                    )
                    return {
                        "qr_id": self._qr_id,
                        "url": self._qr_url,
                        "account_id": self.account_id,
                    }
                return await self._confirm_existing_creator_login()

            # 等二维码就绪：优先等 qrcode/create 响应；DOM data:image 回退。
            # _wait_for_qr_ready raises LoginError on security-block pages.
            qr_data = await self._wait_for_qr_ready(timeout=_QR_CREATE_WAIT_S)
            if qr_data is None:
                # One recovery only: reminted www cookies may hide the modal again.
                names_now = await self._cookie_names_from_context()
                if names_now & _PARTIAL_WWW_AUTH_COOKIE_NAMES:
                    logger.info(
                        "首次未找到二维码且仍有 www cookie，清理后重试一次: account=%s",
                        self.account_id,
                    )
                    await self._clear_partial_login_cookies()
                    await self._goto_explore()
                    await self._ensure_login_modal()
                    qr_data = await self._wait_for_qr_ready(timeout=_QR_CREATE_WAIT_S)
            if qr_data is None:
                page_hint = ""
                if self._page is not None:
                    with contextlib.suppress(Exception):
                        page_hint = f"（当前页: {str(self._page.url)[:120]}）"
                raise LoginError(
                    f"启动扫码登录失败：{_QR_CREATE_WAIT_S:.0f}s 内未找到登录二维码"
                    f"{page_hint}。"
                    "常见原因：1) 小红书 IP/环境风控（error 300012）"
                    " 2) 页面结构变化。"
                    "请切换家庭宽带或手机热点后稍后再试。"
                )
        except LoginError:
            # 显式 LoginError（未装 / CDP 连不上 / 超时）：关 context 后原样抛出。
            await self.stop()
            raise
        except Exception as e:
            # launch/goto/stealth 等意外异常：关 context 后包成 LoginError，使 route
            # 的 except LoginError 统一映射 503（裸 Exception 会落到 500 内部错误）。
            await self.stop()
            raise LoginError(f"启动扫码登录失败：{type(e).__name__}: {e}") from e

        self._qr_id = qr_data["qr_id"]
        self._qr_url = qr_data["url"]
        self._qr_created_at = time.time()
        self._code_status = _CODE_WAITING

        logger.info(
            "扫码登录会话已启动: account=%s qr_id=%s profile=%s",
            self.account_id,
            self._qr_id,
            self.profile_path,
        )
        return {
            "qr_id": self._qr_id,
            "url": self._qr_url,
            "account_id": self.account_id,
        }

    async def get_status(self) -> dict[str, Any]:
        """返回当前登录状态.

        Returns:
            ``{status, qr_id, url?, account_id}`` where status is one of:
            - ``"waiting"`` — 待扫码（codeStatus=0）
            - ``"scanned"`` — 已扫待确认（codeStatus=1）
            - ``"confirmed"`` — 已确认登录，cookie 已写 profile（codeStatus=2）
            - ``"expired"`` — 二维码过期/超时，已自动刷新，返回新 url
        """
        # confirmed 优先于 _context is None 判定：confirmed 后会自动 stop()
        # （见下方 codeStatus==2 分支），此时 _context 已为 None，但会话状态仍是
        # confirmed——必须先判 confirmed，否则二次轮询会落到下方 waiting 早返路径。
        if self._confirmed:
            # 已确认：cookie 已落盘 profile，url 清空（前端无需再显示二维码）。
            # 注意 url 必须在此路径也清空，否则前端二次轮询会拿到 stale url 重画二维码
            # （早先 bug：仅末尾路径清空 url，二次 get_status 走此早返路径返回 stale url）。
            return {
                "status": "confirmed",
                "qr_id": self._qr_id,
                "url": "",
                "account_id": self.account_id,
            }

        if self._raw_ws is not None:
            try:
                return await self._get_raw_status()
            except Exception as e:
                logger.warning(
                    "raw CDP 扫码会话已断开 account=%s: %s",
                    self.account_id,
                    e,
                )
                await self.stop()
                raise LoginError("扫码登录会话已断开，请刷新二维码后重试。") from e

        if self._context is None:
            return {
                "status": "waiting",
                "qr_id": self._qr_id,
                "url": self._qr_url,
                "account_id": self.account_id,
            }

        # 二维码过期判定：超时未确认 → 自动刷新。
        if self._is_qr_expired():
            refreshed = await self._refresh_qr()
            return {
                "status": "expired",
                "qr_id": refreshed["qr_id"],
                "url": refreshed["url"],
                "account_id": self.account_id,
            }

        # 主动轮询 qrcode/status：headless 下 xhs 前端 JS 不发起 status XHR
        # （实测仅发 qrcode/create，无 status 轮询——可能 canvas 未渲染致轮询
        # 计时器未启动）。用 page.evaluate 在页面 JS 上下文发 fetch，复用页面
        # 自带的 cookie + x-s/x-t 签名头（后端无法独立签名）。
        await self._poll_status_via_page()

        # Some successful mobile confirmations write login cookies to the real
        # Chrome profile before qrcode/status advances to 2. Treat the durable
        # profile login state as authoritative so the frontend does not spin on
        # a stale waiting status.
        if self._code_status != _CODE_CONFIRMED and await self._looks_logged_in():
            self._code_status = _CODE_CONFIRMED

        if self._force_refresh_qr:
            refreshed = await self._refresh_qr()
            return {
                "status": "expired",
                "qr_id": refreshed["qr_id"],
                "url": refreshed["url"],
                "account_id": self.account_id,
            }

        status_map = {
            _CODE_WAITING: "waiting",
            _CODE_SCANNED: "scanned",
            _CODE_CONFIRMED: "confirmed",
        }
        status = status_map.get(self._code_status, "waiting")
        verification_required = False
        if status == "scanned":
            page_state = await self._probe_login_page_state()
            verification_required = bool(page_state.get("verification_required"))

        if self._code_status == _CODE_CONFIRMED and not self._confirmed:
            # codeStatus==2：登录成功，cookie 已由 persistent context 写入 profile。
            # 标记 confirmed，后续 get_status 直接返回 confirmed（幂等）。
            self._confirmed = True
            logger.info(
                "扫码登录成功: account=%s qr_id=%s login_info keys=%s",
                self.account_id,
                self._qr_id,
                list(self._login_info.keys()),
            )
            status = "confirmed"
            # Mint Creator Center cookies (access-token-creator.*) so stats/publish
            # do not see a "logged_in" www session that still fails on creator APIs.
            # 同时把页面停在 creator home——下面的 keep_page 会把这个 tab 留下来。
            await self._warm_creator_session()
            # 登录确认后保留可见结果：CDP 模式断开连接但 tab 留在 host Chrome
            # （停在 creator home），操作员能直接看到已登录页面。tab 不算泄漏——
            # host Chrome 由 launcher 常驻管理，该页就是登录态的可视化。
            # persistent context 兜底模式下 keep_page 被忽略（断连即杀进程）。
            await self.stop(keep_page=True)
            # 会话自摘：登录态已交接给 profile + 可见 tab，_sessions 不再持有对象，
            # 同账号下次 start() 能新建会话（profile 失效时重走扫码）。
            _detach_session_if_current(self)

        result: dict[str, Any] = {
            "status": status,
            "qr_id": self._qr_id,
            "url": self._qr_url if status != "confirmed" else "",
            "account_id": self.account_id,
        }
        if status == "scanned":
            result["verification_required"] = verification_required
        return result

    async def submit_verification_code(self, code: str) -> dict[str, Any]:
        """Fill a numeric verification code into the current CDP login page.

        The verification UI belongs to XHS' live browser page, not this API. We
        therefore fill the code inside the active page/iframe and then return the
        latest QR login status so the frontend can keep polling.
        """
        code = code.strip()
        if not code.isdigit() or not (4 <= len(code) <= 8):
            raise LoginError("验证码必须是 4-8 位数字")
        if self._raw_ws is not None:
            return await self._submit_raw_verification_code(code)
        if self._page is None:
            raise LoginError("没有可填写验证码的登录页面，请重新启动扫码登录")

        with contextlib.suppress(Exception):
            await self._page.bring_to_front()

        frames = list(getattr(self._page, "frames", []) or [])
        if not frames:
            main_frame = getattr(self._page, "main_frame", None)
            if main_frame is not None:
                frames = [main_frame]

        fill_result: dict[str, Any] | None = None
        for frame in frames:
            try:
                result = await frame.evaluate(_VERIFICATION_CODE_FILL_SCRIPT, code)
            except Exception as e:
                logger.debug("填写验证码 frame 失败 account=%s: %s", self.account_id, e)
                continue
            if isinstance(result, dict) and result.get("filled"):
                fill_result = result
                break

        status = await self.get_status()
        if fill_result is None:
            return {
                **status,
                "submitted": False,
                "reason": "verification_input_not_found",
            }

        return {
            **status,
            "submitted": True,
            "reason": "verification_code_filled",
            "clicked": bool(fill_result.get("clicked")),
            "target_count": fill_result.get("target_count"),
            "frame_url": fill_result.get("frame_url"),
        }

    async def stop(self, *, keep_page: bool = False) -> None:
        """关闭 page + 断开连接（profile 已落盘）.

        CDP 模式（connect_over_cdp）：只 close 自己开的 page + 断 playwright 连接，
        不 close host Chrome 的 context（launcher 管 host Chrome 生命周期）。
        launch_persistent_context 模式：close context 即杀 Chrome 进程（原行为）。

        ``keep_page=True``：登录确认后调用——断开连接但保留 host Chrome 里的
        已登录 tab（停在 creator home），让操作员直接看到登录结果。仅 CDP 模式
        （含 raw CDP）有效：persistent context 兜底模式下断连接即杀进程，页面
        必然消失，该参数被忽略。
        """
        if self._raw_ws is not None:
            if not keep_page:
                with contextlib.suppress(Exception):
                    if self._raw_target_id:
                        await self._raw_send(
                            "Target.closeTarget",
                            {"targetId": self._raw_target_id},
                            session_id=None,
                        )
            with contextlib.suppress(Exception):
                await self._raw_ws.close()
            self._raw_ws = None
            self._raw_target_id = ""
            self._raw_session_id = ""
        if self._page is not None:
            if keep_page and self._browser is not None:
                # CDP 模式：page 属于 host 常驻 Chrome——只丢引用不 close，
                # tab 留在浏览器里显示已登录页面（playwright 断连不影响它）。
                self._page = None
            else:
                with contextlib.suppress(Exception):
                    await self._page.close()
                self._page = None
        if self._browser is not None:
            # CDP 模式：只关我们 new_context 的（若新建过），default context 不动。
            # _playwright.stop() 断 CDP 连接，host Chrome 继续跑。
            self._browser = None
            self._context = None
        elif self._context is not None:
            with contextlib.suppress(Exception):
                await self._context.close()
            self._context = None
        if self._playwright is not None:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
            self._playwright = None
        await self._release_cdp_hold()
        logger.info("扫码登录会话已关闭: account=%s", self.account_id)

    # ── 内部方法 ──

    def _is_qr_expired(self) -> bool:
        """二维码是否过期：超时未确认即判定过期."""
        if self._confirmed:
            return False
        if self._qr_created_at == 0.0:
            return False
        return (time.time() - self._qr_created_at) > _QR_CONFIRM_TIMEOUT_S

    async def _poll_status_via_page(self) -> None:
        """在页面 JS 上下文发 qrcode/status GET，更新 _code_status.

        headless 下 xhs 前端 JS 不自动轮询 status（实测），故后端主动发。
        用 page.evaluate(fetch(...)) 复用页面 cookie + 签名上下文——后端
        独立调 status 需 x-s/x-t 签名（未实现），走页面是唯一可行路径。
        """
        if self._page is None or not self._qr_id:
            return
        # code 是 status 轮询的校验参数（create 返回）；缺则跳过——create 响应
        # 可能未含 code 字段（envelope 变体），此时只能靠被动 listener。
        if not self._qr_code:
            return
        js = """
        async (params) => {
            const url = `https://edith.xiaohongshu.com/api/sns/web/v1/login/qrcode/status?qr_id=${params.qr_id}&code=${params.code}`;
            try {
                const r = await fetch(url, {credentials: 'include'});
                const j = await r.json();
                return {status: r.status, body: j};
            } catch (e) {
                return {error: String(e)};
            }
        }
        """
        try:
            result = await self._page.evaluate(js, {"qr_id": self._qr_id, "code": self._qr_code})
        except Exception as e:
            logger.warning("poll_status evaluate 失败: %s: %s", type(e).__name__, e)
            return
        if not isinstance(result, dict) or "body" not in result:
            return
        http_status = result.get("status")
        if http_status in (461, 471):
            logger.warning("qrcode/status 被 XHS 安全校验拦截: status=%s", http_status)
            # Do not refresh here: XHS may block the status polling endpoint
            # while the phone-side confirmation is still in progress. Refreshing
            # immediately invalidates the QR the user is confirming. Keep the
            # last known state and let cookie detection or normal timeout decide.
            return
        body = result["body"]
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            return
        code_status = data.get("code_status") if isinstance(data, dict) else None
        # xhs www 站实际返回 code_status（下划线），非 codeStatus（驼峰）——实测确认。
        # 兼容驼峰写法以防 envelope 变体。
        if code_status is None:
            code_status = data.get("codeStatus")
        if isinstance(code_status, int):
            self._code_status = code_status
            if code_status == _CODE_EXPIRED:
                self._force_refresh_qr = True
                return
            if code_status == _CODE_CONFIRMED:
                login_info = data.get("login_info") or {}
                if isinstance(login_info, dict):
                    self._login_info = login_info

    async def _wait_for_existing_login(self, timeout: float) -> bool:
        """Return True when the profile is already logged in on xiaohongshu.com."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._qr_id:
                return False
            if await self._looks_logged_in():
                return True
            await asyncio.sleep(_EXISTING_LOGIN_POLL_S)
        return False

    async def _looks_logged_in(self) -> bool:
        """Detect a *creator-ready* login without forcing a QR-code flow.

        Only the creator access token counts. Feed page text (发布/通知/消息/我)
        must not short-circuit QR — a www-only session renders the feed while
        Creator Center still returns 401 and explore never paints a login QR.
        """
        if self._context is None:
            return False
        try:
            cookies = await self._context.cookies([_EXPLORE_URL, "https://creator.xiaohongshu.com"])
        except Exception as e:
            logger.debug("读取 XHS 登录 cookie 失败: %s", e)
            return False

        cookie_names = {
            str(cookie.get("name") or "")
            for cookie in cookies
            if isinstance(cookie, dict) and bool(cookie.get("value"))
        }
        is_logged_in, _signals, _reason = _cookie_names_mean_logged_in(cookie_names)
        return is_logged_in

    async def _cookie_names_from_context(self) -> set[str]:
        if self._context is None:
            return set()
        try:
            cookies = await self._context.cookies([_EXPLORE_URL, "https://creator.xiaohongshu.com"])
        except Exception as e:
            logger.debug("读取 cookie 名失败: %s", e)
            return set()
        return {
            str(cookie.get("name") or "")
            for cookie in cookies
            if isinstance(cookie, dict) and bool(cookie.get("value"))
        }

    async def _confirm_existing_creator_login(
        self, *, already_warmed: bool = False
    ) -> dict[str, Any]:
        """Mark session confirmed when creator access token is present."""
        self._confirmed = True
        self._code_status = _CODE_CONFIRMED
        logger.info(
            "扫码登录已跳过：profile 已具备创作者中心登录态 account=%s",
            self.account_id,
        )
        if not already_warmed:
            await self._warm_creator_session()
        await self.stop(keep_page=True)
        _detach_session_if_current(self)
        return {
            "status": "confirmed",
            "qr_id": "",
            "url": "",
            "account_id": self.account_id,
        }

    async def _clear_partial_login_cookies(self) -> int:
        """Drop www SSO cookies that block the explore login QR modal.

        Returns the number of cookies deleted.
        """
        if self._context is None:
            return 0
        try:
            cookies = await self._context.cookies()
        except Exception as e:
            logger.debug("列举 cookie 以清理半登录态失败: %s", e)
            return 0
        deleted = 0
        for cookie in cookies:
            if not isinstance(cookie, dict):
                continue
            name = str(cookie.get("name") or "")
            if (
                name not in _PARTIAL_WWW_AUTH_COOKIE_NAMES
                and name not in _CREATOR_LOGIN_COOKIE_NAMES
            ):
                continue
            try:
                await self._context.clear_cookies(
                    name=name,
                    domain=cookie.get("domain"),
                    path=cookie.get("path") or "/",
                )
                deleted += 1
            except TypeError:
                # Older playwright: clear_cookies() clears all — last resort.
                with contextlib.suppress(Exception):
                    await self._context.clear_cookies()
                    return -1
            except Exception as e:
                logger.debug("删除 cookie %s 失败: %s", name, e)
        if deleted:
            logger.info(
                "已清理半登录 cookie 以强制展示扫码浮层: account=%s count=%s",
                self.account_id,
                deleted,
            )
        return deleted

    async def _refresh_qr(self) -> dict[str, Any]:
        """刷新二维码：重新 goto explore 页触发新的 qrcode/create.

        Raises:
            LoginError: 刷新失败（未收到 qrcode/create 响应）。失败时关闭
                context，使会话进入"无 context"终态——下次 get_status 返回
                waiting/空 qr，前端可据此重调 start() 重开，避免 zombie 会话。
        """
        if self._page is None:
            raise LoginError("无法刷新二维码：页面已关闭")

        # 重置状态，等新的 qrcode/create。
        self._qr_id = ""
        self._qr_url = ""
        self._code_status = _CODE_WAITING
        self._login_info = {}
        self._force_refresh_qr = False

        logger.info("刷新二维码: account=%s", self.account_id)
        try:
            await self._goto_explore()

            qr_data = await self._wait_for_qr_ready(timeout=_QR_CREATE_WAIT_S)
            if qr_data is None:
                raise LoginError("刷新二维码失败：未找到登录二维码")
        except LoginError:
            # 显式 LoginError：关 context 后原样抛出（保留具体错误信息）。
            await self.stop()
            raise
        except Exception as e:
            # goto/网络异常等：关 context 后包成 LoginError，与 start() 失败契约一致
            # （route 只 catch LoginError → 503，否则裸 Exception 会变 500）。
            await self.stop()
            raise LoginError(f"刷新二维码失败：{type(e).__name__}: {e}") from e

        self._qr_id = qr_data["qr_id"]
        self._qr_url = qr_data["url"]
        self._qr_created_at = time.time()
        return {
            "qr_id": self._qr_id,
            "url": self._qr_url,
            "account_id": self.account_id,
        }

    async def _wait_for_qr_create(self, timeout: float) -> dict[str, Any] | None:
        """等 qrcode/create 响应到达（_on_response 填充 self._qr_id）."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._qr_id and self._qr_url:
                return {"qr_id": self._qr_id, "url": self._qr_url}
            await asyncio.sleep(_QR_READY_POLL_S)
        return None

    async def _submit_raw_verification_code(self, code: str) -> dict[str, Any]:
        fill_result = await self._raw_fill_verification_code(code)
        status = await self.get_status()
        if not isinstance(fill_result, dict) or not fill_result.get("filled"):
            return {
                **status,
                "submitted": False,
                "reason": "verification_input_not_found",
            }

        return {
            **status,
            "submitted": True,
            "reason": "verification_code_filled",
            "clicked": bool(fill_result.get("clicked")),
            "target_count": fill_result.get("target_count"),
            "frame_url": fill_result.get("frame_url"),
        }

    async def _raw_fill_verification_code(self, code: str) -> dict[str, Any] | None:
        expression = f"({_VERIFICATION_CODE_FILL_SCRIPT.strip()})({json.dumps(code)})"
        result = await self._raw_eval(expression)
        return result if isinstance(result, dict) else None

    async def _wait_for_qr_ready(self, timeout: float) -> dict[str, Any] | None:
        """Wait until a QR is available from network response or rendered DOM.

        Raises ``LoginError`` immediately when the explore page is redirected to
        the XHS security-block shell (IP risk / shield), so callers do not fall
        through to the generic "QR not found" message.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            security_error = await self._detect_security_restriction()
            if security_error:
                raise LoginError(security_error)

            if self._qr_id and self._qr_url:
                return {"qr_id": self._qr_id, "url": self._qr_url}

            qr_image = await self._extract_qr_image_from_dom()
            if qr_image:
                self._qr_id = self._qr_id or f"dom-{int(time.time() * 1000)}"
                self._qr_url = qr_image
                self._qr_created_at = time.time()
                logger.info("从 XHS 页面 DOM 提取到登录二维码: account=%s", self.account_id)
                return {"qr_id": self._qr_id, "url": self._qr_url}

            await asyncio.sleep(_QR_READY_POLL_S)

        # Final diagnosis for a clearer operator-facing error.
        security_error = await self._detect_security_restriction()
        if security_error:
            raise LoginError(security_error)
        return None

    async def _extract_qr_image_from_dom(self) -> str:
        """Return the rendered login QR image data URL when XHS skips create capture."""
        if self._page is None:
            return ""
        try:
            result = await self._page.evaluate(_QR_IMAGE_EXTRACT_SCRIPT)
        except Exception as e:
            logger.debug("读取 XHS DOM 二维码失败: %s", e)
            return ""
        if not isinstance(result, str):
            return ""
        result = result.strip()
        if not result:
            return ""
        if result.startswith("data:image/") or "qrcode" in result.lower():
            return result
        return ""

    def _should_try_raw_cdp(self) -> bool:
        return _should_try_raw_cdp_endpoint(self.cdp_endpoint)

    async def _start_raw_cdp(self) -> dict[str, Any]:
        """Start QR login through a minimal raw CDP client.

        This avoids Playwright's CDP browser bootstrap, which can stall when a
        container reaches host Chrome through a TCP forwarder even though raw CDP
        messages work.
        """
        if self._raw_ws is not None:
            await self.stop()
        self._raw_target_id = ""
        self._raw_session_id = ""
        await self._raw_connect()
        target = await self._raw_send(
            "Target.createTarget", {"url": "about:blank"}, session_id=None
        )
        self._raw_target_id = str(target.get("targetId") or "")
        attached = await self._raw_send(
            "Target.attachToTarget",
            {"targetId": self._raw_target_id, "flatten": True},
            session_id=None,
        )
        self._raw_session_id = str(attached.get("sessionId") or "")
        await self._raw_send("Page.enable")
        await self._raw_send("Runtime.enable")
        await self._raw_send("Network.enable")

        # Creator-first: if access-token already present, skip QR entirely.
        if await self._raw_has_strong_cookie():
            self._confirmed = True
            self._code_status = _CODE_CONFIRMED
            await self._raw_send("Page.navigate", {"url": _CREATOR_HOME_URL})
            await asyncio.sleep(1.0)
            await self.stop(keep_page=True)
            _detach_session_if_current(self)
            return {
                "status": "confirmed",
                "qr_id": "",
                "url": "",
                "account_id": self.account_id,
            }

        # www_only: try creator home warm-up before clearing cookies (less risk).
        await self._raw_send("Page.navigate", {"url": _CREATOR_HOME_URL})
        await asyncio.sleep(_CREATOR_WARMUP_SETTLE_S)
        if await self._raw_has_strong_cookie():
            self._confirmed = True
            self._code_status = _CODE_CONFIRMED
            await self.stop(keep_page=True)
            _detach_session_if_current(self)
            logger.info("raw CDP creator warm minted access token account=%s", self.account_id)
            return {
                "status": "confirmed",
                "qr_id": "",
                "url": "",
                "account_id": self.account_id,
            }

        # Still no creator token — clear partial www SSO so explore paints QR.
        cleared = await self._raw_clear_partial_login_cookies()
        if cleared:
            logger.info(
                "raw CDP 已清理半登录 cookie 以强制扫码: account=%s count=%s",
                self.account_id,
                cleared,
            )
        await self._raw_send("Page.navigate", {"url": _EXPLORE_URL})

        qr_data = await self._raw_wait_for_qr(timeout=_QR_CREATE_WAIT_S)
        if qr_data is None:
            # One recovery if www cookies reminted on navigate.
            cleared_again = await self._raw_clear_partial_login_cookies()
            logger.info(
                "raw CDP 首次未找到二维码，二次清理后重试: account=%s cleared=%s",
                self.account_id,
                cleared_again,
            )
            await self._raw_send("Page.navigate", {"url": _EXPLORE_URL})
            qr_data = await self._raw_wait_for_qr(timeout=_QR_CREATE_WAIT_S)
        if qr_data is None:
            await self.stop()
            raise LoginError(
                f"启动扫码登录失败：{_QR_CREATE_WAIT_S:.0f}s 内未找到登录二维码。"
                "常见原因：小红书 IP/环境风控（300012）、半登录态未清干净或页面变化。"
                "请切换家庭宽带或手机热点后稍后再试。"
            )
        return {
            "qr_id": qr_data["qr_id"],
            "url": qr_data["url"],
            "account_id": self.account_id,
        }

    async def _raw_connect(self) -> None:
        import websockets

        endpoint = await _resolve_cdp_connect_endpoint(self.cdp_endpoint)
        parsed = urlparse(self.cdp_endpoint)
        host = (parsed.hostname or "").strip()
        headers: dict[str, str] = {}
        # Chrome 144+ rejects the CDP WebSocket when the Host header is a
        # non-IP hostname (e.g. host.containers.internal) — 500 "Host header is
        # specified and is not an IP address or localhost". get_account_cdp_endpoint
        # already resolves host.containers.internal to its IP, and when the host
        # IS an IP/literal we must NOT override Host (the library sends the IP,
        # which Chrome accepts). Only override Host for a genuinely non-IP
        # hostname, and even then the lib's own netloc Host may still win on
        # websockets>=14 — so the IP-resolved path is the one that works.
        if parsed.port and host and host not in {"127.0.0.1", "localhost", "::1"}:
            try:
                import ipaddress

                ipaddress.ip_address(host)
            except ValueError:
                headers = {"Host": f"127.0.0.1:{parsed.port}"}
        try:
            self._raw_ws = await websockets.connect(
                endpoint,
                additional_headers=headers,
                open_timeout=5,
            )
        except TypeError:
            self._raw_ws = await websockets.connect(
                endpoint,
                extra_headers=headers,
                open_timeout=5,
            )

    async def _raw_send(
        self, method: str, params: dict[str, Any] | None = None, *, session_id: str | None = ""
    ) -> dict[str, Any]:
        if self._raw_ws is None:
            raise LoginError("raw CDP 未连接")
        self._raw_msg_id += 1
        msg_id = self._raw_msg_id
        payload: dict[str, Any] = {"id": msg_id, "method": method}
        if params:
            payload["params"] = params
        sid = self._raw_session_id if session_id == "" else session_id
        if sid:
            payload["sessionId"] = sid
        await self._raw_ws.send(json.dumps(payload))
        while True:
            raw = await asyncio.wait_for(self._raw_ws.recv(), timeout=10)
            message = json.loads(raw)
            if message.get("id") != msg_id:
                continue
            if "error" in message:
                raise LoginError(f"raw CDP {method} 失败: {message['error']}")
            result = message.get("result")
            return result if isinstance(result, dict) else {}

    async def _raw_eval(self, expression: str) -> Any:
        source = expression.strip()
        if source.startswith("() =>") or source.startswith("async () =>"):
            source = f"({source})()"
        result = await self._raw_send(
            "Runtime.evaluate",
            {
                "expression": source,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        remote = result.get("result") if isinstance(result, dict) else None
        if isinstance(remote, dict):
            return remote.get("value")
        return None

    async def _raw_wait_for_qr(self, timeout: float) -> dict[str, Any] | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            result = await self._raw_eval(_QR_IMAGE_EXTRACT_SCRIPT)
            if isinstance(result, str) and result.startswith("data:image/"):
                self._qr_id = self._qr_id or f"dom-{int(time.time() * 1000)}"
                self._qr_url = result
                self._qr_created_at = time.time()
                return {"qr_id": self._qr_id, "url": self._qr_url}
            await asyncio.sleep(_QR_READY_POLL_S)
        return None

    async def _get_raw_status(self) -> dict[str, Any]:
        if self._is_qr_expired():
            await self._raw_send("Page.navigate", {"url": _EXPLORE_URL})
            refreshed = await self._raw_wait_for_qr(timeout=_QR_CREATE_WAIT_S)
            if refreshed:
                return {
                    "status": "expired",
                    "qr_id": refreshed["qr_id"],
                    "url": refreshed["url"],
                    "account_id": self.account_id,
                }

        if await self._raw_has_strong_cookie():
            self._confirmed = True
            self._code_status = _CODE_CONFIRMED
            # 与 playwright-CDP confirmed 分支一致：保留 host Chrome 里的已登录
            # tab（不发 Target.closeTarget），只断 ws，会话自摘出注册表。
            await self.stop(keep_page=True)
            _detach_session_if_current(self)
            return {
                "status": "confirmed",
                "qr_id": self._qr_id,
                "url": "",
                "account_id": self.account_id,
            }

        # www_only: 扫码确实写入了 www 登录态（web_session+id_token），但本环境
        # Chrome CDP 模式从不 mint access-token-creator.* cookie（小红书改版 /
        # persistent 差异）。此时以 creator 页面证据兜底判定：导航到 creator home，
        # 若页面显示已登录 dashboard（发布笔记/数据看板/笔记管理等）即视为登录成功。
        # 与 _inspect_profile_login_status_raw 的页面证据 fallback 一致。
        if await self._raw_warm_creator_for_confirm():
            self._confirmed = True
            self._code_status = _CODE_CONFIRMED
            logger.info("raw CDP creator 页面证据确认登录成功 account=%s", self.account_id)
            await self.stop(keep_page=True)
            _detach_session_if_current(self)
            return {
                "status": "confirmed",
                "qr_id": self._qr_id,
                "url": "",
                "account_id": self.account_id,
            }

        page_state = await self._raw_login_page_state()
        if page_state.get("verification_required") or page_state.get("scanned"):
            self._code_status = _CODE_SCANNED
            return {
                "status": "scanned",
                "qr_id": self._qr_id,
                "url": "",
                "account_id": self.account_id,
                "verification_required": bool(page_state.get("verification_required")),
            }
        if page_state.get("qr_expired"):
            return {
                "status": "expired",
                "qr_id": self._qr_id,
                "url": self._qr_url,
                "account_id": self.account_id,
            }
        return {
            "status": "waiting",
            "qr_id": self._qr_id,
            "url": self._qr_url,
            "account_id": self.account_id,
        }

    async def _probe_login_page_state(self) -> dict[str, Any]:
        """Read login-page state through the active CDP transport.

        Playwright-CDP and raw-CDP must use the same browser-side probe. In
        particular, verification is evidence from a visible, enabled input;
        page copy alone is not enough to show the verification prompt.
        """
        try:
            if self._raw_ws is not None:
                result = await self._raw_eval(_LOGIN_PAGE_STATE_SCRIPT)
            elif self._page is not None:
                result = await self._page.evaluate(_LOGIN_PAGE_STATE_SCRIPT)
            else:
                return {}
        except Exception as e:
            logger.debug("读取扫码页面状态失败: %s", e)
            return {}
        return result if isinstance(result, dict) else {}

    async def _raw_login_page_state(self) -> dict[str, Any]:
        """Compatibility wrapper for the raw-CDP status path."""
        return await self._probe_login_page_state()

    async def _raw_has_strong_cookie(self) -> bool:
        try:
            result = await self._raw_send("Network.getCookies", {"urls": _LOGIN_STATUS_URLS})
        except Exception as e:
            logger.debug("raw CDP 读取 cookie 失败: %s", e)
            return False
        cookies = result.get("cookies") if isinstance(result, dict) else None
        if not isinstance(cookies, list):
            return False
        names = {
            str(cookie.get("name") or "")
            for cookie in cookies
            if isinstance(cookie, dict) and bool(cookie.get("value"))
        }
        is_logged_in, _signals, _reason = _cookie_names_mean_logged_in(names)
        return is_logged_in

    async def _raw_warm_creator_for_confirm(self) -> bool:
        """Best-effort: navigate current raw-CDP target to Creator home and check
        whether the page shows a logged-in creator dashboard (page evidence).

        Raw-CDP QR login writes the www session (web_session+id_token) but in this
        deployment Chrome never mints an ``access-token-creator.*`` cookie, so the
        cookie-only check in ``_raw_has_strong_cookie`` under-reports success. The
        creator page itself is the authoritative signal (same as
        ``_raw_creator_page_is_ready``). Never raises; returns True only when the
        loaded creator page is verified logged-in.
        """
        try:
            await self._raw_send("Page.navigate", {"url": _CREATOR_HOME_URL})
            # Give the creator SPA a window to render + run its SSO/boot.
            await asyncio.sleep(_CREATOR_WARMUP_SETTLE_S)
            state = await self._raw_eval(_CREATOR_PAGE_STATUS_SCRIPT)
            if _creator_page_state_is_ready(state):
                return True
            # SPA may still be booting; one more probe after a short settle.
            await asyncio.sleep(_CREATOR_WARMUP_SETTLE_S)
            state = await self._raw_eval(_CREATOR_PAGE_STATUS_SCRIPT)
            return _creator_page_state_is_ready(state)
        except Exception as e:
            logger.debug("raw CDP creator 页面证据探测失败 account=%s: %s", self.account_id, e)
            return False

    async def _raw_clear_partial_login_cookies(self) -> int:
        """Delete www/creator auth cookies via CDP so explore shows the QR shell.

        Uses ``Network.deleteCookies`` / ``Storage.getCookies`` (browser-level).
        Returns the number of cookies deleted.
        """
        try:
            result = await self._raw_send("Storage.getCookies", session_id=None)
        except Exception as e:
            logger.debug("raw CDP Storage.getCookies 失败: %s", e)
            try:
                result = await self._raw_send("Network.getCookies", {"urls": _LOGIN_STATUS_URLS})
            except Exception as e2:
                logger.debug("raw CDP Network.getCookies 失败: %s", e2)
                return 0
        cookies = result.get("cookies") if isinstance(result, dict) else None
        if not isinstance(cookies, list):
            return 0
        targets = _PARTIAL_WWW_AUTH_COOKIE_NAMES | _CREATOR_LOGIN_COOKIE_NAMES
        deleted = 0
        for cookie in cookies:
            if not isinstance(cookie, dict):
                continue
            name = str(cookie.get("name") or "")
            if name not in targets or not cookie.get("value"):
                continue
            domain = str(cookie.get("domain") or "")
            path = str(cookie.get("path") or "/")
            params: dict[str, Any] = {"name": name}
            if domain:
                params["domain"] = domain
            if path:
                params["path"] = path
            try:
                await self._raw_send("Network.deleteCookies", params, session_id=None)
                deleted += 1
            except Exception:
                # Some CDP versions require the page session for Network.*.
                with contextlib.suppress(Exception):
                    await self._raw_send("Network.deleteCookies", params)
                    deleted += 1
        return deleted

    async def _warm_creator_session(self) -> None:
        """Best-effort visit to Creator Center after www QR login succeeds.

        www login alone often leaves only ``web_session``/``id_token``. Creator
        stats and note manager need ``access-token-creator.xiaohongshu.com``,
        which the creator origin sets when a valid SSO session loads its home.
        Failures here must never undo an already-confirmed login.
        """
        if self._page is None:
            return
        try:
            await self._page.goto(
                _CREATOR_HOME_URL,
                wait_until="domcontentloaded",
                timeout=15_000,
            )
            # Give the creator SPA a brief window to mint auth cookies.
            await asyncio.sleep(_CREATOR_WARMUP_SETTLE_S)
            logger.info("creator session warm-up finished: account=%s", self.account_id)
        except Exception as e:
            logger.info(
                "creator session warm-up skipped for account=%s: %s",
                self.account_id,
                e,
            )

    async def _ensure_login_modal(self) -> None:
        """Open the www scan-login overlay when explore is already partially logged in.

        After IP-risk recovery the profile often has ``web_session``+``id_token``
        so explore loads the feed without a QR. Creator Center still needs a
        fresh scan. Clicking the site's own 登录 entry triggers qrcode/create
        or at least paints a DOM QR image we can return to the frontend.
        """
        if self._page is None or self._qr_id:
            return
        existing = await self._extract_qr_image_from_dom()
        if existing:
            return
        for label in ("登录", "登录/注册", "扫码登录"):
            try:
                locator = self._page.get_by_text(label, exact=True).first
                await locator.click(timeout=2_000)
                await asyncio.sleep(_LOGIN_MODAL_CLICK_SETTLE_S)
            except Exception as e:
                logger.debug("打开登录浮层点击 %r 失败: %s", label, e)
                continue
            if self._qr_id or await self._extract_qr_image_from_dom():
                logger.info("已打开小红书登录浮层: account=%s via=%s", self.account_id, label)
                return
        # One more settle for SPA paint after the last click attempt.
        await asyncio.sleep(_LOGIN_MODAL_FINAL_SETTLE_S)

    async def _goto_explore(self) -> None:
        """Navigate to XHS explore without blocking on safety pages forever."""
        if self._page is None:
            raise LoginError("无法打开小红书登录页：页面未初始化")
        try:
            # `commit` returns as soon as the main document response starts.
            # XHS safety pages can leave domcontentloaded pending while the
            # visible tab already shows the block page, so waiting for DOMContentLoaded
            # makes the UI spin even though the outcome is known.
            await self._page.goto(
                _EXPLORE_URL,
                wait_until="commit",
                timeout=_EXPLORE_GOTO_TIMEOUT_MS,
            )
        except Exception as e:
            security_error = await self._detect_security_restriction()
            if security_error:
                raise LoginError(security_error) from e
            raise

        # Explore often first paints, then soft-redirects to /website-login/error
        # (error_code=300012 IP at risk). Poll briefly so we fail with the real
        # shield message instead of a generic "QR not found" timeout.
        deadline = time.time() + _SECURITY_REDIRECT_SETTLE_S
        while time.time() < deadline:
            security_error = await self._detect_security_restriction()
            if security_error:
                raise LoginError(security_error)
            await asyncio.sleep(_EXPLORE_POLL_S)

        security_error = await self._detect_security_restriction()
        if security_error:
            raise LoginError(security_error)

    async def _detect_security_restriction(self) -> str | None:
        """Return an actionable error when XHS redirects to a safety block page."""
        if self._page is None:
            return None

        current_url = str(getattr(self._page, "url", "") or "")
        parsed = urlparse(current_url)
        if _SECURITY_ERROR_PATH in parsed.path:
            query = parse_qs(parsed.query)
            error_code = (query.get("error_code") or [""])[0]
            error_msg = (query.get("error_msg") or query.get("verifyMsg") or [""])[0]
            try:
                from urllib.parse import unquote

                error_msg = unquote(error_msg)
            except Exception:
                pass
            if error_code == "300012" or "IP at risk" in error_msg or "secure network" in error_msg:
                return (
                    "小红书安全限制：当前网络/IP 被判定存在风险（error_code=300012），"
                    "无法生成登录二维码。请切换到更安全的网络（家庭宽带/手机热点），"
                    "或以 headed Chrome 在本机扫码后重试；云主机/机房 IP 常被拦截。"
                )
            detail = f"error_code={error_code}" if error_code else "未知错误码"
            if error_msg:
                detail = f"{detail}, {error_msg}"
            return (
                f"小红书安全限制：无法生成登录二维码（{detail}）。"
                "请在浏览器中完成安全校验或切换网络后重试。"
            )

        try:
            title = await self._page.title()
        except Exception:
            title = ""
        body_snip = ""
        try:
            body_snip = await self._page.evaluate(
                "() => (document.body && document.body.innerText || '').slice(0, 240)"
            )
        except Exception:
            body_snip = ""
        body_text = str(body_snip or "")
        if (
            "安全限制" in str(title)
            or "安全限制" in body_text
            or "IP at risk" in body_text
            or "Switch to a secure network" in body_text
        ):
            return (
                "小红书安全限制：当前浏览器页面被安全校验拦截（IP/环境风险），"
                "无法生成登录二维码。请切换安全网络，"
                "或在可访问小红书的本机浏览器完成扫码后重试。"
            )
        return None

    async def _on_response(self, response: Any) -> None:
        """响应拦截器：匹配 qrcode/create + qrcode/status，解析 envelope."""
        try:
            url = response.url
            if _QR_CREATE_PATH in url and response.request.method == "POST":
                await self._handle_qr_create(response)
            elif _QR_STATUS_PATH in url and response.request.method == "GET":
                await self._handle_qr_status(response)
        except Exception as e:
            # 拦截器异常不能冒泡到 playwright 事件循环（会断后续响应处理）。
            # _handle_* 内部已吞掉良性解析失败（bad JSON / 缺字段），能走到这里的是
            # 真正意外异常——按 spec 不静默，记 WARNING（DEBUG 在生产等于吞掉）。
            logger.warning("qrcode 响应拦截异常: %s: %s", type(e).__name__, e)

    async def _handle_qr_create(self, response: Any) -> None:
        """解析 qrcode/create 响应，取 data.{qr_id, url, code}."""
        try:
            body = await response.json()
        except Exception:
            return
        # xhs envelope: {success, code, data: {qr_id, code, url, multi_flag}}
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            return
        qr_id = data.get("qr_id") or data.get("qrid") or ""
        url = data.get("url") or ""
        # code 是 status 轮询的校验参数（_poll_status_via_page 用）
        self._qr_code = str(data.get("code") or "")
        if qr_id and url:
            self._qr_id = str(qr_id)
            self._qr_url = str(url)
            self._qr_created_at = time.time()
            logger.debug("拦截到 qrcode/create: qr_id=%s", self._qr_id)

    async def _handle_qr_status(self, response: Any) -> None:
        """解析 qrcode/status 响应，取 data.code_status + data.login_info.

        被动 listener 路径（headless 下 xhs 前端 JS 不自动轮询，此路径通常不触发；
        _poll_status_via_page 主动轮询是主路径）。保留作 headed 模式或回退用。
        """
        try:
            body = await response.json()
        except Exception:
            return
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            return
        # xhs www 站实际返回 code_status（下划线），兼容 codeStatus（驼峰）
        code_status = data.get("code_status")
        if code_status is None:
            code_status = data.get("codeStatus")
        if isinstance(code_status, int):
            self._code_status = code_status
            if code_status == _CODE_EXPIRED:
                self._force_refresh_qr = True
                logger.debug("拦截到 qrcode/status: code_status=%s", code_status)
                return
            if code_status == _CODE_CONFIRMED:
                login_info = data.get("login_info") or {}
                if isinstance(login_info, dict):
                    self._login_info = login_info
            logger.debug("拦截到 qrcode/status: code_status=%s", code_status)

    async def _apply_stealth(self, context: BrowserContext) -> None:
        """复用 publisher 的 stealth 注入逻辑.

        XHS shield 检测 webdriver/CDP/permissions 等指纹，仅隐藏
        navigator.webdriver 不够。playwright-stealth 注入全套反检测 init
        script（plugins/webgl/vendor/permissions/ua 等）。可选依赖，未装则
        fallback 到手动 webdriver 隐藏。
        """
        try:
            from playwright_stealth import Stealth

            # 不覆盖 platform/languages（stealth 默认 Win32/en-US 与真实 Linux UA +
            # zh-CN locale 冲突，指纹不一致反而是自动化特征）。只启用检测隐藏类。
            await Stealth(
                navigator_platform=False,
                navigator_languages=False,
                navigator_languages_override=("zh-CN", "zh"),
            ).apply_stealth_async(context)
            logger.info("playwright-stealth 已应用 (login session)")
        except Exception as e:
            logger.warning(
                "playwright-stealth 不可用，fallback 手动隐藏: %s: %s", type(e).__name__, e
            )
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', { get: () => false });"
            )


# ── 会话注册表：模块级 dict[account_id, XhsLoginSession] ──
#
# 支持多账号并发扫码（每账号独立 Chrome+profile）。同一账号已有进行中会话
# 则 start 复用（返回现有 qr_id+url），避免重复开 Chrome 抢同一 profile。
# stop 显式关闭；进程退出时残留会话由 Chrome 自身 GC 回收（profile 已落盘）。

_sessions: dict[str, XhsLoginSession] = {}


def _detach_session_if_current(session: XhsLoginSession) -> None:
    """登录确认后会话自摘：登录态已落盘 profile、tab 已交接给 host Chrome。

    仅当注册表里仍是本对象时才 pop（并发下可能已被新会话覆盖）。
    摘除后同账号下次 start() 新建会话；profile 仍有效则 start() 经
    _wait_for_existing_login 短路再次 confirmed（幂等）。
    """
    if _sessions.get(session.account_id) is session:
        _sessions.pop(session.account_id, None)


def get_session(account_id: str) -> XhsLoginSession | None:
    """获取账号的进行中登录会话（无则返回 None）."""
    return _sessions.get(account_id)


def get_or_create_session(
    account_id: str, profile_path: str, cdp_endpoint: str = ""
) -> XhsLoginSession:
    """获取或创建账号的登录会话.

    同一 account_id 已有会话则复用（即使 profile_path 不同——以 account_id
    为准，避免重复开 Chrome 抢同一 profile 锁）。
    """
    session = _sessions.get(account_id)
    if session is None:
        session = XhsLoginSession(
            account_id=account_id,
            profile_path=profile_path,
            cdp_endpoint=cdp_endpoint,
            allow_persistent_fallback=False,
        )
        _sessions[account_id] = session
    return session


async def stop_session(account_id: str) -> bool:
    """关闭并移除账号的登录会话. Returns True if a session was stopped."""
    session = _sessions.pop(account_id, None)
    if session is None:
        return False
    await session.stop()
    return True


async def stop_all_sessions() -> None:
    """关闭所有进行中的登录会话（进程退出时调用）."""
    sessions = list(_sessions.values())
    _sessions.clear()
    for session in sessions:
        with contextlib.suppress(Exception):
            await session.stop()


async def _raw_creator_page_is_ready(session: XhsLoginSession) -> bool:
    """Check existing Creator Center targets without changing browser state."""
    try:
        targets_result = await session._raw_send("Target.getTargets", session_id=None)
    except Exception as e:
        logger.debug("raw CDP 枚举创作者中心页面失败 account=%s: %s", session.account_id, e)
        return False

    target_infos = targets_result.get("targetInfos") if isinstance(targets_result, dict) else None
    if not isinstance(target_infos, list):
        return False

    for target_info in target_infos:
        if not isinstance(target_info, dict) or target_info.get("type") != "page":
            continue
        target_id = str(target_info.get("targetId") or "")
        target_url = str(target_info.get("url") or "")
        if not target_id or urlparse(target_url).hostname != "creator.xiaohongshu.com":
            continue

        target_session_id = ""
        try:
            attached = await session._raw_send(
                "Target.attachToTarget",
                {"targetId": target_id, "flatten": True},
                session_id=None,
            )
            target_session_id = str(attached.get("sessionId") or "")
            if not target_session_id:
                continue
            evaluated = await session._raw_send(
                "Runtime.evaluate",
                {
                    "expression": f"({_CREATOR_PAGE_STATUS_SCRIPT.strip()})()",
                    "returnByValue": True,
                    "awaitPromise": True,
                },
                session_id=target_session_id,
            )
            remote_result = evaluated.get("result") if isinstance(evaluated, dict) else None
            state = remote_result.get("value") if isinstance(remote_result, dict) else None
            if _creator_page_state_is_ready(state):
                return True
        except Exception as e:
            logger.debug("raw CDP 读取创作者中心页面证据失败 account=%s: %s", session.account_id, e)
        finally:
            if target_session_id:
                with contextlib.suppress(Exception):
                    await session._raw_send(
                        "Target.detachFromTarget",
                        {"sessionId": target_session_id},
                        session_id=None,
                    )
    return False


async def _playwright_creator_page_is_ready(contexts: list[Any], account_id: str) -> bool:
    """Check existing Playwright pages without navigating or creating tabs."""
    for context in contexts:
        pages = getattr(context, "pages", None) or []
        for page in pages:
            try:
                state = await page.evaluate(_CREATOR_PAGE_STATUS_SCRIPT)
            except Exception as e:
                logger.debug("Playwright 读取创作者中心页面证据失败 account=%s: %s", account_id, e)
                continue
            if _creator_page_state_is_ready(state):
                return True
    return False


async def _inspect_profile_login_status_raw(account_id: str, cdp_endpoint: str) -> dict[str, Any]:
    """Read durable profile login state through raw browser-level CDP."""
    session = XhsLoginSession(account_id=account_id, profile_path="", cdp_endpoint=cdp_endpoint)
    try:
        await session._raw_connect()
        result = await session._raw_send("Storage.getCookies", session_id=None)
        cookies = result.get("cookies") if isinstance(result, dict) else None
        if not isinstance(cookies, list):
            if await _raw_creator_page_is_ready(session):
                return _creator_page_status(account_id)
            return {
                "account_id": account_id,
                "status": "unknown",
                "is_logged_in": False,
                "reason": "cookies_unavailable",
            }

        cookie_names = {
            str(cookie.get("name") or "")
            for cookie in cookies
            if isinstance(cookie, dict)
            and bool(cookie.get("value"))
            and "xiaohongshu.com" in str(cookie.get("domain") or "")
        }
        is_logged_in, signals, reason = _cookie_names_mean_logged_in(cookie_names)
        if is_logged_in:
            return {
                "account_id": account_id,
                "status": "logged_in",
                "is_logged_in": True,
                "reason": reason,
                "signals": signals,
            }
        if await _raw_creator_page_is_ready(session):
            return _creator_page_status(account_id)
        return {
            "account_id": account_id,
            "status": "logged_in" if is_logged_in else "logged_out",
            "is_logged_in": is_logged_in,
            "reason": reason,
            "signals": signals,
        }
    except Exception as e:
        logger.warning(
            "raw CDP 检查小红书登录状态失败 account=%s: %s: %s",
            account_id,
            type(e).__name__,
            e,
        )
        reason = "cdp_port_down" if "ECONNREFUSED" in str(e) else "cdp_unreachable"
        return {
            "account_id": account_id,
            "status": "unavailable",
            "is_logged_in": False,
            "reason": reason,
            "message": str(e),
        }
    finally:
        if session._raw_ws is not None:
            with contextlib.suppress(Exception):
                await session._raw_ws.close()
            session._raw_ws = None


async def inspect_profile_login_status(account_id: str, cdp_endpoint: str) -> dict[str, Any]:
    """Return the durable login state for an account's Chrome profile.

    This read-only probe is used by the settings page. It must not start a QR
    flow, navigate tabs, or close the host Chrome instance.

    ``logged_in`` requires either the creator access token
    (``access-token-creator.xiaohongshu.com``) or verified evidence from an
    already-open Creator Center page. The www pair (``web_session`` +
    ``id_token``) alone is ``www_only`` / not logged in — it commonly survives
    after creator SSO expiry and previously caused a false green "已登录" while
    Creator Center APIs returned 401.
    """
    if not cdp_endpoint:
        return {
            "account_id": account_id,
            "status": "unavailable",
            "is_logged_in": False,
            "reason": "cdp_unavailable",
        }

    if _should_try_raw_cdp_endpoint(cdp_endpoint):
        return await _inspect_profile_login_status_raw(account_id, cdp_endpoint)

    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        return {
            "account_id": account_id,
            "status": "unknown",
            "is_logged_in": False,
            "reason": "playwright_missing",
            "message": str(e),
        }

    playwright = await async_playwright().start()
    try:
        try:
            connect_endpoint = await _resolve_cdp_connect_endpoint(cdp_endpoint)
            browser = await playwright.chromium.connect_over_cdp(connect_endpoint, timeout=5000)
        except Exception as e:
            logger.warning(
                "连接小红书登录状态 CDP 失败 account=%s: %s: %s",
                account_id,
                type(e).__name__,
                e,
            )
            reason = "cdp_port_down" if "ECONNREFUSED" in str(e) else "cdp_unreachable"
            return {
                "account_id": account_id,
                "status": "unavailable",
                "is_logged_in": False,
                "reason": reason,
                "message": str(e),
            }

        contexts = browser.contexts
        if not contexts:
            return {
                "account_id": account_id,
                "status": "unknown",
                "is_logged_in": False,
                "reason": "no_browser_context",
            }

        cookies = await contexts[0].cookies(_LOGIN_STATUS_URLS)
        cookie_names = {
            str(cookie.get("name") or "")
            for cookie in cookies
            if isinstance(cookie, dict) and bool(cookie.get("value"))
        }
        is_logged_in, signals, reason = _cookie_names_mean_logged_in(cookie_names)
        if is_logged_in:
            return {
                "account_id": account_id,
                "status": "logged_in",
                "is_logged_in": True,
                "reason": reason,
                "signals": signals,
            }
        if await _playwright_creator_page_is_ready(contexts, account_id):
            return _creator_page_status(account_id)
        return {
            "account_id": account_id,
            "status": "logged_in" if is_logged_in else "logged_out",
            "is_logged_in": is_logged_in,
            "reason": reason,
            "signals": signals,
        }
    except Exception as e:
        logger.warning(
            "检查小红书登录状态失败 account=%s: %s: %s",
            account_id,
            type(e).__name__,
            e,
        )
        return {
            "account_id": account_id,
            "status": "unknown",
            "is_logged_in": False,
            "reason": "check_failed",
            "message": str(e),
        }
    finally:
        with contextlib.suppress(Exception):
            await playwright.stop()
