"""Authenticated fetch client for creator-center statistics APIs.

Product surface: https://creator.xiaohongshu.com/statistics/account/v2
Underlying JSON APIs live under creator.xiaohongshu.com/api/galaxy/...

Transport is injectable so unit tests never need live cookies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

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
NOTE_LIST_PATH = "/api/galaxy/creator/datacenter/note/analyze/list"

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


class HttpxTransport:
    """Default httpx-based transport."""

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


class CreatorStatsClient:
    """Fetch account + note stats from the creator statistics surface."""

    def __init__(
        self,
        cookie: str = "",
        *,
        transport: Transport | None = None,
        base_url: str = XHSApiEndpoints.CREATOR_URL,
    ):
        self.cookie = cookie
        self.transport: Transport = transport or HttpxTransport()
        self.base_url = base_url.rstrip("/")

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
        max_pages: int = 5,
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
            max_pages = 5
        page_size = max(1, min(page_size, 100))
        max_pages = max(1, min(max_pages, 50))
        period_norm = normalize_period(period)
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
