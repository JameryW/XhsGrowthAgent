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
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
_LOGIN_COOKIE_NAMES = {
    "web_session",
    "id_token",
    "access-token-creator.xiaohongshu.com",
}
_STRONG_LOGIN_COOKIE_NAMES = {
    "id_token",
    "access-token-creator.xiaohongshu.com",
}
_LOGIN_STATUS_URLS = [_EXPLORE_URL, "https://creator.xiaohongshu.com"]

# codeStatus 语义（spike + reverse-engineered CLI 源码确认）。
_CODE_WAITING = 0  # 待扫
_CODE_SCANNED = 1  # 已扫待确认
_CODE_CONFIRMED = 2  # 已确认登录
_CODE_EXPIRED = 3  # 已失效/需刷新

# 二维码等待确认的超时（秒）。超时未确认 → 判定过期，自动刷新。
# XHS qrcode/status 也会返回 code_status=3 表示当前二维码不可继续确认。
_QR_CONFIRM_TIMEOUT_S = 120.0

# 拿到 qrcode/create 响应后的等待窗口（秒）。超时仍未收到 → 启动失败
# （可能 headless 被 shield 拦或网络异常）。
_QR_CREATE_WAIT_S = 30.0
_ALREADY_LOGIN_CHECK_S = 3.0

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

    def __init__(self, account_id: str, profile_path: str, cdp_endpoint: str = "") -> None:
        self.account_id = account_id
        self.profile_path = profile_path
        # host 真实 Chrome 的 CDP endpoint（connect_over_cdp 用）。空则回退
        # launch_persistent_context（playwright bundled chromium，会被 xhs 471 风控）。
        self.cdp_endpoint = cdp_endpoint
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

    @property
    def qr_id(self) -> str:
        return self._qr_id

    @property
    def qr_url(self) -> str:
        return self._qr_url

    async def start(self) -> dict[str, Any]:
        """启动 headless Chrome，拦截 qrcode/create，返回 ``{qr_id, url}``.

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
                try:
                    self._browser = await self._playwright.chromium.connect_over_cdp(
                        self.cdp_endpoint
                    )
                except Exception as e:
                    raise LoginError(
                        f"连接 host Chrome CDP 失败: {self.cdp_endpoint} ({type(e).__name__}: {e})"
                        "——确认 launcher 已启动该账号 Chrome（chrome-profiles.sh start）"
                    ) from e
                contexts = self._browser.contexts
                self._context = contexts[0] if contexts else await self._browser.new_context()
                logger.info("扫码登录连 host Chrome: %s", self.cdp_endpoint)
            else:
                # 回退：launch_persistent_context（playwright bundled chromium）。
                # 会被 xhs 471 风控——仅 cdp_endpoint 不可用时兜底。
                Path(self.profile_path).mkdir(parents=True, exist_ok=True)
                headless = os.getenv("XHS_LOGIN_HEADLESS", "0") == "1"
                self._context = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=self.profile_path,
                    headless=headless,
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

            # 开 explore 页——登录浮层自动触发 qrcode/create。
            await self._page.goto(_EXPLORE_URL, wait_until="domcontentloaded", timeout=45000)

            # If the persistent profile is already logged in, XHS does not show
            # the login layer and therefore will not call qrcode/create. Treat
            # that as a successful login instead of making the UI spin for 30s.
            if await self._wait_for_existing_login(timeout=_ALREADY_LOGIN_CHECK_S):
                self._confirmed = True
                self._code_status = _CODE_CONFIRMED
                logger.info("扫码登录已跳过：profile 已登录 account=%s", self.account_id)
                await self.stop()
                return {
                    "status": "confirmed",
                    "qr_id": "",
                    "url": "",
                    "account_id": self.account_id,
                }

            # 等 qrcode/create 响应到达（_on_response 填充 self._qr_id）。
            qr_data = await self._wait_for_qr_create(timeout=_QR_CREATE_WAIT_S)
            if qr_data is None:
                raise LoginError(
                    f"启动扫码登录失败：{_QR_CREATE_WAIT_S:.0f}s 内未收到 qrcode/create 响应"
                    "（可能被 XHS shield 拦截或网络异常）"
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
            # 兜底资源回收：登录态已落盘 profile，headless Chrome 无需再常驻。
            # 前端若未显式调 stop 也不会泄漏——confirmed 即关闭 context。
            # stop() 幂等，前端后续调 stop 仍安全（no-op）。
            await self.stop()

        return {
            "status": status,
            "qr_id": self._qr_id,
            "url": self._qr_url if status != "confirmed" else "",
            "account_id": self.account_id,
        }

    async def submit_verification_code(self, code: str) -> dict[str, Any]:
        """Fill a numeric verification code into the current CDP login page.

        The verification UI belongs to XHS' live browser page, not this API. We
        therefore fill the code inside the active page/iframe and then return the
        latest QR login status so the frontend can keep polling.
        """
        code = code.strip()
        if not code.isdigit() or not (4 <= len(code) <= 8):
            raise LoginError("验证码必须是 4-8 位数字")
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

    async def stop(self) -> None:
        """关闭 page + 断开连接（profile 已落盘）.

        CDP 模式（connect_over_cdp）：只 close 自己开的 page + 断 playwright 连接，
        不 close host Chrome 的 context（launcher 管 host Chrome 生命周期）。
        launch_persistent_context 模式：close context 即杀 Chrome 进程（原行为）。
        """
        if self._page is not None:
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
            logger.warning("poll_status evaluate 失败: %s", e)
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
            await asyncio.sleep(0.2)
        return False

    async def _looks_logged_in(self) -> bool:
        """Detect an existing login state without forcing a QR-code flow."""
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
        if cookie_names & _STRONG_LOGIN_COOKIE_NAMES:
            return True

        has_login_cookie = bool(cookie_names & _LOGIN_COOKIE_NAMES)
        if not has_login_cookie:
            return False

        if self._page is None:
            return True
        try:
            text = await self._page.evaluate("document.body.innerText || ''")
        except Exception as e:
            logger.debug("读取 XHS 登录页面文本失败: %s", e)
            return False
        if not isinstance(text, str):
            return False
        return all(keyword in text for keyword in ("发布", "通知", "消息", "我"))

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
            await self._page.goto(_EXPLORE_URL, wait_until="domcontentloaded", timeout=45000)

            qr_data = await self._wait_for_qr_create(timeout=_QR_CREATE_WAIT_S)
            if qr_data is None:
                raise LoginError("刷新二维码失败：未收到 qrcode/create 响应")
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
            await asyncio.sleep(0.3)
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
            logger.warning("qrcode 响应拦截异常: %s", e)

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
            logger.warning("playwright-stealth 不可用，fallback 手动隐藏: %s", e)
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', { get: () => false });"
            )


# ── 会话注册表：模块级 dict[account_id, XhsLoginSession] ──
#
# 支持多账号并发扫码（每账号独立 Chrome+profile）。同一账号已有进行中会话
# 则 start 复用（返回现有 qr_id+url），避免重复开 Chrome 抢同一 profile。
# stop 显式关闭；进程退出时残留会话由 Chrome 自身 GC 回收（profile 已落盘）。

_sessions: dict[str, XhsLoginSession] = {}


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
            account_id=account_id, profile_path=profile_path, cdp_endpoint=cdp_endpoint
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


async def inspect_profile_login_status(account_id: str, cdp_endpoint: str) -> dict[str, Any]:
    """Return the durable login state for an account's Chrome profile.

    This read-only probe is used by the settings page. It must not start a QR
    flow, navigate tabs, or close the host Chrome instance. A strong creator/web
    auth cookie is required to report ``logged_in``; anonymous cookies such as
    ``web_session`` alone are not enough for publishing.
    """
    if not cdp_endpoint:
        return {
            "account_id": account_id,
            "status": "unavailable",
            "is_logged_in": False,
            "reason": "cdp_unavailable",
        }

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
            browser = await playwright.chromium.connect_over_cdp(cdp_endpoint, timeout=5000)
        except Exception as e:
            logger.warning("连接小红书登录状态 CDP 失败 account=%s: %s", account_id, e)
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
        signals = sorted(cookie_names & _STRONG_LOGIN_COOKIE_NAMES)
        is_logged_in = bool(signals)
        return {
            "account_id": account_id,
            "status": "logged_in" if is_logged_in else "logged_out",
            "is_logged_in": is_logged_in,
            "reason": "strong_cookie" if is_logged_in else "missing_strong_cookie",
            "signals": signals,
        }
    except Exception as e:
        logger.warning("检查小红书登录状态失败 account=%s: %s", account_id, e)
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
