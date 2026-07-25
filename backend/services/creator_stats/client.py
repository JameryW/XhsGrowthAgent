"""Authenticated fetch client for creator-center statistics APIs.

Product surface: https://creator.xiaohongshu.com/statistics/account/v2
Underlying JSON APIs live under creator.xiaohongshu.com/api/galaxy/...

Transport is injectable so unit tests never need live cookies.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import parse_qs, quote, urlsplit

import httpx

from backend.services.creator_stats.normalize import extract_note_items, normalize_bundle
from backend.services.creator_stats.types import CreatorStatsBundle
from backend.services.xhs_api import XHSApiEndpoints

logger = logging.getLogger("xhs_growth.creator_stats.client")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


# Creator-center statistics surface (product UI)
CREATOR_STATS_PAGE = "https://creator.xiaohongshu.com/statistics/account/v2"

# Galaxy/datacenter endpoints used by the account statistics page.
# Paths are reverse-engineered and may change; client isolates that risk.
ACCOUNT_OVERVIEW_PATH = "/api/galaxy/v2/creator/datacenter/account/base"
CREATOR_PROFILE_PATH = "/api/galaxy/user/info"
# Home personal_info carries cumulative fans_count; account/base only has
# period rise/net-rise fan metrics (涨粉), not total followers.
CREATOR_PERSONAL_INFO_PATH = "/api/galaxy/creator/home/personal_info"
CREATOR_HOME_PAGE = "https://creator.xiaohongshu.com/new/home"
# This is the signed endpoint that the Creator Center's Note Manager itself
# calls.  It is intentionally distinct from the legacy cookie/httpx endpoint:
# current creator-center requests require browser-generated x-s/x-t headers.
NOTE_LIST_PATH = "/api/galaxy/v2/creator/note/user/posted"
LEGACY_NOTE_LIST_PATH = "/api/galaxy/creator/datacenter/note/analyze/list"
# Optional aggregate insight surfaces loaded by the statistics dashboard.
AUDIENCE_SOURCE_PATH = "/api/galaxy/v2/creator/datacenter/audience/source/account"
AUDIENCE_PERIODS_PATH = "/api/galaxy/v2/creator/datacenter/audience/view/periods"
NOTE_DETAIL_PATH = "/api/galaxy/creator/data/note_detail_new"
NOTE_DETAIL_PAGE = "https://creator.xiaohongshu.com/statistics/note-detail"
NOTE_BASE_PATH = "/api/galaxy/creator/datacenter/note/base"
NOTE_AUDIENCE_TREND_PATH = "/api/galaxy/creator/datacenter/note/analyze/audience/trend"
NOTE_AUDIENCE_SOURCE_PATH = "/api/galaxy/creator/datacenter/note/audience/source"
NOTE_AUDIENCE_PROFILE_PATH = "/api/galaxy/creator/datacenter/note/audience/source/detail"
NOTE_DETAIL_RESPONSE_PATHS = (
    NOTE_BASE_PATH,
    NOTE_AUDIENCE_TREND_PATH,
    NOTE_AUDIENCE_SOURCE_PATH,
    NOTE_AUDIENCE_PROFILE_PATH,
)
CREATOR_NOTE_MANAGER_PAGE = "https://creator.xiaohongshu.com/new/note-manager"

# Known date_type values on account overview (reverse-engineered):
# 1 ≈ 7d window, 2 ≈ 30d window. Longer periods fall back to 2 (not 1).
_PERIOD_DATE_TYPE: dict[str, int] = {
    "7d": 1,
    "7": 1,
    "1w": 1,
    "week": 1,
    "weekly": 1,
    "30d": 2,
    "30": 2,
    "1m": 2,
    "month": 2,
    "monthly": 2,
    # API has no dedicated 90d type in known surface — use longest window (2)
    "90d": 2,
    "90": 2,
    "3m": 2,
    "quarter": 2,
}


def period_to_date_type(period: str | None) -> int:
    """Map product period strings to creator-center ``date_type`` query param.

    Unknown / empty periods default to 30d (date_type=2). Never map long
    windows (e.g. 90d) to the 7d type.
    """
    p = (period or "30d").strip().lower().replace(" ", "")
    return _PERIOD_DATE_TYPE.get(p, 2)


def normalize_period(period: str | None) -> str:
    """Canonical period label stored on account overview rows."""
    p = (period or "30d").strip().lower().replace(" ", "")
    if p in ("7d", "7", "1w", "week", "weekly"):
        return "7d"
    if p in ("90d", "90", "3m", "quarter"):
        return "90d"
    return "30d"


class CreatorStatsFetchError(Exception):
    """Remote fetch failed (auth, network, or API error)."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class Transport(Protocol):
    """Minimal HTTP transport protocol for mockability."""

    async def get(
        self, url: str, *, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any] | list[Any] | None]:
        """Return (status_code, parsed_json_or_none)."""
        ...

    async def aclose(self) -> None:
        """Release transport-backed resources (CDP connection, etc.)."""
        ...


class HttpxTransport:
    """Default httpx-based transport (cookie-driven, fallback / tests)."""

    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout

    async def get(
        self, url: str, *, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any] | list[Any] | None]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.get(url, headers=headers, params=params or {})
            except httpx.TimeoutException as e:
                raise CreatorStatsFetchError("creator stats request timed out") from e
            except httpx.RequestError as e:
                raise CreatorStatsFetchError(f"creator stats network error: {e}") from e
            try:
                body: Any = resp.json()
            except Exception:
                body = None
            return resp.status_code, body

    async def aclose(self) -> None:
        """No-op for httpx (per-request clients)."""
        return None


