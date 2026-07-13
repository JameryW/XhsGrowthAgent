"""Authenticated fetch client for creator-center statistics APIs.

Product surface: https://creator.xiaohongshu.com/statistics/account/v2
Underlying JSON APIs live under creator.xiaohongshu.com/api/galaxy/...

Transport is injectable so unit tests never need live cookies.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit

import httpx

from backend.services.creator_stats.normalize import extract_note_items, normalize_bundle
from backend.services.creator_stats.types import CreatorStatsBundle
from backend.services.xhs_api import XHSApiEndpoints

logger = logging.getLogger("xhs_growth.creator_stats.client")

# Creator-center statistics surface (product UI)
CREATOR_STATS_PAGE = "https://creator.xiaohongshu.com/statistics/account/v2"

# Galaxy/datacenter endpoints used by the account statistics page.
# Paths are reverse-engineered and may change; client isolates that risk.
ACCOUNT_OVERVIEW_PATH = "/api/galaxy/v2/creator/datacenter/account/base"
CREATOR_PROFILE_PATH = "/api/galaxy/user/info"
# This is the signed endpoint that the Creator Center's Note Manager itself
# calls.  It is intentionally distinct from the legacy cookie/httpx endpoint:
# current creator-center requests require browser-generated x-s/x-t headers.
NOTE_LIST_PATH = "/api/galaxy/v2/creator/note/user/posted"
LEGACY_NOTE_LIST_PATH = "/api/galaxy/creator/datacenter/note/analyze/list"
# Optional aggregate insight surfaces loaded by the statistics dashboard.
AUDIENCE_SOURCE_PATH = "/api/galaxy/v2/creator/datacenter/audience/source/account"
AUDIENCE_PERIODS_PATH = "/api/galaxy/v2/creator/datacenter/audience/view/periods"
NOTE_DETAIL_PATH = "/api/galaxy/creator/data/note_detail_new"
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

    def __init__(self, cdp_endpoint: str, *, timeout: float = 30.0):
        self.cdp_endpoint = cdp_endpoint
        self._timeout = timeout
        self._playwright: Any = None
        self._browser: Any = None
        self._fetch_lock = asyncio.Lock()

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
            raw = parse_qs(urlsplit(url).query).get("page", ["0"])[0]
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _validate_creator_response(
        status: int, body: dict[str, Any] | list[Any] | None, *, operation: str
    ) -> None:
        if status in (401, 403):
            raise CreatorStatsFetchError(
                f"creator stats auth failed during {operation}", status_code=status
            )
        if status >= 400:
            raise CreatorStatsFetchError(
                f"creator stats {operation} HTTP {status}", status_code=status
            )
        # Reuse the shared envelope validation so platform error code/message
        # becomes the user-facing sync error instead of a misleading empty list.
        _unwrap_api_body(body)

    async def fetch_creator_center(
        self, *, max_pages: int = 50
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        """Capture overview, public profile, and up to ``max_pages`` native note pages.

        The Note Manager starts at page 0 and loads later pages when its own
        ``div.content`` scroll container reaches the bottom.  We only observe
        those requests; no request headers, cookies, or user content are
        fabricated by this service.
        """
        try:
            max_pages = max(1, min(int(max_pages), 50))
        except (TypeError, ValueError):
            max_pages = 50

        async with self._fetch_lock:
            browser = await self._ensure_browser()
            context = browser.contexts[0]
            page = await context.new_page()
            account_response: tuple[int, dict[str, Any] | list[Any] | None] | None = None
            profile_response: tuple[int, dict[str, Any] | list[Any] | None] | None = None
            note_responses: dict[int, tuple[int, dict[str, Any] | list[Any] | None]] = {}
            insight_responses: dict[str, tuple[int, dict[str, Any] | list[Any] | None]] = {}
            account_ready = asyncio.Event()
            profile_ready = asyncio.Event()
            first_notes_ready = asyncio.Event()
            pending: set[asyncio.Task[None]] = set()

            async def capture(response: Any) -> None:
                nonlocal account_response, profile_response
                path = urlsplit(response.url).path
                if path not in (
                    ACCOUNT_OVERVIEW_PATH,
                    CREATOR_PROFILE_PATH,
                    NOTE_LIST_PATH,
                    AUDIENCE_SOURCE_PATH,
                    AUDIENCE_PERIODS_PATH,
                    NOTE_DETAIL_PATH,
                ):
                    return
                try:
                    body: dict[str, Any] | list[Any] | None = await response.json()
                except Exception:
                    body = None
                if path == ACCOUNT_OVERVIEW_PATH:
                    account_response = (response.status, body)
                    account_ready.set()
                    return
                if path == CREATOR_PROFILE_PATH:
                    profile_response = (response.status, body)
                    profile_ready.set()
                    return
                if path in (AUDIENCE_SOURCE_PATH, AUDIENCE_PERIODS_PATH, NOTE_DETAIL_PATH):
                    # These are optional enrichment calls.  A permission or
                    # rollout failure must not discard the note snapshot.
                    insight_responses[path] = (response.status, body)
                    return
                page_index = self._page_index(response.url)
                note_responses[page_index] = (response.status, body)
                if page_index == 0:
                    first_notes_ready.set()

            def on_response(response: Any) -> None:
                task = asyncio.create_task(capture(response))
                pending.add(task)
                task.add_done_callback(pending.discard)

            page.on("response", on_response)
            try:
                try:
                    # Start at the statistics dashboard: it loads the account
                    # overview request we need, then use the site's own menu
                    # transition to Note Manager so the signed note request is
                    # generated by the same app session.
                    await page.goto(
                        CREATOR_STATS_PAGE,
                        wait_until="domcontentloaded",
                        timeout=self._timeout * 1000,
                    )
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
                except Exception as e:
                    raise CreatorStatsFetchError(
                        f"creator note manager did not load: {type(e).__name__}: {e}"
                    ) from e

                try:
                    await asyncio.wait_for(
                        asyncio.gather(account_ready.wait(), first_notes_ready.wait()),
                        timeout=self._timeout,
                    )
                except TimeoutError as e:
                    raise CreatorStatsFetchError(
                        "creator note manager did not return account and first note page; "
                        "verify the profile is logged in"
                    ) from e

                if account_response is None or 0 not in note_responses:
                    raise CreatorStatsFetchError(
                        "creator note manager returned incomplete initial data"
                    )
                self._validate_creator_response(*account_response, operation="account overview")
                self._validate_creator_response(*note_responses[0], operation="note list")
                try:
                    await asyncio.wait_for(profile_ready.wait(), timeout=min(2.0, self._timeout))
                except TimeoutError:
                    # Identity data enriches the snapshot but must not discard already-read stats.
                    logger.info("creator profile response was not observed during stats sync")

                # The Creator Center app itself knows how to generate a fresh
                # signature for every page. Trigger its infinite-scroll path
                # instead of replaying a stale signed request.
                for page_index in range(1, max_pages):
                    previous_pages = len(note_responses)
                    try:
                        await page.locator("div.content").evaluate(
                            """el => {
                                el.scrollTop = el.scrollHeight
                                el.dispatchEvent(new Event('scroll', { bubbles: true }))
                            }"""
                        )
                    except Exception as e:
                        logger.debug(
                            "creator note list cannot scroll for page %s: %s", page_index, e
                        )
                        break
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

                raw_notes: list[dict[str, Any]] = []
                for page_index in sorted(note_responses):
                    _status, body = note_responses[page_index]
                    data = _unwrap_api_body(body)
                    if isinstance(data, dict):
                        items = data.get("notes")
                        if isinstance(items, list):
                            raw_notes.extend(item for item in items if isinstance(item, dict))
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                detail_body = insight_responses.get(NOTE_DETAIL_PATH, (0, {}))[1]
                details = _note_detail_map(detail_body)
                if details:
                    for index, note in enumerate(raw_notes):
                        note_id = note.get("note_id") or note.get("noteId") or note.get("id")
                        detail = details.get(str(note_id))
                        if isinstance(detail, dict):
                            raw_notes[index] = {**note, **detail}
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

        ``headers``/``params`` are deliberately ignored: the native page owns
        signed request construction.  ``fetch_all`` calls ``fetch_creator_center``
        directly to obtain multiple pages efficiently.
        """
        account_body, profile_body, notes = await self.fetch_creator_center(max_pages=1)
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
            account_raw, profile_raw, notes_raw = await self.transport.fetch_creator_center(
                max_pages=max_pages
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
