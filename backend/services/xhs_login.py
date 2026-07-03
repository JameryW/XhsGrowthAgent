"""小红书扫码登录 service — headless Chrome 拦截 qrcode 接口方案.

路径 B'（spike 已验证）：
1. ``launch_persistent_context(user_data_dir=profile, headless=True)`` 开
   ``https://www.xiaohongshu.com/explore``，登录浮层自动触发
   ``POST /api/sns/web/v1/login/qrcode/create``。
2. ``page.on("response")`` 拦截该 XHR，取 ``data.url``（二维码编码字符串）+
   ``data.qr_id``（轮询 key）。
3. 同一 listener 也拦 ``qrcode/status`` 的 GET 响应，缓存最新 ``codeStatus``
   （0=待扫 / 1=已扫待确认 / 2=已确认）。
4. ``codeStatus==2`` 即登录成功，cookie 已由 ``launch_persistent_context``
   写入 ``user_data_dir``（profile 持久化），关闭 context 即可——launcher
   常驻 CDP Chrome 复用同一 profile，发布时无需再扫码。
5. 二维码过期（status 返回非 0/1/2 的码或超时无 2）→ 重新 ``goto`` 刷新
   ``qrcode/create``，返回新 ``qr_id``+``url``。

每账号独立 ``XhsLoginSession`` + 独立 Chrome + 独立 profile，多账号并发互不
干扰。同一账号已有进行中会话则 ``start`` 复用现有会话（返回当前 qr_id+url）。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
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

# codeStatus 语义（spike + reverse-engineered CLI 源码确认）。
_CODE_WAITING = 0  # 待扫
_CODE_SCANNED = 1  # 已扫待确认
_CODE_CONFIRMED = 2  # 已确认登录

# 二维码等待确认的超时（秒）。超时未确认 → 判定过期，自动刷新。
# spike 未精确捕获失效码值，用超时兜底（xhs 二维码实测约 60-120s 失效）。
_QR_CONFIRM_TIMEOUT_S = 120.0

# 拿到 qrcode/create 响应后的等待窗口（秒）。超时仍未收到 → 启动失败
# （可能 headless 被 shield 拦或网络异常）。
_QR_CREATE_WAIT_S = 30.0


class LoginError(Exception):
    """扫码登录流程错误（启动失败 / playwright 未装 / 超时等）。"""


class XhsLoginSession:
    """管理一次账号的扫码登录会话.

    生命周期：
        ``start()`` → headless Chrome 开 explore 页，拦截 qrcode/create，
        返回 ``{qr_id, url}``。前端用 ``qrcode`` JS 库渲染 url 为二维码。
        ``get_status()`` → 返回当前 ``codeStatus`` 映射的状态
        （waiting/scanned/confirmed/expired）。expired 时自动刷新二维码。
        ``stop()`` → 关闭 context（profile 已落盘）。

    登录态靠 ``launch_persistent_context(user_data_dir=profile)`` 自动持久化
    到 ``account.chrome_profile_path``——无需单独导出 cookie。
    """

    def __init__(self, account_id: str, profile_path: str) -> None:
        self.account_id = account_id
        self.profile_path = profile_path
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        # playwright async_playwright().start() handle — kept so stop() can .stop() it.
        self._playwright: Any = None
        # 当前二维码信息（start 时填充，刷新时更新）。
        self._qr_id: str = ""
        self._qr_url: str = ""
        # 最新 codeStatus（listener 异步更新）。
        self._code_status: int = _CODE_WAITING
        # codeStatus==2 时缓存的登录信息（含 session/user_id）。
        self._login_info: dict[str, Any] = {}
        self._confirmed = False
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

        Path(self.profile_path).mkdir(parents=True, exist_ok=True)

        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise LoginError("playwright 未安装。运行: pip install -e '.[browser]'") from e

        self._started_at = time.time()

        # launch_persistent_context owns the Chrome lifecycle — this is a
        # one-shot login browser, NOT the always-on CDP Chrome the launcher
        # manages. Closing the context kills it. Login state persists in
        # profile_path for the launcher's CDP Chrome to reuse.
        try:
            self._playwright = await async_playwright().start()
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=self.profile_path,
                headless=True,
                args=[
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )

            # 反自动化检测：复用 publisher 的 stealth 注入逻辑。XHS shield 检测
            # webdriver/CDP/permissions 等指纹，仅隐藏 navigator.webdriver 不够。
            # playwright-stealth 是可选依赖，未装则 fallback 到手动 webdriver 隐藏。
            await self._apply_stealth(self._context)

            existing_pages = self._context.pages
            self._page = existing_pages[0] if existing_pages else await self._context.new_page()

            # 注册响应拦截器：监听 qrcode/create + qrcode/status。
            self._page.on("response", self._on_response)

            # 开 explore 页——登录浮层自动触发 qrcode/create。
            await self._page.goto(_EXPLORE_URL, wait_until="domcontentloaded", timeout=45000)

            # 等 qrcode/create 响应到达（_on_response 填充 self._qr_id）。
            qr_data = await self._wait_for_qr_create(timeout=_QR_CREATE_WAIT_S)
            if qr_data is None:
                raise LoginError(
                    f"启动扫码登录失败：{_QR_CREATE_WAIT_S:.0f}s 内未收到 qrcode/create 响应"
                    "（可能被 XHS shield 拦截或网络异常）"
                )
        except LoginError:
            # 显式 LoginError（playwright 未装 / 超时未收到响应）：关 context 后原样抛出。
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

    async def stop(self) -> None:
        """关闭 context（profile 已落盘）."""
        if self._page is not None:
            with contextlib.suppress(Exception):
                await self._page.close()
            self._page = None
        if self._context is not None:
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
        """解析 qrcode/create 响应，取 data.{qr_id, url}."""
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
        if qr_id and url:
            self._qr_id = str(qr_id)
            self._qr_url = str(url)
            self._qr_created_at = time.time()
            logger.debug("拦截到 qrcode/create: qr_id=%s", self._qr_id)

    async def _handle_qr_status(self, response: Any) -> None:
        """解析 qrcode/status 响应，取 data.codeStatus + data.login_info."""
        try:
            body = await response.json()
        except Exception:
            return
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            return
        code_status = data.get("codeStatus")
        if isinstance(code_status, int):
            self._code_status = code_status
            if code_status == _CODE_CONFIRMED:
                login_info = data.get("login_info") or {}
                if isinstance(login_info, dict):
                    self._login_info = login_info
            logger.debug("拦截到 qrcode/status: codeStatus=%s", code_status)

    async def _apply_stealth(self, context: BrowserContext) -> None:
        """复用 publisher 的 stealth 注入逻辑.

        XHS shield 检测 webdriver/CDP/permissions 等指纹，仅隐藏
        navigator.webdriver 不够。playwright-stealth 注入全套反检测 init
        script（plugins/webgl/vendor/permissions/ua 等）。可选依赖，未装则
        fallback 到手动 webdriver 隐藏。
        """
        try:
            from playwright_stealth import Stealth  # type: ignore[import-not-found]

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


def get_or_create_session(account_id: str, profile_path: str) -> XhsLoginSession:
    """获取或创建账号的登录会话.

    同一 account_id 已有会话则复用（即使 profile_path 不同——以 account_id
    为准，避免重复开 Chrome 抢同一 profile 锁）。
    """
    session = _sessions.get(account_id)
    if session is None:
        session = XhsLoginSession(account_id=account_id, profile_path=profile_path)
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