class CdpTransport:
    """Read Creator Center data through its already-logged-in browser page.

    Creator Center signs each API call in page JavaScript (``x-s``, ``x-t``
    and related trace headers).  A standalone ``httpx`` or Playwright
    ``APIRequestContext`` request does not have those signatures, even when it
    shares the profile cookie jar.  We therefore open a disposable Note Manager
    tab and capture the page's *own* successful account/profile/note responses.  This
    keeps the authenticated request in the real Chrome profile and never reads
    or serializes its cookies/signatures.
    """

    def __init__(
        self,
        cdp_endpoint: str,
        *,
        timeout: float = 30.0,
        detail_timeout: float = 120.0,
        request_delay: tuple[float, float] | None = None,
    ):
        self.cdp_endpoint = cdp_endpoint
        self._timeout = timeout
        self._detail_timeout = max(1.0, float(detail_timeout))
        # Random pause between per-note page visits.  Back-to-back navigations
        # look like a bot to XHS risk control; jitter keeps the crawl human-paced.
        if request_delay is None:
            request_delay = (
                _env_float("CREATOR_STATS_REQUEST_DELAY_MIN_S", 2.0),
                _env_float("CREATOR_STATS_REQUEST_DELAY_MAX_S", 6.0),
            )
        delay_min = max(0.0, float(request_delay[0]))
        delay_max = max(delay_min, float(request_delay[1]))
        self._request_delay = (delay_min, delay_max)
        # 均匀的短停顿本身也是节拍器式的机器特征——以小概率插入一次"走神"
        # 长停顿打乱节奏（人刷创作者中心会被消息/倒水打断）。
        self._long_pause_chance = max(
            0.0, min(1.0, _env_float("CREATOR_STATS_LONG_PAUSE_CHANCE", 0.08))
        )
        long_min = max(0.0, _env_float("CREATOR_STATS_LONG_PAUSE_MIN_S", 15.0))
        long_max = max(long_min, _env_float("CREATOR_STATS_LONG_PAUSE_MAX_S", 45.0))
        self._long_pause = (long_min, long_max)
        # 轻量轮：以小概率本轮只看概览+列表，不做逐篇详情/正文深入——人不会
        # 每次都把每篇笔记翻到底，"每轮必全量深入"本身是可识别的固定流程。
        self._light_run_chance = max(
            0.0, min(1.0, _env_float("CREATOR_STATS_LIGHT_RUN_CHANCE", 0.15))
        )
        # 逐篇跳过：即使在深入轮，也以该概率跳过单篇笔记的详情/正文访问
        # （被跳过的笔记下轮仍会被增量过滤器选中），避免"候选全扫"的机器人
        # 完备性特征。
        self._enrich_skip_chance = max(
            0.0, min(1.0, _env_float("CREATOR_STATS_ENRICH_SKIP_CHANCE", 0.15))
        )
        # 入口随机化：以该概率先打开创作者主页（真人通常从主页点进数据页），
        # 而不是每轮都直接深链到数据统计页——"每次会话都以同一个深链开头"
        # 是可识别的会话模式。
        self._home_entry_chance = max(
            0.0, min(1.0, _env_float("CREATOR_STATS_HOME_ENTRY_CHANCE", 0.5))
        )
        # 翻页提前停止：每翻一页后以该概率停止继续翻——人很少每次都把列表
        # 滚到底；被截断的旧笔记下轮仍有机会被翻到。
        self._page_stop_chance = max(
            0.0, min(1.0, _env_float("CREATOR_STATS_PAGE_STOP_CHANCE", 0.15))
        )
        # 数据页浏览噪声：以该概率在数据页上先点一下别的日期范围 Tab 再进
        # 笔记管理——人看数据会切换时间范围对比，"每次进数据页只干一件事"
        # 是固定行为模式。
        self._dashboard_browse_chance = max(
            0.0, min(1.0, _env_float("CREATOR_STATS_DASHBOARD_BROWSE_CHANCE", 0.25))
        )
        # 每轮抓取的节奏基准（在 fetch 开头随机缩放 request_delay 得到）：
        # 有的运行整体偏快、有的偏慢，避免跨运行统一的节奏画像。
        self._run_delay: tuple[float, float] | None = None
        self._playwright: Any = None
        self._browser: Any = None
        self._fetch_lock = asyncio.Lock()

    def _new_run_pace(self) -> None:
        """Roll this run's pacing baseline (0.7-1.6× the configured range)."""
        delay_min, delay_max = self._request_delay
        scale = random.uniform(0.7, 1.6)
        self._run_delay = (delay_min * scale, delay_max * scale)

    async def _pace(self) -> None:
        """Sleep a random interval before the next page visit.

        大部分是本轮节奏基准区间内的短停顿；以小概率插入 15-45s 的长
        停顿，避免爬行节奏成为均匀的节拍器。
        """
        delay_min, delay_max = self._run_delay or self._request_delay
        if delay_max <= 0:
            return
        if random.random() < self._long_pause_chance:
            long_min, long_max = self._long_pause
            if long_max > 0:
                await asyncio.sleep(random.uniform(long_min, long_max))
            return
        await asyncio.sleep(random.uniform(delay_min, delay_max))

    async def _human_touch(self, page: Any) -> None:
        """Simulate small random mouse movements on the page.

        长时间无任何鼠标轨迹的"幽灵浏览"是风控可识别的会话特征；真人浏览
        创作者中心时指针会无意识移动。移动本身带随机步数/落点，不产生新的
        固定模式。页面对象为测试替身或无鼠标能力时静默跳过。
        """
        mouse = getattr(page, "mouse", None)
        if mouse is None:
            return
        with contextlib.suppress(Exception):
            viewport = getattr(page, "viewport_size", None)
            width = int(viewport.get("width", 1280)) if isinstance(viewport, dict) else 1280
            height = int(viewport.get("height", 800)) if isinstance(viewport, dict) else 800
            x = random.uniform(0.1, 0.9) * width
            y = random.uniform(0.1, 0.9) * height
            for _ in range(random.randint(1, 3)):
                x = min(max(x + random.uniform(-240.0, 240.0), 8.0), width - 8.0)
                y = min(max(y + random.uniform(-160.0, 160.0), 8.0), height - 8.0)
                await mouse.move(x, y, steps=random.randint(3, 12))
                await asyncio.sleep(random.uniform(0.05, 0.3))

    async def _ensure_browser(self) -> Any:
        if self._browser is not None:
            return self._browser
        try:
            from playwright.async_api import async_playwright  # lazy: optional [browser] extra
        except ImportError as e:
            raise CreatorStatsFetchError(
                "playwright not installed; run: pip install -e '.[browser]'"
            ) from e
        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(self.cdp_endpoint)
        except Exception as e:
            await self._cleanup()
            raise CreatorStatsFetchError(
                f"CDP connect failed: {self.cdp_endpoint} ({type(e).__name__}: {e})"
            ) from e

        if not self._browser.contexts:
            await self._cleanup()
            raise CreatorStatsFetchError("CDP browser has no logged-in browser context")
        return self._browser

    @staticmethod
    async def _wait_for(predicate: Any, timeout: float) -> None:
        """Wait for an in-memory predicate without relying on page internals."""
        deadline = asyncio.get_running_loop().time() + timeout
        while not predicate():
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("timed out waiting for Creator Center response")
            await asyncio.sleep(0.1)

    @staticmethod
    def _page_index(url: str) -> int:
        try:
            # Creator Center has used both page=0 and page=1 as the first page.
            raw = parse_qs(urlsplit(url).query).get("page", ["0"])[0]
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    async def _scrape_public_note_body(
        page: Any,
        note_id: str,
        *,
        xsec_token: str = "",
        xsec_source: str = "pc_creatormng",
        timeout_ms: int = 12_000,
    ) -> str:
        """Read the public explore caption for one note (creator APIs omit body).

        Uses the note's ``xsec_token`` from the posted-list response so the
        public page can resolve without an extra signed feed request.
        """
        note_id = (note_id or "").strip()
        if not note_id or page is None:
            return ""
        url = f"https://www.xiaohongshu.com/explore/{quote(note_id, safe='')}"
        query: list[str] = []
        if xsec_token:
            query.append(f"xsec_token={quote(xsec_token, safe='')}")
        if xsec_source:
            query.append(f"xsec_source={quote(xsec_source, safe='')}")
        if query:
            url = f"{url}?{'&'.join(query)}"
        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=max(1_000, int(timeout_ms)),
        )
        deadline = asyncio.get_running_loop().time() + max(1.0, timeout_ms / 1000.0)
        script = """() => {
            const pick = (sel) => {
                const el = document.querySelector(sel);
                if (!el) return '';
                return (el.innerText || el.textContent || '').trim();
            };
            // Prefer caption containers; avoid comment threads under .note-text.
            return pick('#detail-desc .note-text')
                || pick('.note-content .desc')
                || pick('#detail-desc')
                || pick('.note-content .note-text')
                || pick('.desc');
        }"""
        while asyncio.get_running_loop().time() < deadline:
            try:
                text = await page.evaluate(script)
            except Exception:
                text = ""
            if isinstance(text, str):
                cleaned = text.strip()
                # Drop trailing UI chrome that sometimes rides on the container.
                for marker in ("\n猜你想搜", "\n编辑于", "\n共 ", "\n评论"):
                    if marker in cleaned:
                        cleaned = cleaned.split(marker, 1)[0].strip()
                if cleaned:
                    return cleaned[:4000]
            await asyncio.sleep(0.25)
        return ""

    @staticmethod
    def _validate_creator_response(
        status: int, body: dict[str, Any] | list[Any] | None, *, operation: str
    ) -> None:
        if status in (401, 403):
            raise CreatorStatsFetchError(
                f"creator stats auth failed during {operation}; "
                "re-login the bound Chrome profile to creator.xiaohongshu.com",
                status_code=status,
            )
        if status >= 400:
            raise CreatorStatsFetchError(
                f"creator stats {operation} HTTP {status}", status_code=status
            )
        # Reuse the shared envelope validation so platform error code/message
        # becomes the user-facing sync error instead of a misleading empty list.
        _unwrap_api_body(body)

    @staticmethod
    def _looks_like_login_url(url: str) -> bool:
        path = urlsplit(url or "").path.lower()
        return (
            "/login" in path
            or path.endswith("/login")
            or "website-login" in path
            or "passport" in path
        )

    @staticmethod
    async def _page_shows_login_ui(page: Any) -> bool:
        """Best-effort detection of the Creator Center SMS/QR login shell."""
        try:
            url = str(getattr(page, "url", "") or "")
            if CdpTransport._looks_like_login_url(url):
                return True
            text = await page.evaluate("() => (document.body && document.body.innerText) || ''")
        except Exception:
            return False
        if not isinstance(text, str) or not text.strip():
            return False
        # Match the live creator login shell without treating menu labels as login.
        markers = ("短信登录", "扫码登录", "发送验证码", "请先登录", "登录即同意")
        hits = sum(1 for marker in markers if marker in text)
        return hits >= 2

    @staticmethod
    def _auth_error_from_captured(
        *,
        profile_response: tuple[int, dict[str, Any] | list[Any] | None] | None,
        account_response: tuple[int, dict[str, Any] | list[Any] | None] | None,
        note_responses: dict[int, tuple[int, dict[str, Any] | list[Any] | None]],
        login_ui: bool,
    ) -> CreatorStatsFetchError | None:
        """Map observed auth failures to a clear, actionable fetch error."""
        for label, response in (
            ("creator profile", profile_response),
            ("account overview", account_response),
        ):
            if response is not None and response[0] in (401, 403):
                return CreatorStatsFetchError(
                    f"creator stats auth failed during {label} (HTTP {response[0]}); "
                    "re-login the bound Chrome profile to creator.xiaohongshu.com",
                    status_code=response[0],
                )
        for page_index, response in note_responses.items():
            if response[0] in (401, 403):
                return CreatorStatsFetchError(
                    f"creator stats auth failed during note list page {page_index} "
                    f"(HTTP {response[0]}); re-login the bound Chrome profile "
                    "to creator.xiaohongshu.com",
                    status_code=response[0],
                )
        if login_ui:
            return CreatorStatsFetchError(
                "creator center login page is showing; "
                "re-login the bound Chrome profile (scan QR) before syncing",
                status_code=401,
            )
        return None

    async def fetch_creator_center(
        self,
        *,
        max_pages: int = 50,
        period: str = "30d",
        detail_filter: Callable[[dict[str, Any]], bool] | None = None,
        body_filter: Callable[[dict[str, Any]], bool] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        """Capture overview, public profile, and up to ``max_pages`` native note pages.

        The Note Manager starts at page 0 and loads later pages when its own
        ``div.content`` scroll container reaches the bottom.  We only observe
        those requests; no request headers, cookies, or user content are
        fabricated by this service.

        ``detail_filter`` / ``body_filter`` decide per raw note whether the
        extra detail-page / public-body visits are worth making.  Incremental
        sync passes filters that skip unchanged notes so the crawl does not
        re-visit every note page on every run (risk-control friendly).
        """
        try:
            max_pages = max(1, min(int(max_pages), 50))
        except (TypeError, ValueError):
            max_pages = 50
        period_norm = normalize_period(period)

        async with self._fetch_lock:
            # 每轮换一个节奏基准：本轮整体偏快或偏慢，跨运行无统一节奏。
            self._new_run_pace()
            # 轻量轮：本轮只看概览+列表就离开，不做逐篇详情/正文深入。
            light_run = self._light_run_chance > 0 and random.random() < self._light_run_chance
            if light_run:
                logger.info("creator stats light run: skipping per-note enrichment this round")
            # 每轮的深入预算也随机缩放——会话总时长不聚类在固定上限。
            detail_budget = self._detail_timeout * random.uniform(0.7, 1.3)
            browser = await self._ensure_browser()
            context = browser.contexts[0]
            page = await context.new_page()
            account_response: tuple[int, dict[str, Any] | list[Any] | None] | None = None
            profile_response: tuple[int, dict[str, Any] | list[Any] | None] | None = None
            personal_info_response: tuple[int, dict[str, Any] | list[Any] | None] | None = None
            note_responses: dict[int, tuple[int, dict[str, Any] | list[Any] | None]] = {}
            insight_responses: dict[str, tuple[int, dict[str, Any] | list[Any] | None]] = {}
            note_detail_responses: dict[
                str, dict[str, tuple[int, dict[str, Any] | list[Any] | None]]
            ] = {}
            account_ready = asyncio.Event()
            profile_ready = asyncio.Event()
            personal_ready = asyncio.Event()
            first_notes_ready = asyncio.Event()
            auth_failed = asyncio.Event()
            pending: set[asyncio.Task[None]] = set()
            auth_status: int | None = None

            def _record_auth_status(status: int) -> None:
                nonlocal auth_status
                if status in (401, 403):
                    auth_status = status
                    auth_failed.set()

            async def capture(response: Any) -> None:
                nonlocal account_response, profile_response, personal_info_response
                path = urlsplit(response.url).path
                note_id = _note_detail_id(response.url)
                if path not in (
                    ACCOUNT_OVERVIEW_PATH,
                    CREATOR_PROFILE_PATH,
                    CREATOR_PERSONAL_INFO_PATH,
                    NOTE_LIST_PATH,
                    LEGACY_NOTE_LIST_PATH,
                    AUDIENCE_SOURCE_PATH,
                    AUDIENCE_PERIODS_PATH,
                    NOTE_DETAIL_PATH,
                    *NOTE_DETAIL_RESPONSE_PATHS,
                ):
                    return
                try:
                    body: dict[str, Any] | list[Any] | None = await response.json()
                except Exception:
                    body = None
                status = int(getattr(response, "status", 0) or 0)
                if path == ACCOUNT_OVERVIEW_PATH:
                    account_response = (status, body)
                    _record_auth_status(status)
                    account_ready.set()
                    return
                if path == CREATOR_PROFILE_PATH:
                    profile_response = (status, body)
                    _record_auth_status(status)
                    profile_ready.set()
                    return
                if path == CREATOR_PERSONAL_INFO_PATH:
                    personal_info_response = (status, body)
                    personal_ready.set()
                    return
                if path in (AUDIENCE_SOURCE_PATH, AUDIENCE_PERIODS_PATH, NOTE_DETAIL_PATH):
                    # These are optional enrichment calls.  A permission or
                    # rollout failure must not discard the note snapshot.
                    insight_responses[path] = (status, body)
                    return
                if path in NOTE_DETAIL_RESPONSE_PATHS and note_id:
                    note_detail_responses.setdefault(note_id, {})[path] = (status, body)
                    return
                page_index = self._page_index(response.url)
                note_responses[page_index] = (status, body)
                _record_auth_status(status)
                # First list page may be page=0 or page=1 depending on frontend.
                if page_index in (0, 1) or len(note_responses) == 1:
                    first_notes_ready.set()

            def on_response(response: Any) -> None:
                task = asyncio.create_task(capture(response))
                pending.add(task)
                task.add_done_callback(pending.discard)

            page.on("response", on_response)
            try:
                try:
                    # 入口随机化：真人通常从创作者主页点进数据页，而不是每次
                    # 都直接深链。主页加载顺带带出 personal_info（总粉丝数）。
                    if self._home_entry_chance > 0 and random.random() < self._home_entry_chance:
                        with contextlib.suppress(Exception):
                            await page.goto(
                                CREATOR_HOME_PAGE,
                                wait_until="domcontentloaded",
                                timeout=self._timeout * 1000,
                            )
                            await page.wait_for_timeout(random.uniform(900.0, 2200.0))
                            await self._human_touch(page)
                    # Start at the statistics dashboard: it loads the account
                    # overview request we need, then use the site's own menu
                    # transition to Note Manager so the signed note request is
                    # generated by the same app session.
                    dashboard_url = CREATOR_STATS_PAGE
                    if period_norm != "30d":
                        dashboard_url = (
                            f"{CREATOR_STATS_PAGE}?date_type={period_to_date_type(period_norm)}"
                        )
                    await page.goto(
                        dashboard_url,
                        wait_until="domcontentloaded",
                        timeout=self._timeout * 1000,
                    )
                    # SPA login shell may paint after domcontentloaded.  停顿
                    # 时长抖动——固定毫秒数是时序特征。
                    with contextlib.suppress(Exception):
                        await page.wait_for_timeout(random.uniform(700.0, 1600.0))
                    await self._human_touch(page)
                    # Fail fast when the profile is logged out of Creator Center.
                    if await self._page_shows_login_ui(page) or auth_failed.is_set():
                        login_ui = await self._page_shows_login_ui(page)
                        auth_err = self._auth_error_from_captured(
                            profile_response=profile_response,
                            account_response=account_response,
                            note_responses=note_responses,
                            login_ui=login_ui or auth_failed.is_set(),
                        )
                        if auth_err is not None:
                            raise auth_err
                    # 数据页浏览噪声：以一定概率先点一下别的日期范围 Tab
                    # （人看数据会切换时间范围对比）。Tab 文案可能随改版变
                    # 化，逐个候选尝试、失败静默。
                    if (
                        self._dashboard_browse_chance > 0
                        and random.random() < self._dashboard_browse_chance
                    ):
                        for tab_text in ("近7天", "7天", "近 7 天"):
                            try:
                                await page.get_by_text(tab_text, exact=True).click(timeout=1500)
                                with contextlib.suppress(Exception):
                                    await page.wait_for_timeout(random.uniform(600.0, 1500.0))
                                await self._human_touch(page)
                                break
                            except Exception:
                                continue
                    try:
                        await page.get_by_text("笔记管理", exact=True).click(
                            timeout=min(15_000, int(self._timeout * 1000))
                        )
                    except Exception:
                        # A direct route is a compatibility fallback for a
                        # Creator Center navigation redesign.  The account
                        # response may already have been captured above.
                        await page.goto(
                            CREATOR_NOTE_MANAGER_PAGE,
                            wait_until="domcontentloaded",
                            timeout=self._timeout * 1000,
                        )
                        with contextlib.suppress(Exception):
                            await page.wait_for_timeout(random.uniform(700.0, 1600.0))
                        await self._human_touch(page)
                        if await self._page_shows_login_ui(page) or auth_failed.is_set():
                            login_ui = await self._page_shows_login_ui(page)
                            auth_err = self._auth_error_from_captured(
                                profile_response=profile_response,
                                account_response=account_response,
                                note_responses=note_responses,
                                login_ui=login_ui or auth_failed.is_set(),
                            )
                            if auth_err is not None:
                                raise auth_err from None
                except CreatorStatsFetchError:
                    raise
                except Exception as e:
                    raise CreatorStatsFetchError(
                        f"creator note manager did not load: {type(e).__name__}: {e}"
                    ) from e

                async def _wait_initial_data() -> None:
                    await account_ready.wait()
                    await first_notes_ready.wait()

                data_ready = asyncio.create_task(_wait_initial_data())
                auth_ready = asyncio.create_task(auth_failed.wait())
                try:
                    done, pending_wait = await asyncio.wait(
                        {data_ready, auth_ready},
                        timeout=self._timeout,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in pending_wait:
                        task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await asyncio.gather(*pending_wait, return_exceptions=True)
                    if (
                        auth_ready in done
                        and auth_failed.is_set()
                        and not (account_ready.is_set() and first_notes_ready.is_set())
                    ):
                        login_ui = await self._page_shows_login_ui(page)
                        auth_err = self._auth_error_from_captured(
                            profile_response=profile_response,
                            account_response=account_response,
                            note_responses=note_responses,
                            login_ui=login_ui,
                        )
                        if auth_err is not None:
                            raise auth_err
                    if data_ready not in done:
                        raise TimeoutError("timed out waiting for creator stats responses")
                    # Propagate wait exceptions if any.
                    await data_ready
                except TimeoutError as e:
                    login_ui = await self._page_shows_login_ui(page)
                    auth_err = self._auth_error_from_captured(
                        profile_response=profile_response,
                        account_response=account_response,
                        note_responses=note_responses,
                        login_ui=login_ui,
                    )
                    if auth_err is not None:
                        raise auth_err from e
                    detail_bits = [
                        f"account_ready={account_ready.is_set()}",
                        f"notes_ready={first_notes_ready.is_set()}",
                        f"note_pages={sorted(note_responses)}",
                    ]
                    if auth_status is not None:
                        detail_bits.append(f"auth_http={auth_status}")
                    raise CreatorStatsFetchError(
                        "creator note manager did not return account and first note page "
                        f"({', '.join(detail_bits)}); verify the profile is logged in to "
                        "creator.xiaohongshu.com",
                        status_code=auth_status,
                    ) from e
                finally:
                    for task in (data_ready, auth_ready):
                        if not task.done():
                            task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await asyncio.gather(data_ready, auth_ready, return_exceptions=True)

                first_note_page = 0 if 0 in note_responses else (1 if 1 in note_responses else None)
                if account_response is None or first_note_page is None:
                    raise CreatorStatsFetchError(
                        "creator note manager returned incomplete initial data"
                    )
                self._validate_creator_response(*account_response, operation="account overview")
                self._validate_creator_response(
                    *note_responses[first_note_page], operation="note list"
                )
                try:
                    await asyncio.wait_for(profile_ready.wait(), timeout=min(2.0, self._timeout))
                except TimeoutError:
                    # Identity data enriches the snapshot but must not discard already-read stats.
                    logger.info("creator profile response was not observed during stats sync")
                if profile_response is not None and profile_response[0] in (401, 403):
                    # Profile is optional for metrics, but 401 is a strong auth signal.
                    logger.warning(
                        "creator profile returned HTTP %s during stats sync",
                        profile_response[0],
                    )

                # The Creator Center app itself knows how to generate a fresh
                # signature for every page. Trigger its infinite-scroll path
                # instead of replaying a stale signed request.
                start_page = first_note_page + 1
                for page_index in range(start_page, start_page + max_pages - 1):
                    # 翻页提前停止：人很少每次都把列表滚到底。每翻一页前掷一次，
                    # 命中就停——被截断的旧笔记下轮仍有机会被翻到。
                    if self._page_stop_chance > 0 and random.random() < self._page_stop_chance:
                        logger.info("creator note list pagination stopped early (human-like)")
                        break
                    previous_pages = len(note_responses)
                    # 翻页也保持人的节奏——连续秒翻列表是明显的机器特征。
                    await self._pace()
                    # 渐进滚动：瞬时 scrollTop=scrollHeight 是典型机器行为。
                    # 分 2-4 段滚动、段间停顿，最后一段才到底触发加载。
                    scroll_steps = random.randint(2, 4)
                    for step in range(scroll_steps):
                        last_step = step == scroll_steps - 1
                        # 偶尔往回滚一下——人看列表会回看上一屏。
                        if not last_step and random.random() < 0.15:
                            with contextlib.suppress(Exception):
                                await page.locator("div.content").evaluate(
                                    """el => {
                                        el.scrollTop = Math.max(
                                            el.scrollTop
                                                - el.clientHeight * (0.3 + Math.random() * 0.5),
                                            0
                                        )
                                        el.dispatchEvent(new Event('scroll', { bubbles: true }))
                                    }"""
                                )
                                await asyncio.sleep(random.uniform(0.2, 0.6))
                        script = (
                            """el => {
                                el.scrollTop = el.scrollHeight
                                el.dispatchEvent(new Event('scroll', { bubbles: true }))
                            }"""
                            if last_step
                            else """el => {
                                el.scrollTop = Math.min(
                                    el.scrollTop + el.clientHeight * (0.6 + Math.random() * 0.8),
                                    el.scrollHeight
                                )
                                el.dispatchEvent(new Event('scroll', { bubbles: true }))
                            }"""
                        )
                        try:
                            await page.locator("div.content").evaluate(script)
                        except Exception as e:
                            logger.debug(
                                "creator note list cannot scroll for page %s: %s", page_index, e
                            )
                            break
                        if not last_step:
                            await asyncio.sleep(random.uniform(0.15, 0.45))
                    else:
                        # All scroll steps completed — wait for the next page.
                        try:
                            await self._wait_for(
                                lambda expected=page_index, before=previous_pages: (
                                    expected in note_responses or len(note_responses) > before
                                ),
                                min(8.0, self._timeout),
                            )
                        except TimeoutError:
                            # No next request is the normal end-of-list condition.
                            break
                        if page_index not in note_responses:
                            break
                        self._validate_creator_response(
                            *note_responses[page_index], operation=f"note list page {page_index}"
                        )
                        next_data = _unwrap_api_body(note_responses[page_index][1])
                        if (isinstance(next_data, dict) and not extract_note_items(next_data)) or (
                            isinstance(next_data, list) and not next_data
                        ):
                            break
                        continue
                    # Scroll evaluate failed — stop paginating.
                    break

                raw_notes: list[dict[str, Any]] = []
                for page_index in sorted(note_responses):
                    _status, body = note_responses[page_index]
                    data = _unwrap_api_body(body)
                    if isinstance(data, dict):
                        # Posted notes API may nest under notes / note_list / list.
                        items = (
                            data.get("notes")
                            or data.get("note_list")
                            or data.get("note_infos")
                            or data.get("list")
                        )
                        if isinstance(items, list):
                            raw_notes.extend(item for item in items if isinstance(item, dict))
                    elif isinstance(data, list):
                        raw_notes.extend(item for item in data if isinstance(item, dict))
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)

                # The note manager list endpoint does not include the audience
                # breakdowns shown on the detail page.  Open each note detail
                # route in the same signed browser session so the page itself
                # issues the four authenticated requests we capture above.
                # Keep a bounded batch: a malformed/slow note must not prevent
                # the account snapshot from being imported.
                detail_deadline = asyncio.get_running_loop().time() + detail_budget
                detail_failures = 0
                detail_candidates: list[str] = []
                if not light_run:
                    for note in raw_notes[:100]:
                        note_id = str(
                            note.get("note_id") or note.get("noteId") or note.get("id") or ""
                        ).strip()
                        if not note_id:
                            continue
                        if detail_filter is not None and not detail_filter(note):
                            continue
                        # 逐篇随机跳过：人翻笔记列表不会每篇都点开，候选全扫
                        # 是机器人的完备性特征；跳过的笔记下轮仍会被过滤器选中。
                        if (
                            self._enrich_skip_chance > 0
                            and random.random() < self._enrich_skip_chance
                        ):
                            continue
                        detail_candidates.append(note_id)
                # 乱序访问：每次以不同顺序浏览笔记详情，避免固定的"新→旧"
                # 访问序列——固定顺序本身是可被风控识别的爬行特征。
                random.shuffle(detail_candidates)
                for visit_order, note_id in enumerate(detail_candidates):
                    remaining = detail_deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        logger.info("note detail enrichment budget exhausted")
                        break
                    if visit_order:
                        await self._pace()
                    try:
                        await page.goto(
                            f"{NOTE_DETAIL_PAGE}?noteId={quote(note_id, safe='')}",
                            wait_until="domcontentloaded",
                            timeout=max(
                                100,
                                min(int(self._timeout * 1000), int(remaining * 1000)),
                            ),
                        )
                        remaining = detail_deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            break
                        # 打开详情页后偶尔动一下鼠标，避免整段会话无指针轨迹。
                        if random.random() < 0.7:
                            await self._human_touch(page)
                        await self._wait_for(
                            lambda current=note_id: (
                                len(note_detail_responses.get(current, {})) >= 2
                            ),
                            min(5.0, self._timeout, remaining),
                        )
                        detail_failures = 0
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.info("note detail enrichment skipped for %s: %s", note_id, exc)
                        detail_failures += 1
                        if detail_failures >= 3:
                            # Repeated failures usually mean risk control or a
                            # dead page — stop instead of hammering the site.
                            logger.warning(
                                "note detail enrichment circuit break after %s "
                                "consecutive failures",
                                detail_failures,
                            )
                            break

                # Wait for response callbacks created by the final navigation
                # before taking the captured payloads out of the local map.
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)

                for index, note in enumerate(raw_notes):
                    note_id = str(
                        note.get("note_id") or note.get("noteId") or note.get("id") or ""
                    ).strip()
                    if note_id:
                        enriched = _note_detail_snapshot(note_detail_responses.get(note_id, {}))
                        if enriched:
                            raw_notes[index] = {**note, **enriched}

                detail_body = insight_responses.get(NOTE_DETAIL_PATH, (0, {}))[1]
                details = _note_detail_map(detail_body)
                if details:
                    for index, note in enumerate(raw_notes):
                        legacy_note_id: Any = (
                            note.get("note_id") or note.get("noteId") or note.get("id")
                        )
                        detail = details.get(str(legacy_note_id))
                        if isinstance(detail, dict):
                            raw_notes[index] = {**note, **detail}

                # Creator list/detail APIs often only expose display_title (and a
                # note_info.desc that equals the title). Full captions live on the
                # public explore page — scrape them with the note's xsec_token.
                body_deadline = asyncio.get_running_loop().time() + min(
                    90.0, max(30.0, float(detail_budget))
                )
                body_failures = 0
                body_empty = 0
                body_candidates: list[int] = []
                if not light_run:
                    for index, note in enumerate(raw_notes[:50]):
                        note_id = str(
                            note.get("note_id") or note.get("noteId") or note.get("id") or ""
                        ).strip()
                        if not note_id:
                            continue
                        title = str(
                            note.get("display_title") or note.get("title") or note.get("desc") or ""
                        ).strip()
                        existing = str(
                            note.get("body_text") or note.get("body") or note.get("desc") or ""
                        ).strip()
                        # Skip when we already have a caption distinct from the title.
                        if existing and existing != title and len(existing) > len(title):
                            continue
                        if body_filter is not None and not body_filter(note):
                            continue
                        if (
                            self._enrich_skip_chance > 0
                            and random.random() < self._enrich_skip_chance
                        ):
                            continue
                        body_candidates.append(index)
                # 乱序访问公开正文页，避免与详情页相同的固定访问序列。
                random.shuffle(body_candidates)
                for visit_order, index in enumerate(body_candidates):
                    remaining = body_deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        logger.info("public note body enrichment budget exhausted")
                        break
                    note = raw_notes[index]
                    note_id = str(
                        note.get("note_id") or note.get("noteId") or note.get("id") or ""
                    ).strip()
                    xsec_token = str(note.get("xsec_token") or note.get("xsecToken") or "").strip()
                    xsec_source = str(
                        note.get("xsec_source") or note.get("xsecSource") or "pc_creatormng"
                    ).strip()
                    if visit_order:
                        await self._pace()
                    # 正文页之间也偶尔动一下鼠标。
                    if random.random() < 0.7:
                        await self._human_touch(page)
                    try:
                        body_text = await self._scrape_public_note_body(
                            page,
                            note_id,
                            xsec_token=xsec_token,
                            xsec_source=xsec_source,
                            timeout_ms=max(1_000, min(12_000, int(remaining * 1000))),
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.info("public note body scrape skipped for %s: %s", note_id, exc)
                        body_failures += 1
                        if body_failures >= 3:
                            logger.warning(
                                "public note body scrape circuit break after %s "
                                "consecutive failures",
                                body_failures,
                            )
                            break
                        continue
                    body_failures = 0
                    if body_text:
                        body_empty = 0
                        raw_notes[index] = {
                            **raw_notes[index],
                            "body_text": body_text,
                            "desc": body_text,
                        }
                    else:
                        body_empty += 1
                        if body_empty >= 5:
                            # A run of empty bodies on the public explore page
                            # usually means risk control is serving a shell page.
                            logger.warning(
                                "public note body scrape circuit break: %s consecutive empty "
                                "results (possible risk control)",
                                body_empty,
                            )
                            break

                # personal_info (total fans_count) is often only requested from the
                # creator home shell, not the stats dashboard. Fetch it once when
                # the stats navigation did not already observe it.
                if personal_info_response is None:
                    with contextlib.suppress(Exception):
                        await page.goto(
                            CREATOR_HOME_PAGE,
                            wait_until="domcontentloaded",
                            timeout=min(10_000, int(self._timeout * 1000)),
                        )
                        await asyncio.wait_for(
                            personal_ready.wait(), timeout=min(4.0, self._timeout)
                        )
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)

                account_body = account_response[1]
                profile_body = profile_response[1] if profile_response is not None else {}
                if isinstance(account_body, dict):
                    account_body = dict(account_body)
                    account_body["_creator_insights"] = {
                        "audience_source": insight_responses.get(AUDIENCE_SOURCE_PATH, (0, {}))[1],
                        "audience_periods": insight_responses.get(AUDIENCE_PERIODS_PATH, (0, {}))[
                            1
                        ],
                        "note_detail": insight_responses.get(NOTE_DETAIL_PATH, (0, {}))[1],
                    }
                    if personal_info_response is not None:
                        account_body["_personal_info"] = personal_info_response[1]
                return (
                    account_body if isinstance(account_body, dict) else {},
                    profile_body if isinstance(profile_body, dict) else {},
                    raw_notes,
                )
            finally:
                with contextlib.suppress(Exception):
                    page.remove_listener("response", on_response)
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                with contextlib.suppress(Exception):
                    await page.close()

    async def get(
        self, url: str, *, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any] | list[Any] | None]:
        """Compatibility adapter for callers that fetch one logical resource.

        ``headers`` are deliberately ignored: the native page owns signed
        request construction.  The date type is retained so compatibility
        callers receive the requested dashboard period as well.
        """
        date_type = (params or {}).get("date_type")
        period = "7d" if str(date_type) == "1" else "30d"
        account_body, profile_body, notes = await self.fetch_creator_center(
            max_pages=1, period=period
        )
        path = urlsplit(url).path
        if path == ACCOUNT_OVERVIEW_PATH:
            return 200, account_body
        if path == CREATOR_PROFILE_PATH:
            return 200, profile_body
        if path in (NOTE_LIST_PATH, LEGACY_NOTE_LIST_PATH):
            return 200, {"data": {"notes": notes}}
        raise CreatorStatsFetchError(f"unsupported CDP creator endpoint: {path}")

    async def _cleanup(self) -> None:
        if self._browser is not None:
            with contextlib.suppress(Exception):
                await self._browser.close()  # disconnect only; 宿主 Chrome 由 launcher 管
            self._browser = None
        if self._playwright is not None:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
            self._playwright = None

    async def aclose(self) -> None:
        await self._cleanup()


