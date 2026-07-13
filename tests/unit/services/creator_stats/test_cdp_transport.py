"""CDP browser-page transport tests for creator stats.

Creator Center signs requests in its own page JavaScript.  These tests stub
the native-page capture boundary so they never need a real Chrome, while
covering the production contract: no copied Cookie/signature headers and the
actual Note Manager response shape is normalized into note stats.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.creator_stats.client import (
    ACCOUNT_OVERVIEW_PATH,
    CREATOR_NOTE_MANAGER_PAGE,
    CREATOR_PROFILE_PATH,
    CREATOR_STATS_PAGE,
    NOTE_AUDIENCE_PROFILE_PATH,
    NOTE_AUDIENCE_SOURCE_PATH,
    NOTE_AUDIENCE_TREND_PATH,
    NOTE_BASE_PATH,
    NOTE_LIST_PATH,
    CdpTransport,
    CreatorStatsClient,
)

pytestmark = pytest.mark.asyncio


def _native_account() -> dict:
    return {
        "code": 0,
        "success": True,
        "data": {
            "seven": {"view_count": 7, "like_count": 2, "publish_note_num": 1},
            "thirty": {"view_count": 30, "like_count": 8, "publish_note_num": 2},
        },
    }


def _native_note() -> dict:
    return {
        "id": "note-1",
        "display_title": "真实笔记",
        "view_count": 100,
        "likes": 11,
        "comments_count": 2,
        "collected_count": 3,
        "shared_count": 4,
        "time": "2026-07-13 10:00",
        "type": "normal",
        "images_list": [{"url": "https://img.example/cover.jpg"}],
    }


def _native_profile() -> dict:
    return {
        "code": 0,
        "success": True,
        "data": {
            "userId": "creator-1",
            "userName": "真实创作者",
            "redId": "creator_red",
            "userAvatar": "https://img.example/avatar.jpg",
            "userDesc": "真实创作者简介",
            "role": "creator",
            "zone": "上海",
            "phone": "must-not-be-persisted",
        },
    }


async def test_cdp_fetch_all_uses_native_creator_page_data():
    """CDP uses the page-captured payload, not a copied Cookie header/API call."""
    transport = CdpTransport("http://127.0.0.1:9222")
    transport.fetch_creator_center = AsyncMock(
        return_value=(_native_account(), _native_profile(), [_native_note()])
    )
    client = CreatorStatsClient(cookie="must-not-be-used", transport=transport)

    bundle = await client.fetch_all("acct", period="30d", max_pages=3)

    transport.fetch_creator_center.assert_awaited_once_with(max_pages=3)
    assert bundle.account.views == 30
    assert bundle.account.likes == 8
    assert bundle.account.note_count == 2
    assert bundle.account.creator_user_id == "creator-1"
    assert bundle.account.creator_name == "真实创作者"
    assert bundle.account.red_id == "creator_red"
    assert bundle.account.avatar_url == "https://img.example/avatar.jpg"
    assert bundle.account.bio == "真实创作者简介"
    assert bundle.account.creator_role == "creator"
    assert bundle.account.zone == "上海"
    assert "phone" not in bundle.account.to_dict()
    assert len(bundle.notes) == 1
    note = bundle.notes[0]
    assert (note.comments, note.collects, note.shares) == (2, 3, 4)
    assert note.cover_url == "https://img.example/cover.jpg"


async def test_cdp_capture_associates_camel_case_note_id_with_profile_responses():
    """Detail API requests using noteId must enrich the matching note."""

    class FakePage:
        def __init__(self) -> None:
            self._response_handler = None

        def on(self, event: str, handler) -> None:
            assert event == "response"
            self._response_handler = handler

        def remove_listener(self, event: str, handler) -> None:
            assert event == "response"
            assert handler is self._response_handler

        async def _emit(self, path: str, body: dict, *, query: str = "") -> None:
            response = SimpleNamespace(
                url=f"https://creator.xiaohongshu.com{path}{query}",
                status=200,
                json=AsyncMock(return_value=body),
            )
            assert self._response_handler is not None
            self._response_handler(response)
            await asyncio.sleep(0)

        async def goto(self, url: str, **_kwargs) -> None:
            if url == CREATOR_STATS_PAGE:
                await self._emit(ACCOUNT_OVERVIEW_PATH, _native_account())
                await self._emit(CREATOR_PROFILE_PATH, _native_profile())
            elif url == CREATOR_NOTE_MANAGER_PAGE:
                await self._emit(NOTE_LIST_PATH, {"data": {"notes": [_native_note()]}})
            else:
                query = "?noteId=note-1"
                await self._emit(NOTE_BASE_PATH, {"data": {"view_count": 100}}, query=query)
                await self._emit(
                    NOTE_AUDIENCE_SOURCE_PATH,
                    {"data": {"source": [{"title": "首页推荐", "value": 48}]}},
                    query=query,
                )
                await self._emit(
                    NOTE_AUDIENCE_PROFILE_PATH,
                    {"data": {"gender": [{"title": "女性", "value": 48}]}},
                    query=query,
                )
                await self._emit(
                    NOTE_AUDIENCE_TREND_PATH,
                    {"data": {"trend_list": [{"title": "10-11点", "value": 22}]}},
                    query=query,
                )

        def get_by_text(self, _text: str, **_kwargs):
            return self

        async def click(self, **_kwargs) -> None:
            await self.goto(CREATOR_NOTE_MANAGER_PAGE)

        def locator(self, _selector: str):
            return self

        async def evaluate(self, _script: str) -> None:
            return None

        async def close(self) -> None:
            return None

    class FakeContext:
        async def new_page(self) -> FakePage:
            return FakePage()

    class FakeBrowser:
        contexts = [FakeContext()]

    transport = CdpTransport("http://127.0.0.1:9222", timeout=1)
    transport._ensure_browser = AsyncMock(return_value=FakeBrowser())
    account, _profile, notes = await transport.fetch_creator_center(max_pages=1)

    assert account["_creator_insights"]["audience_source"] == {}
    assert len(notes) == 1
    assert notes[0]["audience_profile"] == [{"dimension": "gender", "title": "女性", "value": 48}]
    assert notes[0]["view_sources"] == [{"title": "首页推荐", "value": 48}]


async def test_cdp_get_adapts_native_data_without_forwarding_headers():
    transport = CdpTransport("http://127.0.0.1:9222")
    transport.fetch_creator_center = AsyncMock(
        return_value=(_native_account(), _native_profile(), [_native_note()])
    )

    status, account = await transport.get(
        f"https://creator.xiaohongshu.com{ACCOUNT_OVERVIEW_PATH}",
        headers={"Cookie": "must-not-be-forwarded", "x-s": "stale"},
        params={"date_type": 2},
    )
    assert status == 200
    assert account == _native_account()

    status, profile = await transport.get(
        f"https://creator.xiaohongshu.com{CREATOR_PROFILE_PATH}",
        headers={"Cookie": "must-not-be-forwarded"},
    )
    assert status == 200
    assert profile == _native_profile()

    status, notes = await transport.get(
        f"https://creator.xiaohongshu.com{NOTE_LIST_PATH}",
        headers={"Cookie": "must-not-be-forwarded"},
        params={"page": 0},
    )
    assert status == 200
    assert notes == {"data": {"notes": [_native_note()]}}
    assert transport.fetch_creator_center.await_count == 3


async def test_cdp_transport_aclose_clears_state():
    transport = CdpTransport("http://127.0.0.1:9222")
    browser = MagicMock()
    browser.close = AsyncMock()
    playwright = MagicMock()
    playwright.stop = AsyncMock()
    transport._browser = browser
    transport._playwright = playwright

    await transport.aclose()

    browser.close.assert_awaited_once()
    playwright.stop.assert_awaited_once()
    assert transport._browser is None
    assert transport._playwright is None
    # Idempotent — safe to call when nothing is connected.
    await transport.aclose()


async def test_client_aclose_safe_for_transport_without_aclose():
    """Back-compat: test-only transports may predate ``aclose``."""

    class _NoCloseTransport:
        async def get(self, url, *, headers, params=None):
            return 200, {}

    client = CreatorStatsClient(transport=_NoCloseTransport())
    await client.aclose()