@dataclass
class FixtureTransport:
    """Transport that returns fixed payloads (dry-run / tests)."""

    account_payload: dict[str, Any]
    notes_payload: Any
    status_code: int = 200

    async def get(
        self, url: str, *, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any] | list[Any] | None]:
        # Prefer path-segment match so ".../account/base" is not confused with notes.
        if "/note/" in url or url.rstrip("/").endswith("analyze/list"):
            return self.status_code, self.notes_payload
        return self.status_code, self.account_payload

    async def aclose(self) -> None:
        """No-op for fixture transport."""
        return None


def _creator_headers(cookie: str) -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cookie": cookie,
        "Origin": XHSApiEndpoints.CREATOR_URL,
        "Referer": CREATOR_STATS_PAGE,
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
    }


def _unwrap_api_body(body: dict[str, Any] | list[Any] | None) -> Any:
    if body is None:
        return None
    if isinstance(body, list):
        return body
    if not isinstance(body, dict):
        return body
    # Common envelopes: {success, data}, {code, data}, {result}
    if body.get("success") is False:
        msg = body.get("msg") or body.get("message") or "creator API returned success=false"
        raise CreatorStatsFetchError(str(msg))
    code = body.get("code")
    if code is not None and code not in (0, 200, "0", "200"):
        msg = body.get("msg") or body.get("message") or f"creator API code={code}"
        raise CreatorStatsFetchError(str(msg))
    if "data" in body:
        return body["data"]
    if "result" in body:
        return body["result"]
    return body


def _note_detail_id(url: str) -> str:
    """Extract a note id from Creator Center detail request URLs."""
    query = parse_qs(urlsplit(url).query)
    for key in ("note_id", "noteId", "note-id"):
        value = query.get(key, [""])[0]
        if value:
            return str(value).strip()
    return ""


def _note_detail_map(body: dict[str, Any] | list[Any] | None) -> dict[str, dict[str, Any]]:
    """Extract optional per-note detail rows without retaining auth fields."""
    root = _unwrap_api_body(body)
    found: dict[str, dict[str, Any]] = {}

    def visit(value: Any, depth: int = 0) -> None:
        if depth > 5:
            return
        if isinstance(value, list):
            for item in value[:200]:
                visit(item, depth + 1)
            return
        if not isinstance(value, dict):
            return
        note_id = value.get("note_id") or value.get("noteId") or value.get("id")
        if note_id not in (None, ""):
            found[str(note_id)] = dict(value)
        for key in ("data", "result", "notes", "items", "list", "records"):
            child = value.get(key)
            if isinstance(child, (dict, list)):
                visit(child, depth + 1)

    visit(root)
    return found


def _note_detail_snapshot(
    responses: dict[str, tuple[int, dict[str, Any] | list[Any] | None]],
) -> dict[str, Any]:
    """Flatten the note-detail response quartet into normalize-friendly fields."""

    def data_for(path: str) -> Any:
        item = responses.get(path)
        if item is None:
            return None
        try:
            return _unwrap_api_body(item[1])
        except CreatorStatsFetchError:
            return None

    base = data_for(NOTE_BASE_PATH)
    source = data_for(NOTE_AUDIENCE_SOURCE_PATH)
    profile = data_for(NOTE_AUDIENCE_PROFILE_PATH)
    trend = data_for(NOTE_AUDIENCE_TREND_PATH)
    enriched: dict[str, Any] = {}

    # Base contains the authoritative scalar metrics for this note.  Restrict
    # the merge to public metric aliases; response envelopes may contain other
    # page state that should never be persisted as note fields.
    if isinstance(base, dict):
        metric_keys = (
            "view_count",
            "like_count",
            "comment_count",
            "collect_count",
            "share_count",
            "impl_count",
            "rise_fans_count",
            "view_time_avg",
            "cover_click_rate",
            "full_view_rate",
            "finish5s_rate",
            "exit_view2s_rate",
            "note_post_days",
        )
        for key in metric_keys:
            if key in base:
                enriched[key] = base[key]
        note_info = base.get("note_info")
        if isinstance(note_info, dict):
            for source_key, target_key in (
                ("note_id", "note_id"),
                ("title", "title"),
                ("desc", "desc"),
                ("cover", "cover_url"),
                ("cover_url", "cover_url"),
                ("tags", "tags"),
            ):
                if note_info.get(source_key) not in (None, ""):
                    enriched[target_key] = note_info[source_key]

    if isinstance(source, dict):
        source_rows = source.get("source") or source.get("sources")
        if isinstance(source_rows, list):
            enriched["view_sources"] = [row for row in source_rows if isinstance(row, dict)]

    if isinstance(profile, dict):
        profile_rows: list[dict[str, Any]] = []
        for dimension in ("gender", "age", "city", "region", "interest"):
            values = profile.get(dimension)
            if isinstance(values, dict):
                values = [values]
            if not isinstance(values, list):
                continue
            for row in values:
                if isinstance(row, dict):
                    profile_rows.append({"dimension": dimension, **row})
        if profile_rows:
            enriched["audience_profile"] = profile_rows

    if isinstance(trend, dict):
        trend_rows = trend.get("trend_list") or trend.get("trend")
        if isinstance(trend_rows, list):
            enriched["audience_trend"] = [row for row in trend_rows if isinstance(row, dict)]

    detail_metrics: dict[str, Any] = {}
    if isinstance(base, dict):
        detail_metrics["base"] = base
    if isinstance(trend, dict):
        detail_metrics["audience_trend"] = trend
    if detail_metrics:
        enriched["detail_metrics"] = detail_metrics
    return enriched


class CreatorStatsClient:
    """Fetch account + note stats from the creator statistics surface."""

    def __init__(
        self,
        cookie: str = "",
        *,
        transport: Transport | None = None,
        base_url: str = XHSApiEndpoints.CREATOR_URL,
        cdp_endpoint: str = "",
    ):
        self.cookie = cookie
        self.base_url = base_url.rstrip("/")
        # 优先级：注入的 transport > cdp_endpoint（CDP）> cookie（httpx fallback）。
        # CDP 模式连宿主已登录 Chrome，cookie jar 自带，不碰 Cookie header。
        if transport is not None:
            self.transport: Transport = transport
        elif cdp_endpoint:
            self.transport = CdpTransport(cdp_endpoint)
        else:
            self.transport = HttpxTransport()

    async def aclose(self) -> None:
        """Close any transport-backed resources (CDP connection).

        Guards transports that predate the ``aclose`` protocol member.
        """
        close = getattr(self.transport, "aclose", None)
        if close is not None:
            await close()

    async def fetch_account_overview(self, period: str = "30d") -> dict[str, Any]:
        url = f"{self.base_url}{ACCOUNT_OVERVIEW_PATH}"
        params = {"date_type": period_to_date_type(period)}
        status, body = await self.transport.get(
            url, headers=_creator_headers(self.cookie), params=params
        )
        if status == 401 or status == 403:
            raise CreatorStatsFetchError("creator stats auth failed", status_code=status)
        if status >= 400:
            raise CreatorStatsFetchError(
                f"creator stats account overview HTTP {status}", status_code=status
            )
        data = _unwrap_api_body(body)
        # Empty overview (null / []) is common for new accounts — degrade to {}
        # so note-list import can still proceed.
        if data is None or data == [] or data == {}:
            return {}
        if not isinstance(data, dict):
            raise CreatorStatsFetchError(
                f"unexpected account overview shape: {type(data).__name__}"
            )
        return data

    async def fetch_note_list(
        self, *, page_num: int = 1, page_size: int = 50, note_type: int = 0
    ) -> Any:
        # Clamp pagination — page_size<=0 would never satisfy len(items)<page_size
        # for non-empty pages and could burn max_pages uselessly.
        # Note: do not use `x or default` — 0 is a valid invalid input to clamp.
        try:
            page_num = int(page_num)
        except (TypeError, ValueError):
            page_num = 1
        try:
            page_size = int(page_size)
        except (TypeError, ValueError):
            page_size = 50
        page_num = max(1, page_num)
        page_size = max(1, min(page_size, 100))
        url = f"{self.base_url}{NOTE_LIST_PATH}"
        params: dict[str, Any] = {
            "type": note_type,
            "page_size": page_size,
            "page_num": page_num,
        }
        status, body = await self.transport.get(
            url, headers=_creator_headers(self.cookie), params=params
        )
        if status == 401 or status == 403:
            raise CreatorStatsFetchError("creator stats auth failed", status_code=status)
        if status >= 400:
            raise CreatorStatsFetchError(
                f"creator stats note list HTTP {status}", status_code=status
            )
        return _unwrap_api_body(body)

    async def fetch_all(
        self,
        account_id: str,
        *,
        period: str = "30d",
        max_pages: int = 50,
        page_size: int = 50,
        detail_filter: Callable[[dict[str, Any]], bool] | None = None,
        body_filter: Callable[[dict[str, Any]], bool] | None = None,
    ) -> CreatorStatsBundle:
        """Fetch account overview + paginated notes, return normalized bundle."""
        try:
            page_size = int(page_size)
        except (TypeError, ValueError):
            page_size = 50
        try:
            max_pages = int(max_pages)
        except (TypeError, ValueError):
            max_pages = 50
        page_size = max(1, min(page_size, 100))
        max_pages = max(1, min(max_pages, 50))
        period_norm = normalize_period(period)
        if isinstance(self.transport, CdpTransport):
            # Forward optional filters only when set, so mocked transports in
            # older tests keep seeing the original two-keyword call shape.
            cdp_kwargs: dict[str, Any] = {"max_pages": max_pages, "period": period_norm}
            if detail_filter is not None:
                cdp_kwargs["detail_filter"] = detail_filter
            if body_filter is not None:
                cdp_kwargs["body_filter"] = body_filter
            account_raw, profile_raw, notes_raw = await self.transport.fetch_creator_center(
                **cdp_kwargs
            )
            return normalize_bundle(
                account_raw,
                notes_raw,
                account_id,
                period=period_norm,
                profile_raw=profile_raw,
            )
        account_raw = await self.fetch_account_overview(period=period_norm)
        all_notes: list[Any] = []
        for page in range(1, max_pages + 1):
            page_data = await self.fetch_note_list(page_num=page, page_size=page_size)
            if page_data is None:
                break
            # Shared extractor: notes / note_list / note_infos / list / …
            items = extract_note_items(page_data)
            if not items:
                break
            all_notes.extend(items)
            if len(items) < page_size:
                break

        return normalize_bundle(
            account_raw,
            all_notes,
            account_id,
            period=period_norm,
        )
